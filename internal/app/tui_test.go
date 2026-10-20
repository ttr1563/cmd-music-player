package app

import (
	"context"
	"github.com/gdamore/tcell/v2"
	"github.com/ttr1563/cmd-music-player/internal/service"
	"github.com/ttr1563/cmd-music-player/internal/store"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestTUIClosesOnCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	screen := tcell.NewSimulationScreen("UTF-8")
	done := make(chan error, 1)
	go func() { done <- runTUI(ctx, service.New(nil), store.DefaultConfig(), "guest", screen) }()
	time.Sleep(100 * time.Millisecond)
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("TUI did not close")
	}
}
func TestTUIQuitKey(t *testing.T) {
	screen := tcell.NewSimulationScreen("UTF-8")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- runTUI(ctx, service.New(nil), store.DefaultConfig(), "guest", screen) }()
	time.Sleep(100 * time.Millisecond)
	screen.InjectKey(tcell.KeyCtrlQ, 0, tcell.ModNone)
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("quit key failed")
	}
}

type brokenScreen struct{ tcell.Screen }

func (brokenScreen) Init() error { return context.Canceled }
func (brokenScreen) Fini()       { panic("Fini called on uninitialized terminal") }
func TestTUIInitializationFailureIsSafe(t *testing.T) {
	if err := runTUI(context.Background(), service.New(nil), store.DefaultConfig(), "guest", brokenScreen{tcell.NewSimulationScreen("UTF-8")}); err == nil {
		t.Fatal("initialization failure ignored")
	}
}

type screenTransport func(*http.Request) (*http.Response, error)

func (f screenTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestTUISearchRendersServiceResults(t *testing.T) {
	m := service.New(nil)
	m.HTTP.Transport = screenTransport(func(r *http.Request) (*http.Response, error) {
		body := `{"INNERTUBE_CLIENT_VERSION":"1.20261013.15.00"}`
		if r.Method == "POST" {
			body = `{"musicResponsiveListItemRenderer":{"playlistItemData":{"videoId":"abcdefghijk"},"flexColumns":[{"musicResponsiveListItemFlexColumnRenderer":{"text":{"simpleText":"Fixture Song"}}}]}}`
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(body))}, nil
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	screen := tcell.NewSimulationScreen("UTF-8")
	done := make(chan error, 1)
	go func() { done <- runTUI(ctx, m, store.DefaultConfig(), "guest", screen) }()
	time.Sleep(100 * time.Millisecond)
	for _, r := range "query" {
		screen.InjectKey(tcell.KeyRune, r, tcell.ModNone)
	}
	screen.InjectKey(tcell.KeyEnter, 0, tcell.ModNone)
	deadline := time.Now().Add(3 * time.Second)
	found := false
	for time.Now().Before(deadline) {
		cells, _, _ := screen.GetContents()
		var b strings.Builder
		for _, cell := range cells {
			b.WriteString(string(cell.Runes))
		}
		if strings.Contains(b.String(), "Fixture Song") {
			found = true
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("TUI did not exit")
	}
	if !found {
		t.Fatal("service results not shown")
	}
}
