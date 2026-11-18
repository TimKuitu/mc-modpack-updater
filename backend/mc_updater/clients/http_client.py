from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from mc_updater.core.config import detect_windows_system_proxy
from mc_updater.core.models import AppSettings


USER_AGENT = "MCModpackUpdater/1.0.0 (desktop-client)"


class TokenBucketLimiter:
    """异步令牌桶限流器，防止触发 Modrinth 300 req/min 限制。"""

    def __init__(self, rate_per_minute: int = 240) -> None:
        self.capacity = float(max(10, rate_per_minute // 4))
        self.tokens = self.capacity
        self.rate_per_sec = rate_per_minute / 60.0
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_sec)
            self.last_refill = now
            if self.tokens < 1.0:
                wait_sec = (1.0 - self.tokens) / self.rate_per_sec
                await asyncio.sleep(wait_sec)
                self.tokens = 0.0
                self.last_refill = time.monotonic()
            else:
                self.tokens -= 1.0


def build_proxy_url(settings: AppSettings) -> str | None:
    if settings.proxy_mode == "direct":
        return None
    if settings.proxy_mode == "custom":
        url = settings.custom_proxy_url.strip()
        return url or None
    return detect_windows_system_proxy()


class RateLimitedHttpClient:
    """带限流、UA 注入、代理支持与 429 指数退避重试的异步 HTTP 客户端。"""

    def __init__(
        self,
        settings: AppSettings | None = None,
        rate_per_minute: int = 240,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or AppSettings()
        self.limiter = TokenBucketLimiter(rate_per_minute=rate_per_minute)
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            proxy = None if self._transport is not None else build_proxy_url(self.settings)
            kwargs: dict[str, Any] = {
                "headers": {"User-Agent": USER_AGENT},
                "timeout": httpx.Timeout(self.timeout, connect=15.0),
                "follow_redirects": True,
                "trust_env": self.settings.proxy_mode == "system",
            }
            if proxy:
                kwargs["proxy"] = proxy
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    def update_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        # 下次请求时重建客户端
        if self._client and not self._client.is_closed:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._client.aclose())
            except RuntimeError:
                pass
            self._client = None

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        max_retries: int = 4,
        **kwargs: Any,
    ) -> httpx.Response:
        client = await self._ensure_client()
        backoff = 1.0
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            await self.limiter.acquire()
            try:
                resp = await client.request(method, url, **kwargs)
                if resp.status_code == 429 or (500 <= resp.status_code < 600):
                    retry_after = resp.headers.get("Retry-After")
                    wait_sec = float(retry_after) if (retry_after and retry_after.isdigit()) else backoff
                    wait_sec = min(max(wait_sec, 0.5), 30.0)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait_sec)
                        backoff *= 2
                        continue
                return resp
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise

        if last_exc:
            raise last_exc
        raise RuntimeError("HTTP request failed unexpectedly")

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = await self.request("GET", url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def post_json(self, url: str, **kwargs: Any) -> Any:
        resp = await self.request("POST", url, **kwargs)
        resp.raise_for_status()
        return resp.json()
