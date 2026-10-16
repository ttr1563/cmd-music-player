package player

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestMain(m *testing.M) {
	if os.Getenv("FEST_DECODER_FIXTURE") == "1" {
		for _, arg := range os.Args[1:] {
			if strings.Contains(arg, "signed-secret") || strings.Contains(arg, "https://") {
				os.Exit(3)
			}
		}
		io.Copy(os.Stdout, os.Stdin)
		os.Exit(0)
	}
	os.Exit(m.Run())
}

type fakeSound struct {
	mu       sync.Mutex
	playing  bool
	volume   float64
	reader   io.Reader
	done     chan struct{}
	once     sync.Once
	received bytes.Buffer
}

func (s *fakeSound) Play() {
	select {
	case <-s.done:
		return
	default:
	}
	s.mu.Lock()
	s.playing = true
	s.mu.Unlock()
	s.once.Do(func() {
		go func() { io.Copy(&s.received, s.reader); s.mu.Lock(); s.playing = false; s.mu.Unlock(); close(s.done) }()
	})
}
func (s *fakeSound) Pause()              { s.mu.Lock(); s.playing = false; s.mu.Unlock() }
func (s *fakeSound) Close() error        { <-s.done; return nil }
func (s *fakeSound) SetVolume(v float64) { s.volume = v }
func (s *fakeSound) SetBufferSize(int)   {}
func (s *fakeSound) BufferedSize() int   { return 0 }
func (s *fakeSound) Err() error          { return nil }
func (s *fakeSound) IsPlaying() bool     { s.mu.Lock(); defer s.mu.Unlock(); return s.playing }

type testTransport func(*http.Request) (*http.Response, error)

func (t testTransport) RoundTrip(r *http.Request) (*http.Response, error) { return t(r) }
func TestPrivatePipePlaybackEOFAndVolume(t *testing.T) {
	t.Setenv("FEST_DECODER_FIXTURE", "1")
	exe, _ := os.Executable()
	var device *fakeSound
	pcm := bytes.Repeat([]byte{1, 2, 3, 4}, 1000)
	p := New(70)
	p.decoderPath = exe
	p.transport = testTransport(func(r *http.Request) (*http.Response, error) {
		if r.Header.Get("Cookie") != "" || r.Header.Get("Authorization") != "" {
			t.Error("credentials forwarded")
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(pcm)), Header: http.Header{}}, nil
	})
	p.factory = func(r io.Reader) (sound, error) {
		device = &fakeSound{reader: r, done: make(chan struct{})}
		return device, nil
	}
	if err := p.Play(context.Background(), "https://r1.googlevideo.com/audio?signed-secret=true", 0); err != nil {
		t.Fatal(err)
	}
	defer p.Stop()
	p.Pause()
	if !p.paused {
		t.Fatal("pause failed")
	}
	p.Pause()
	p.SetVolume(150)
	if p.Volume != 100 || device.volume != 1 {
		t.Fatal("volume cap failed")
	}
	select {
	case <-device.done:
	case <-time.After(3 * time.Second):
		t.Fatal("PCM pipe did not finish")
	}
	if !bytes.Equal(device.received.Bytes(), pcm) {
		t.Fatal("PCM data lost")
	}
	deadline := time.Now().Add(3 * time.Second)
	for {
		eof, err := p.Poll()
		if err != nil {
			t.Fatal(err)
		}
		if eof {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("EOF not reported")
		}
		time.Sleep(time.Millisecond * 10)
	}
	if p.command.ProcessState == nil || !p.command.ProcessState.Exited() {
		t.Fatal("decoder not reaped")
	}
}

type blockedBody struct {
	ctx  context.Context
	sent bool
}

func (b *blockedBody) Read(p []byte) (int, error) {
	if !b.sent {
		b.sent = true
		return copy(p, make([]byte, 8)), nil
	}
	<-b.ctx.Done()
	return 0, b.ctx.Err()
}
func (b *blockedBody) Close() error { return nil }
func TestStopCancelsAndReapsDecoder(t *testing.T) {
	t.Setenv("FEST_DECODER_FIXTURE", "1")
	exe, _ := os.Executable()
	p := New(70)
	p.decoderPath = exe
	p.transport = testTransport(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Body: &blockedBody{ctx: r.Context()}, Header: http.Header{}}, nil
	})
	p.factory = func(r io.Reader) (sound, error) { return &fakeSound{reader: r, done: make(chan struct{})}, nil }
	if err := p.Play(context.Background(), "https://r1.googlevideo.com/audio", 0); err != nil {
		t.Fatal(err)
	}
	command := p.command
	done := make(chan struct{})
	go func() { p.Stop(); close(done) }()
	select {
	case <-done:
	case <-time.After(4 * time.Second):
		t.Fatal("stop blocked")
	}
	if command.ProcessState == nil {
		t.Fatal("decoder not reaped")
	}
}
func TestUnsafeURLRejectedBeforeNetwork(t *testing.T) {
	p := New(70)
	called := false
	p.transport = testTransport(func(*http.Request) (*http.Response, error) { called = true; return nil, nil })
	if err := p.Play(context.Background(), "https://evil.invalid/signed-secret", 0); err == nil || strings.Contains(err.Error(), "signed-secret") {
		t.Fatal("unsafe error", err)
	}
	if called {
		t.Fatal("unsafe network access")
	}
}

func TestDecoderFollowsInstalledCommandSymlink(t *testing.T) {
	root := t.TempDir()
	bundle := filepath.Join(root, "bundle")
	os.MkdirAll(filepath.Join(bundle, "runtime"), 0755)
	executable := filepath.Join(bundle, "fest")
	decoder := filepath.Join(bundle, "runtime", "ffmpeg")
	os.WriteFile(executable, []byte("fixture"), 0755)
	os.WriteFile(decoder, []byte("fixture"), 0755)
	link := filepath.Join(root, "fest")
	if err := os.Symlink(executable, link); err != nil {
		t.Skip("symlink unavailable")
	}
	actual, err := decoderAt(link)
	if err != nil {
		t.Fatal(err)
	}
	expected, _ := filepath.EvalSymlinks(decoder)
	if actual != expected {
		t.Fatalf("decoder is outside bundle: %s", actual)
	}
}
