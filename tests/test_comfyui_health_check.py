"""Unit tests for ComfyUI health check resilience with exponential backoff.

Tests verify requirements 17.1–17.4:
- Retry up to 3 times with exponential backoff (2s, 4s, 8s)
- Increase timeout to 15s on retry attempts
- Log warning on successful retry (retry count + total delay)
- Report failure with attempt count, total elapsed time, last error
"""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.photo_pipeline.comfyui_client import ComfyUIClient


@pytest.fixture
def client() -> ComfyUIClient:
    """Create a ComfyUIClient pointing at a fake URL."""
    return ComfyUIClient(base_url="http://fake-comfyui:8188")


class TestHealthCheckSuccess:
    """Tests for health check succeeding on first attempt."""

    @pytest.mark.asyncio
    async def test_returns_true_on_first_success(self, client: ComfyUIClient):
        """Health check returns True immediately when server responds 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_async_client

            result = await client.health_check()

        assert result is True


class TestHealthCheckRetrySuccess:
    """Tests for health check succeeding after retries (Req 17.4)."""

    @pytest.mark.asyncio
    async def test_succeeds_after_first_retry(
        self, client: ComfyUIClient, caplog
    ):
        """Health check succeeds on first retry and logs warning."""
        call_count = 0

        async def mock_get(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectTimeout("connection timed out")
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_async_client = AsyncMock()
            mock_async_client.get = mock_get
            mock_async_client.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_async_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with caplog.at_level(logging.WARNING):
                    result = await client.health_check()

        assert result is True
        # Should have slept once with 2s backoff
        mock_sleep.assert_called_once_with(2.0)
        # Should log warning about retry
        assert "retry" in caplog.text.lower()
        assert "1" in caplog.text  # retry count

    @pytest.mark.asyncio
    async def test_succeeds_after_second_retry(
        self, client: ComfyUIClient, caplog
    ):
        """Health check succeeds on second retry with correct backoff."""
        call_count = 0

        async def mock_get(url):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.ConnectTimeout("connection timed out")
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_async_client = AsyncMock()
            mock_async_client.get = mock_get
            mock_async_client.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_async_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with caplog.at_level(logging.WARNING):
                    result = await client.health_check()

        assert result is True
        # Should have slept with 2s then 4s backoff
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)
        # Log should mention 2 retries
        assert "2" in caplog.text


class TestHealthCheckRetryExhaustion:
    """Tests for health check failing after all retries (Req 17.3)."""

    @pytest.mark.asyncio
    async def test_returns_false_after_all_retries_exhausted(
        self, client: ComfyUIClient, caplog
    ):
        """Health check returns False after 1 initial + 3 retries all fail."""
        async def mock_get(url):
            raise httpx.ConnectTimeout("connection timed out")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_async_client = AsyncMock()
            mock_async_client.get = mock_get
            mock_async_client.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_async_client

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with caplog.at_level(logging.ERROR):
                    result = await client.health_check()

        assert result is False
        # Should have slept 3 times: 2s, 4s, 8s
        assert mock_sleep.call_count == 3
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)
        mock_sleep.assert_any_call(8.0)

    @pytest.mark.asyncio
    async def test_failure_log_includes_attempt_count(
        self, client: ComfyUIClient, caplog
    ):
        """Failure log includes total attempt count (4 = 1 initial + 3 retries)."""
        async def mock_get(url):
            raise httpx.ConnectTimeout("connection timed out")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_async_client = AsyncMock()
            mock_async_client.get = mock_get
            mock_async_client.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_async_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with caplog.at_level(logging.ERROR):
                    await client.health_check()

        # Should report 4 attempts (1 initial + 3 retries)
        assert "4 attempt" in caplog.text

    @pytest.mark.asyncio
    async def test_failure_log_includes_last_error(
        self, client: ComfyUIClient, caplog
    ):
        """Failure log includes the last error received."""
        async def mock_get(url):
            raise httpx.ConnectTimeout("VRAM contention timeout")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_async_client = AsyncMock()
            mock_async_client.get = mock_get
            mock_async_client.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_async_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with caplog.at_level(logging.ERROR):
                    await client.health_check()

        assert "VRAM contention timeout" in caplog.text


class TestHealthCheckBackoffTiming:
    """Tests for exponential backoff timing (Req 17.1)."""

    @pytest.mark.asyncio
    async def test_backoff_delays_are_2_4_8(self, client: ComfyUIClient):
        """Backoff delays follow 2s, 4s, 8s exponential pattern."""
        async def mock_get(url):
            raise httpx.ConnectTimeout("timeout")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_async_client = AsyncMock()
            mock_async_client.get = mock_get
            mock_async_client.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_async_client

            sleep_calls = []
            original_sleep = asyncio.sleep

            async def track_sleep(duration):
                sleep_calls.append(duration)

            with patch("asyncio.sleep", side_effect=track_sleep):
                await client.health_check()

        assert sleep_calls == [2.0, 4.0, 8.0]


class TestHealthCheckTimeout:
    """Tests for timeout configuration (Req 17.2)."""

    @pytest.mark.asyncio
    async def test_initial_attempt_uses_5s_timeout(
        self, client: ComfyUIClient
    ):
        """First attempt uses 5s timeout."""
        timeout_used = None

        def capture_timeout(timeout):
            nonlocal timeout_used
            timeout_used = timeout
            mock = AsyncMock()
            mock.get = AsyncMock(
                return_value=MagicMock(status_code=200)
            )
            mock.__aenter__ = AsyncMock(return_value=mock)
            mock.__aexit__ = AsyncMock(return_value=False)
            return mock

        with patch("httpx.AsyncClient", side_effect=capture_timeout):
            await client.health_check()

        assert timeout_used == 5.0

    @pytest.mark.asyncio
    async def test_retry_attempts_use_15s_timeout(
        self, client: ComfyUIClient
    ):
        """Retry attempts use increased 15s timeout."""
        timeouts_used = []
        call_count = 0

        def capture_timeout(timeout):
            nonlocal call_count
            call_count += 1
            timeouts_used.append(timeout)
            mock = AsyncMock()
            if call_count <= 1:
                # First attempt fails
                mock.get = AsyncMock(
                    side_effect=httpx.ConnectTimeout("timeout")
                )
            else:
                # Second attempt succeeds
                mock.get = AsyncMock(
                    return_value=MagicMock(status_code=200)
                )
            mock.__aenter__ = AsyncMock(return_value=mock)
            mock.__aexit__ = AsyncMock(return_value=False)
            return mock

        with patch("httpx.AsyncClient", side_effect=capture_timeout):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await client.health_check()

        # First call should use 5.0, second (retry) should use 15.0
        assert timeouts_used[0] == 5.0
        assert timeouts_used[1] == 15.0


class TestHealthCheckNonTimeoutErrors:
    """Tests for handling non-timeout errors (HTTP errors, etc.)."""

    @pytest.mark.asyncio
    async def test_http_500_triggers_retry(self, client: ComfyUIClient):
        """Non-200 status codes trigger retry logic."""
        call_count = 0

        async def mock_get(url):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count <= 2:
                resp.status_code = 500
            else:
                resp.status_code = 200
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_async_client = AsyncMock()
            mock_async_client.get = mock_get
            mock_async_client.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_async_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client.health_check()

        assert result is True
        assert call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_os_error_triggers_retry(self, client: ComfyUIClient):
        """OSError (e.g. connection refused) triggers retry logic."""
        call_count = 0

        async def mock_get(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Connection refused")
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_async_client = AsyncMock()
            mock_async_client.get = mock_get
            mock_async_client.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_async_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_async_client

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client.health_check()

        assert result is True
        assert call_count == 2  # 1 initial + 1 retry
