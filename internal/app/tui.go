package app

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/gdamore/tcell/v2"
	"github.com/rivo/tview"
	"github.com/ttr1563/cmd-music-player/internal/player"
	"github.com/ttr1563/cmd-music-player/internal/service"
	"github.com/ttr1563/cmd-music-player/internal/store"
)

type event struct {
	kind       string
	generation int
	items      []service.Item
	message    string
}
type operation struct {
	kind       string
	generation int
	ctx        context.Context
	item       service.Item
	value      int
}

func TUI(parent context.Context, music *service.Music, config store.Config, identity string) error {
	screen, err := tcell.NewScreen()
	if err != nil {
		return fmt.Errorf("対話端末を開けません。")
	}
	return runTUI(parent, music, config, identity, screen)
}

type initializedScreen struct{ tcell.Screen }

func (initializedScreen) Init() error { return nil }
func runTUI(parent context.Context, music *service.Music, config store.Config, identity string, screen tcell.Screen) error {
	if parent.Err() != nil {
		return nil
	}
	if err := screen.Init(); err != nil {
		return fmt.Errorf("対話端末を初期化できません。通常のターミナルで実行してください。")
	}
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	application := tview.NewApplication().SetScreen(initializedScreen{screen})
	events := make(chan event, 32)
	operations := make(chan operation, 16)
	var workers sync.WaitGroup
	emit := func(e event) {
		select {
		case events <- e:
		case <-ctx.Done():
		}
	}
	workers.Add(1)
	go func() {
		defer workers.Done()
		p := player.New(config.Volume)
		defer p.Stop()
		generation := 0
		playCtx := ctx
		ticker := time.NewTicker(200 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case op := <-operations:
				if op.kind == "play" {
					generation = op.generation
					playCtx = op.ctx
					p.Stop()
					if op.ctx.Err() != nil {
						continue
					}
					raw, err := service.ResolveProcess(op.ctx, music.Headers, op.item.ID)
					if err == nil {
						err = p.Play(op.ctx, raw, 0)
					}
					if err != nil {
						emit(event{kind: "error", generation: generation, message: err.Error()})
					} else {
						emit(event{kind: "playing", generation: generation, message: "再生中です。"})
					}
				} else {
					switch op.kind {
					case "stop":
						p.Stop()
					case "pause":
						p.Pause()
					case "volume":
						p.SetVolume(op.value)
					case "seek":
						if err := p.Seek(playCtx, float64(op.value)); err != nil {
							p.Stop()
							emit(event{kind: "error", generation: generation, message: err.Error()})
						}
					}
				}
			case <-ticker.C:
				eof, err := p.Poll()
				if err != nil {
					p.Stop()
					emit(event{kind: "error", generation: generation, message: err.Error()})
				} else if eof {
					p.Stop()
					emit(event{kind: "eof", generation: generation})
				}
			}
		}
	}()
	// PostEvent is nonblocking; all widget mutations remain on tview's event loop.
	go func() {
		ticker := time.NewTicker(100 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				application.Stop()
				return
			case <-ticker.C:
				if len(events) > 0 {
					screen.PostEvent(tcell.NewEventKey(tcell.KeyF24, 0, tcell.ModNone))
				}
			}
		}
	}()
	table := tview.NewTable().SetSelectable(true, false)
	table.SetBorder(true).SetTitle("曲・プレイリスト")
	status := tview.NewTextView().SetText("検索して曲を選んでください。")
	now := tview.NewTextView()
	identityView := tview.NewTextView().SetText("account: " + tview.Escape(identity) + " · Ctrl+Qで終了")
	search := tview.NewInputField().SetLabel("検索: ")
	results := []service.Item{}
	queue := []service.Item{}
	current := "停止中"
	volume := config.Volume
	playGeneration, browseGeneration := 0, 0
	playCancel := func() {}
	browseCancel := func() {}
	defer func() { playCancel(); browseCancel(); cancel(); workers.Wait() }()
	updateNow := func() {
		now.SetText(fmt.Sprintf("%s · 待ち%d曲 · 音量%d%%", tview.Escape(current), len(queue), volume))
	}
	updateNow()
	send := func(op operation) {
		select {
		case operations <- op:
		default:
			status.SetText("処理中です。少し待ってから操作してください。")
		}
	}
	begin := func(item service.Item) {
		playCancel()
		playGeneration++
		var playContext context.Context
		playContext, playCancel = context.WithCancel(ctx)
		current = item.Title
		updateNow()
		status.SetText("音声を準備しています…")
		send(operation{kind: "play", generation: playGeneration, ctx: playContext, item: item})
	}
	stop := func() {
		playCancel()
		playGeneration++
		queue = nil
		current = "停止中"
		send(operation{kind: "stop"})
		updateNow()
	}
	next := func() {
		if len(queue) > 0 {
			item := queue[0]
			queue = queue[1:]
			begin(item)
		} else {
			stop()
		}
	}
	browse := func(kind, arg string) {
		browseCancel()
		browseGeneration++
		generation := browseGeneration
		var request context.Context
		request, browseCancel = context.WithCancel(ctx)
		status.SetText("読み込み中です…")
		workers.Add(1)
		go func() {
			defer workers.Done()
			items, err := music.Browse(request, kind, arg)
			if request.Err() != nil {
				return
			}
			message := ""
			if err != nil {
				message = err.Error()
			}
			emit(event{kind: "browse", generation: generation, items: items, message: message})
		}()
	}
	search.SetDoneFunc(func(key tcell.Key) {
		if key == tcell.KeyEnter && strings.TrimSpace(search.GetText()) != "" {
			browse("search", search.GetText())
		}
	})
	table.SetSelectedFunc(func(row, column int) {
		if row < 0 || row >= len(results) {
			return
		}
		item := results[row]
		if item.Kind == "playlist" {
			browse("playlist", item.ID)
		} else {
			queue = append([]service.Item{}, results[row+1:]...)
			begin(item)
		}
	})
	focus := []tview.Primitive{search, table}
	controls := tview.NewFlex()
	add := func(label string, fn func()) {
		button := tview.NewButton(label).SetSelectedFunc(fn)
		controls.AddItem(button, 0, 1, false)
		focus = append(focus, button)
	}
	add("ライブラリ", func() { browse("library", "") })
	add("プレイリスト", func() { browse("playlists", "") })
	add("追加", func() {
		row, _ := table.GetSelection()
		if row >= 0 && row < len(results) && results[row].Kind == "song" {
			queue = append(queue, results[row])
			updateNow()
		}
	})
	playback := tview.NewFlex()
	button := func(label string, fn func()) {
		b := tview.NewButton(label).SetSelectedFunc(fn)
		playback.AddItem(b, 0, 1, false)
		focus = append(focus, b)
	}
	button("一時停止/再開", func() { send(operation{kind: "pause"}) })
	button("次へ", next)
	button("停止", stop)
	button("−10秒", func() { send(operation{kind: "seek", value: -10}) })
	button("+10秒", func() { send(operation{kind: "seek", value: 10}) })
	button("音量−", func() { volume = max(0, volume-5); send(operation{kind: "volume", value: volume}); updateNow() })
	button("音量+", func() { volume = min(100, volume+5); send(operation{kind: "volume", value: volume}); updateNow() })
	root := tview.NewFlex().SetDirection(tview.FlexRow).AddItem(identityView, 1, 0, false).AddItem(search, 1, 0, true).AddItem(controls, 1, 0, false).AddItem(table, 0, 1, false).AddItem(now, 1, 0, false).AddItem(playback, 1, 0, false).AddItem(status, 2, 0, false)
	focusIndex := 0
	application.SetInputCapture(func(key *tcell.EventKey) *tcell.EventKey {
		if key.Key() == tcell.KeyCtrlQ || key.Key() == tcell.KeyCtrlC {
			cancel()
			application.Stop()
			return nil
		}
		if key.Key() == tcell.KeyTab {
			focusIndex = (focusIndex + 1) % len(focus)
			application.SetFocus(focus[focusIndex])
			return nil
		}
		if key.Key() == tcell.KeyF24 {
			if ctx.Err() != nil {
				application.Stop()
				return nil
			}
			for {
				select {
				case e := <-events:
					switch e.kind {
					case "browse":
						if e.generation != browseGeneration {
							continue
						}
						if e.message != "" {
							status.SetText(tview.Escape(e.message))
							continue
						}
						results = e.items
						table.Clear()
						for i, item := range results {
							table.SetCell(i, 0, tview.NewTableCell(tview.Escape(item.Title)))
							table.SetCell(i, 1, tview.NewTableCell(tview.Escape(item.Subtitle)))
						}
						table.Select(0, 0)
						application.SetFocus(table)
						focusIndex = 1
						status.SetText(fmt.Sprintf("%d件。Enterで選択します。Tabで操作を切り替えます。", len(results)))
					case "playing":
						if e.generation == playGeneration {
							status.SetText(e.message)
						}
					case "error":
						if e.generation == playGeneration {
							stop()
							status.SetText(tview.Escape(e.message))
						}
					case "eof":
						if e.generation == playGeneration {
							next()
						}
					}
				default:
					return nil
				}
			}
		}
		return key
	})
	return application.EnableMouse(true).SetRoot(root, true).SetFocus(search).Run()
}
