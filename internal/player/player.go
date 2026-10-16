// Package player owns decoding processes and the OS sound output.
package player

import (
	"bufio"
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ebitengine/oto/v3"
	"github.com/ttr1563/cmd-music-player/internal/service"
)

const bytesPerSecond = 48000 * 2 * 4

var audioError = errors.New("音声を再生できません。fest doctorで出力先と同梱decoderを確認してください。")
var audioOnce sync.Once
var audioContext *oto.Context
var audioInitErr error

func output() (*oto.Context, error) {
	audioOnce.Do(func() {
		var ready chan struct{}
		audioContext, ready, audioInitErr = oto.NewContext(&oto.NewContextOptions{SampleRate: 48000, ChannelCount: 2, Format: oto.FormatFloat32LE, BufferSize: 100 * time.Millisecond, ApplicationName: "fest"})
		if audioInitErr == nil {
			select {
			case <-ready:
				audioInitErr = audioContext.Err()
			case <-time.After(10 * time.Second):
				audioInitErr = audioError
			}
		}
	})
	if audioInitErr != nil {
		return nil, audioError
	}
	return audioContext, nil
}
func CheckAudio() error { _, err := output(); return err }
func Decoder() (string, error) {
	executable, err := os.Executable()
	if err != nil {
		return "", err
	}
	return decoderAt(executable)
}
func decoderAt(executable string) (string, error) {
	executable, err := filepath.EvalSymlinks(executable)
	if err != nil {
		return "", err
	}
	name := "ffmpeg"
	if filepath.Ext(executable) == ".exe" {
		name += ".exe"
	}
	p := filepath.Join(filepath.Dir(executable), "runtime", name)
	info, err := os.Stat(p)
	if err != nil || !info.Mode().IsRegular() {
		return "", errors.New("同梱decoderがありません。配布フォルダ一式を展開してください。")
	}
	return p, nil
}

type counted struct {
	reader io.Reader
	bytes  atomic.Int64
	ended  atomic.Bool
}

func (r *counted) Read(p []byte) (int, error) {
	n, err := r.reader.Read(p)
	r.bytes.Add(int64(n))
	if err != nil {
		r.ended.Store(true)
	}
	return n, err
}

type sound interface {
	Play()
	Pause()
	Close() error
	SetVolume(float64)
	SetBufferSize(int)
	BufferedSize() int
	Err() error
	IsPlaying() bool
}

func newSound(r io.Reader) (sound, error) {
	device, err := output()
	if err != nil {
		return nil, err
	}
	return device.NewPlayer(r), nil
}

// Player's public methods are serialized by the application's playback worker.
type Player struct {
	decoderPath string
	transport   http.RoundTripper
	factory     func(io.Reader) (sound, error)
	device      sound
	command     *exec.Cmd
	cancel      context.CancelFunc
	waited      chan error
	source      *counted
	offset      float64
	rawURL      string
	paused      bool
	Volume      int
}

