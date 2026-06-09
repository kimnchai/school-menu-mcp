"""
PlayMCP-mode 전용 보조 — Starlette/ASGI 미들웨어 + 응답 사이즈 가드.

PLAYMCP_MODE=1로 띄울 때만 활성. 원본 Fly 배포 영향 X.

포함:
- OriginCheckMiddleware: DNS rebinding 방어 (MCP spec 2025-03-26 보안 요구).
- GlobalRateLimitMiddleware: 인증 부재 보완용 IP별 sliding-window.
- cap_response(): 24K 응답 초과 위험 시 잘라내고 안내 꼬리표.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Iterable


# PlayMCP 호스트 자체가 우리 서버를 호출. UI/Inspector·curl·헬스체크 등은 Origin
# 헤더가 비어있을 수 있어 빈 Origin은 통과시킨다 (브라우저만 Origin을 강제로 채움).
_DEFAULT_ALLOWED_ORIGINS = {
    "https://playmcp.kakao.com",
    "https://play.mcp.kakao.com",
}


def _allowed_origins() -> set[str]:
    extra = os.environ.get("PLAYMCP_ALLOWED_ORIGINS", "").strip()
    if not extra:
        return set(_DEFAULT_ALLOWED_ORIGINS)
    return set(_DEFAULT_ALLOWED_ORIGINS) | {o.strip() for o in extra.split(",") if o.strip()}


class OriginCheckMiddleware:
    """DNS rebinding 방어. 빈 Origin은 허용 (서버간 호출·헬스체크)."""

    def __init__(self, app, allowed: Iterable[str] | None = None) -> None:
        self.app = app
        self.allowed = set(allowed) if allowed is not None else _allowed_origins()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            origin = ""
            for k, v in scope.get("headers", ()):
                if k == b"origin":
                    origin = v.decode("latin-1")
                    break
            if origin and origin not in self.allowed:
                await send({
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b"forbidden origin",
                })
                return
        await self.app(scope, receive, send)


def _client_ip(scope) -> str:
    # Fly proxy 뒤 — X-Forwarded-For 첫 번째 IP 우선.
    for k, v in scope.get("headers", ()):
        if k == b"fly-client-ip":
            return v.decode("latin-1")
        if k == b"x-forwarded-for":
            return v.decode("latin-1").split(",", 1)[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


class GlobalRateLimitMiddleware:
    """IP별 sliding window. PlayMCP는 인증을 빼는 대신 이걸로 abuse 차단."""

    def __init__(self, app, max_per_minute: int | None = None) -> None:
        self.app = app
        self.max = max_per_minute or int(os.environ.get("PLAYMCP_RATE_LIMIT", "60"))
        self.window = 60
        self._buckets: dict[str, deque[float]] = {}

    def _allow(self, ip: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        bucket = self._buckets.setdefault(ip, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max:
            return False
        bucket.append(now)
        # 메모리 누수 방지 — 오래된 IP 버킷 청소
        if len(self._buckets) > 4096:
            self._gc(cutoff)
        return True

    def _gc(self, cutoff: float) -> None:
        dead = [ip for ip, b in self._buckets.items() if not b or b[-1] < cutoff]
        for ip in dead:
            self._buckets.pop(ip, None)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            ip = _client_ip(scope)
            if not self._allow(ip):
                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"),
                        (b"retry-after", b"60"),
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": b"rate limit exceeded",
                })
                return
        await self.app(scope, receive, send)


# PlayMCP 정책: Tool response 24K 초과 시 에러. 안전 마진 20K로 자른다.
_RESPONSE_MAX_BYTES = 20_000
_TRUNCATION_TAIL = (
    "\n\n_…응답이 너무 길어 잘렸습니다. 필터(공항·노선·날짜·항공사)를 좁혀 다시 요청해 주세요._"
)


def cap_response(text: str, max_bytes: int = _RESPONSE_MAX_BYTES) -> str:
    """UTF-8 기준 max_bytes 초과 시 안전하게 자르고 안내 꼬리표 부착."""
    if text is None:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    tail = _TRUNCATION_TAIL.encode("utf-8")
    keep = max_bytes - len(tail)
    if keep <= 0:
        return _TRUNCATION_TAIL.lstrip()
    cut = encoded[:keep]
    # UTF-8 멀티바이트 중간 자르기 회피 — 마지막 newline 또는 안전 경계로 후퇴.
    nl = cut.rfind(b"\n")
    if nl > keep - 512:  # 충분히 가까우면 newline에서 자름
        cut = cut[:nl]
    else:
        # 멀티바이트 boundary 보정
        while cut and (cut[-1] & 0xC0) == 0x80:
            cut = cut[:-1]
    return cut.decode("utf-8", errors="ignore") + _TRUNCATION_TAIL
