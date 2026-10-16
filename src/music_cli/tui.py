"""Terminal interface; browsing does not interrupt the current track."""

from __future__ import annotations

import asyncio
import queue

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Footer, Header, Input, Static
from textual.worker import WorkerCancelled

from .player import Player
from .provider import Item, YouTubeMusic
from .storage import UserError


class MusicApp(App):
    TITLE = "fest · YouTube Music"
    CSS = """
    Screen { layout: vertical; }
    #identity { height: 1; padding: 0 1; color: $text-muted; }
    #search { margin: 1 1 0 1; }
    .toolbar { height: auto; padding: 0 1; }
    Button { min-width: 9; margin-right: 1; }
    #results { height: 1fr; margin: 0 1; }
    #now { height: 2; padding: 0 1; color: $accent; }
    #status { height: 2; padding: 0 1; }
    """
    BINDINGS = [("ctrl+q", "quit", "終了"), ("ctrl+f", "search", "検索")]

    def __init__(
        self,
        provider: YouTubeMusic,
        config: dict,
        guest: bool = False,
        player: Player | None = None,
    ):
        super().__init__()
        self.provider = provider
        self.settings = config
        self.account = "guest" if guest else config["account"] or "guest"
        self.player = player or Player(provider.headers, config["volume"])
        self.items: list[Item] = []
        self.upcoming: list[Item] = []
        self.current: Item | None = None
        self.loading = False
        self.stopping = False
        self.browse_worker = None
        self.play_worker = None
        self.play_generation = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"account: {self.account} · Ctrl+Qで再生も終了", id="identity")
        yield Input(placeholder="曲名・アーティストを検索してEnter", id="search")
        with Horizontal(classes="toolbar"):
            yield Button("ライブラリ", id="library")
            yield Button("プレイリスト", id="playlists")
            yield Button("キューに追加", id="enqueue")
        yield DataTable(id="results", cursor_type="row")
        yield Static("選曲してください", id="now", markup=False)
        with Horizontal(classes="toolbar"):
            yield Button("一時停止/再開", id="pause")
            yield Button("次へ", id="next")
            yield Button("停止", id="stop")
            yield Button("−10秒", id="back")
            yield Button("+10秒", id="forward")
            yield Button("音量−", id="quieter")
            yield Button("音量+", id="louder")
        yield Static("検索して曲を選択。音声のみ再生します。", id="status", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("曲 / プレイリスト", "アーティスト")
        self.query_one(Input).focus()
        self.set_interval(0.25, self.poll_player)

    def status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def now(self) -> None:
        title = self.current.title if self.current else "停止中"
        self.query_one("#now", Static).update(
            f"{title} · 待ち {len(self.upcoming)}曲 · 音量 {self.player.volume}%"
        )

    def action_search(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if query:
            self.browse_worker = self.browse("search", query)

    @work(exclusive=True, group="browse")
    async def browse(self, operation: str, argument: str | None = None) -> None:
        self.status("読み込み中…")
        try:
            method = getattr(self.provider, operation)
            rows = (
                await asyncio.to_thread(method, argument)
                if argument
                else await asyncio.to_thread(
                    method,
                )
            )
            self.items = rows
            table = self.query_one(DataTable)
            table.clear()
            for item in rows:
                table.add_row(Text(item.title), Text(item.subtitle))
            table.focus()
            self.status(
                f"{len(rows)}件（検索は最大30件、ライブラリ/playlistは最大100件）。Enterで選択。"
            )
        except UserError as error:
            self.status(str(error))

    def selected(self) -> Item | None:
        index = self.query_one(DataTable).cursor_row
        return self.items[index] if 0 <= index < len(self.items) else None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        item = self.selected()
        if item is None:
            return
        if item.kind == "playlist":
            self.browse_worker = self.browse("playlist", item.id)
        else:
            index = self.query_one(DataTable).cursor_row
            self.upcoming = self.items[index + 1 :].copy()
            self.begin(item)

    def begin(self, item: Item) -> None:
        self.current = item
        self.loading = True
        self.play_generation += 1
        self.play_worker = self.play_item(item, self.play_generation)
        self.now()

    @work(exclusive=True, group="playback")
    async def play_item(self, item: Item, generation: int) -> None:
        self.loading = True
        self.status("音声を準備中…")
        try:
            self.player.start()
            # Previous stop/eof events must not advance the new queue.
            while not self.player.events.empty():
                self.player.events.get_nowait()
            await self.player.play(item)
            self.status("再生中。終了はCtrl+Q。")
        except UserError as error:
            self.upcoming.clear()
            self.current = None
            self.now()
            self.status(str(error))
        finally:
            if generation == self.play_generation:
                self.loading = False

    async def stop(self) -> None:
        if self.play_worker is not None and not self.play_worker.is_finished:
            self.play_worker.cancel()
            # Wait for resolver's finally block before clearing state.
            try:
                await self.play_worker.wait()
            except WorkerCancelled:
                pass
        self.upcoming.clear()
        self.current = None
        self.player.command("stop")
        self.now()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        name = event.button.id
        try:
            if name in ("library", "playlists"):
                self.browse_worker = self.browse(name)
            elif name == "enqueue":
                item = self.selected()
                if item and item.kind == "song":
                    self.upcoming.append(item)
                    self.now()
                    self.status("キューに追加しました。「次へ」で開始できます。")
            elif name == "next":
                if self.upcoming:
                    self.begin(self.upcoming.pop(0))
                else:
                    await self.stop()
                    self.status("キューの末尾です。")
            elif name == "stop":
                await self.stop()
                self.status("停止しました。")
            elif name == "pause":
                self.player.command("cycle", "pause")
            elif name in ("back", "forward"):
                self.player.command("seek", -10 if name == "back" else 10, "relative")
            elif name in ("quieter", "louder"):
                self.player.volume = max(
                    0, min(100, self.player.volume + (-5 if name == "quieter" else 5))
                )
                self.player.command("set_property", "volume", self.player.volume)
                self.now()
        except UserError as error:
            self.status(str(error))

    def poll_player(self) -> None:
        if self.stopping:
            return
        self.player.poll()
        while True:
            try:
                event = self.player.events.get_nowait()
            except queue.Empty:
                break
            if self.loading or self.current is None:
                continue
            reason = event.get("reason")
            if reason == "eof":
                if self.upcoming:
                    self.begin(self.upcoming.pop(0))
                else:
                    self.current = None
                    self.now()
                    self.status("再生が終了しました。")
            elif reason == "error":
                self.upcoming.clear()
                self.current = None
                self.now()
                self.status(
                    event.get("message") or "音声の再生に失敗しました。曲を再選択してください。"
                )

    async def on_unmount(self) -> None:
        self.stopping = True
        await self.player.close()
