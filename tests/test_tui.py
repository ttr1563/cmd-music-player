import asyncio
import queue
from unittest.mock import AsyncMock, Mock

from textual.widgets import DataTable, Static

from music_cli.provider import Item
from music_cli.storage import DEFAULT_CONFIG, UserError
from music_cli.tui import MusicApp


def fake_player():
    return Mock(volume=70, events=queue.SimpleQueue(), play=AsyncMock(), close=AsyncMock())


async def test_search_select_queue_advance_and_close():
    tracks = [Item("abcdefghijk", "First"), Item("01234567890", "Second")]
    provider = Mock(headers=None, search=Mock(return_value=tracks))
    player = fake_player()
    app = MusicApp(provider, DEFAULT_CONFIG, player=player)
    async with app.run_test(size=(120, 36)) as pilot:
        app.browse_worker = app.browse("search", "artist")
        await app.browse_worker.wait()
        assert app.query_one(DataTable).row_count == 2
        await pilot.press("enter")
        await app.play_worker.wait()
        assert app.current == tracks[0]
        assert app.upcoming == [tracks[1]]
        player.events.put({"reason": "eof"})
        app.poll_player()
        await app.play_worker.wait()
        assert app.current == tracks[1]
        player.events.put({"reason": "error"})
        app.poll_player()
        assert app.current is None and not app.upcoming
        await pilot.press("ctrl+q")
    player.close.assert_awaited_once()


async def test_guest_library_error_stays_inside_tui():
    provider = Mock(headers=None, library=Mock(side_effect=UserError("ログインが必要")))
    app = MusicApp(provider, DEFAULT_CONFIG, player=fake_player())
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.click("#library")
        await app.browse_worker.wait()
        assert "ログインが必要" in str(app.query_one("#status", Static).render())


async def test_stop_clears_queue_without_exiting():
    player = fake_player()
    app = MusicApp(Mock(headers=None), DEFAULT_CONFIG, player=player)
    async with app.run_test(size=(120, 36)) as pilot:
        app.current = Item("abcdefghijk", "playing")
        app.upcoming = [Item("01234567890", "queued")]
        await pilot.click("#stop")
        assert app.current is None and app.upcoming == []
        player.command.assert_called_with("stop")


async def test_stop_cancels_pending_extraction():
    player = fake_player()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def extract(item):
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    player.play = extract
    app = MusicApp(Mock(headers=None), DEFAULT_CONFIG, player=player)
    async with app.run_test(size=(80, 24)) as pilot:
        app.begin(Item("abcdefghijk", "pending"))
        await started.wait()
        await pilot.click("#stop")
        assert cancelled.is_set()
        assert app.current is None
