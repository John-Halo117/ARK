"""Tests for emitters.jellyfin_emitter module."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from ark.subjects import EVENT_MEDIA_PLAYBACK, METRICS_MEDIA_DURATION
from emitters.jellyfin_emitter import JellyfinEmitter


class TestJellyfinEmitter:
    def setup_method(self):
        self.emitter = JellyfinEmitter()
        self.emitter.nc = MagicMock()
        self.emitter.js = AsyncMock()

    # ---- init ----

    def test_service_name(self):
        assert self.emitter.service_name == "jellyfin"

    def test_capabilities(self):
        assert "media.playback" in self.emitter.capabilities
        assert "media.library" in self.emitter.capabilities
        assert "media.search" in self.emitter.capabilities

    # ---- handle_capability dispatch ----

    @pytest.mark.asyncio
    async def test_handle_capability_unknown(self):
        result = await self.emitter.handle_capability("bogus", {})
        assert "error" in result

    # ---- emit_playback_start ----

    @pytest.mark.asyncio
    async def test_emit_playback_start(self):
        item = {"Name": "Movie", "Type": "Movie", "RunTimeTicks": 72000000000}
        await self.emitter.emit_playback_start("s1", "TV", "Movie", "Movie", item)

        calls = self.emitter.js.publish.call_args_list
        topics = [c[0][0] for c in calls]
        assert EVENT_MEDIA_PLAYBACK in topics
        assert METRICS_MEDIA_DURATION in topics
        assert self.emitter.event_count == 1

    @pytest.mark.asyncio
    async def test_emit_playback_start_no_duration(self):
        item = {"Name": "Track", "Type": "Audio"}
        await self.emitter.emit_playback_start("s1", "Phone", "Track", "Audio", item)
        # Only playback event, no duration metric
        calls = self.emitter.js.publish.call_args_list
        topics = [c[0][0] for c in calls]
        assert topics.count(EVENT_MEDIA_PLAYBACK) == 1
        assert METRICS_MEDIA_DURATION not in topics

    # ---- emit_playback_change ----

    @pytest.mark.asyncio
    async def test_emit_playback_change(self):
        await self.emitter.emit_playback_change("s1", "TV", "Episode 2", "Episode", {})
        self.emitter.js.publish.assert_called_once()
        assert self.emitter.event_count == 1

    # ---- emit_playback_stop ----

    @pytest.mark.asyncio
    async def test_emit_playback_stop(self):
        await self.emitter.emit_playback_stop("s1", "TV")
        self.emitter.js.publish.assert_called_once()
        assert self.emitter.event_count == 1

    # ---- get_playback_status ----

    @pytest.mark.asyncio
    async def test_get_playback_status_empty(self):
        result = await self.emitter.get_playback_status({})
        assert result["active_sessions"] == 0
        assert result["sessions"] == []

    @pytest.mark.asyncio
    async def test_get_playback_status_with_session(self):
        self.emitter.active_sessions["s1"] = {"title": "Movie"}
        result = await self.emitter.get_playback_status({})
        assert result["active_sessions"] == 1

    # ---- poll_sessions ----

    @pytest.mark.asyncio
    async def test_poll_sessions_no_session(self):
        self.emitter.session = None
        result = await self.emitter.poll_sessions()
        assert result == []

    @pytest.mark.asyncio
    async def test_poll_sessions_no_token(self):
        self.emitter.session = MagicMock()
        self.emitter.jellyfin_token = ""
        result = await self.emitter.poll_sessions()
        assert result == []

    # ---- get_library / search_media / get_library_items without session ----

    @pytest.mark.asyncio
    async def test_get_library_no_session(self):
        self.emitter.session = None
        result = await self.emitter.get_library({})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_search_media_no_session(self):
        self.emitter.session = None
        result = await self.emitter.search_media({"query": "test"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_library_items_no_session(self):
        self.emitter.session = None
        result = await self.emitter.get_library_items({})
        assert "error" in result