func New(volume int) *Player { return &Player{Volume: volume} }
func (p *Player) Play(parent context.Context, raw string, position float64) error {
	p.Stop()
	if service.ValidateMediaURL(raw) != nil {
		return audioError
	}
	decoder := p.decoderPath
	var err error
	if decoder == "" {
		decoder, err = Decoder()
	}
	if err != nil {
		return err
	}
	ctx, cancel := context.WithCancel(parent)
	client := &http.Client{Transport: &http.Transport{Proxy: nil, DialContext: (&net.Dialer{Timeout: 10 * time.Second}).DialContext, TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 10 * time.Second}, CheckRedirect: func(req *http.Request, via []*http.Request) error {
		if len(via) > 5 {
			return audioError
		}
		return service.ValidateMediaURL(req.URL.String())
	}}
	if p.transport != nil {
		client.Transport = p.transport
	}
	req, _ := http.NewRequestWithContext(ctx, "GET", raw, nil)
	response, err := client.Do(req)
	if err != nil {
		cancel()
		client.CloseIdleConnections()
		return audioError
	}
	if response.StatusCode != 200 {
		response.Body.Close()
		cancel()
		client.CloseIdleConnections()
		return audioError
	}
	args := []string{"-hide_banner", "-loglevel", "quiet", "-nostdin", "-threads", "1", "-filter_threads", "1", "-protocol_whitelist", "pipe", "-i", "pipe:0"}
	if position > 0 {
		args = append(args, "-ss", strconv.FormatFloat(position, 'f', 3, 64))
	}
	args = append(args, "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "48000", "-f", "f32le", "pipe:1")
	command := exec.CommandContext(ctx, decoder, args...)
	command.WaitDelay = 2 * time.Second
	command.Stderr = io.Discard
	input, err := command.StdinPipe()
	if err != nil {
		response.Body.Close()
		cancel()
		return audioError
	}
	outputPipe, err := command.StdoutPipe()
	if err != nil {
		input.Close()
		response.Body.Close()
		cancel()
		return audioError
	}
	if command.Start() != nil {
		input.Close()
		outputPipe.Close()
		response.Body.Close()
		cancel()
		return audioError
	}
	// The Go transport owns TLS and the account-free CDN request, including idle timeout.
	go func() {
		defer input.Close()
		defer response.Body.Close()
		defer client.CloseIdleConnections()
		buffer := make([]byte, 64<<10)
		for {
			timer := time.AfterFunc(5*time.Second, cancel)
			n, readErr := response.Body.Read(buffer)
			timer.Stop()
			if n > 0 {
				if _, writeErr := input.Write(buffer[:n]); writeErr != nil {
					return
				}
			}
			if readErr != nil {
				if readErr != io.EOF {
					cancel()
				}
				return
			}
		}
	}()
	buffered := bufio.NewReader(outputPipe)
	startup := time.AfterFunc(25*time.Second, cancel)
	_, readyErr := buffered.Peek(1)
	startup.Stop()
	if readyErr != nil {
		cancel()
		outputPipe.Close()
		command.Wait()
		return audioError
	}
	source := &counted{reader: buffered}
	factory := p.factory
	if factory == nil {
		factory = newSound
	}
	sound, err := factory(source)
	if err != nil {
		cancel()
		outputPipe.Close()
		command.Wait()
		return audioError
	}
	sound.SetBufferSize(bytesPerSecond * 2)
	sound.SetVolume(float64(p.Volume) / 100)
	p.device = sound
	p.command = command
	p.cancel = cancel
	p.source = source
	p.offset = position
	p.rawURL = raw
	p.paused = false
	p.waited = make(chan error, 1)
	waited := p.waited
	go func() { // Wait after EOF, so Wait cannot close stdout before Oto has read it.
		ticker := time.NewTicker(20 * time.Millisecond)
		defer ticker.Stop()
		for !source.ended.Load() {
			select {
			case <-ctx.Done():
				outputPipe.Close()
				waited <- command.Wait()
				return
			case <-ticker.C:
			}
		}
		waited <- command.Wait()
	}()
	sound.Play()
	return nil
}
func (p *Player) Stop() {
	if p.cancel != nil {
		p.cancel()
	}
	if p.device != nil {
		p.device.Close()
	}
	if p.waited != nil {
		select {
		case <-p.waited:
		case <-time.After(3 * time.Second):
			if p.command != nil && p.command.Process != nil {
				p.command.Process.Kill()
			}
			<-p.waited
		}
	}
	p.device = nil
	p.command = nil
	p.cancel = nil
	p.waited = nil
	p.source = nil
	p.rawURL = ""
	p.paused = false
}
func (p *Player) Pause() {
	if p.device == nil {
		return
	}
	if p.paused {
		p.device.Play()
	} else {
		p.device.Pause()
	}
	p.paused = !p.paused
}
func (p *Player) SetVolume(v int) {
	p.Volume = max(0, min(100, v))
	if p.device != nil {
		p.device.SetVolume(float64(p.Volume) / 100)
	}
}
func (p *Player) Seek(ctx context.Context, delta float64) error {
	if p.device == nil || p.source == nil {
		return nil
	}
	position := p.offset + float64(p.source.bytes.Load()-int64(p.device.BufferedSize()))/bytesPerSecond + delta
	raw := p.rawURL
	paused := p.paused
	if err := p.Play(ctx, raw, max(0, position)); err != nil {
		return err
	}
	if paused {
		p.Pause()
	}
	return nil
}
func (p *Player) Poll() (bool, error) {
	if p.device == nil {
		return false, nil
	}
	if p.device.Err() != nil || (p.factory == nil && audioContext != nil && audioContext.Err() != nil) {
		return false, audioError
	}
	if p.source.ended.Load() && !p.device.IsPlaying() && !p.paused {
		select {
		case err := <-p.waited:
			p.waited = nil
			if err != nil {
				return false, audioError
			}
			return true, nil
		default:
		}
	}
	return false, nil
}
