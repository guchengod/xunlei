"""session.py — 统一 HTTP 会话 (代理 / 超时 / 指数退避重试)。

零第三方依赖 (urllib)。所有搜索引擎与下载器都通过它发请求,
保证: 统一 UA、统一超时、重试策略、代理设置只有一处。
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlencode


class HttpError(Exception):
    def __init__(self, url: str, status: int | None = None, message: str = ""):
        self.url = url
        self.status = status
        super().__init__(f"HTTP {status} @ {url}: {message}" if status else f"请求失败 @ {url}: {message}")


class HTTPSession:
    DEFAULT_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

    def __init__(
        self,
        proxies: dict | None = None,
        timeout: int = 12,
        retries: int = 2,
        base_delay: float = 0.6,
        user_agent: str = DEFAULT_UA,
    ):
        self._timeout = timeout
        self._retries = retries
        self._base_delay = base_delay
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies or {})
        )
        self._ua = user_agent

    # -------------------------------------------------------------- public API
    def get(self, url: str, headers: dict | None = None, timeout: int | None = None) -> str:
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                req = urllib.request.Request(url, headers=self._headers(headers))
                with self._opener.open(req, timeout=timeout or self._timeout) as resp:
                    return resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                # 4xx/5xx: 重试可能无意义, 但 5xx/429 值得退避重试
                if e.code in (429, 500, 502, 503, 504) and attempt < self._retries:
                    last_exc = e
                    self._sleep(attempt)
                    continue
                raise HttpError(url, e.code) from e
            except OSError as e:
                last_exc = e
                if attempt < self._retries:
                    self._sleep(attempt)
                    continue
                raise HttpError(url, message=str(e)) from e
        raise HttpError(url, message=str(last_exc))

    def get_bytes(self, url: str, headers: dict | None = None, timeout: int | None = None) -> bytes:
        req = urllib.request.Request(url, headers=self._headers(headers))
        with self._opener.open(req, timeout=timeout or self._timeout) as resp:
            return resp.read()

    def post_form(self, url: str, data: dict, headers: dict | None = None) -> tuple[int, str]:
        """application/x-www-form-urlencoded POST; 返回 (状态码, 响应体)。"""
        body = urlencode(data).encode()
        req = urllib.request.Request(
            url, data=body, headers=self._headers(headers, form=True), method="POST"
        )
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except OSError as e:
            raise HttpError(url, message=str(e)) from e

    def post_json(
        self, url: str, payload: dict, headers: dict | None = None
    ) -> tuple[int, str]:
        import json

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers=self._headers(headers, json=True),
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except OSError as e:
            raise HttpError(url, message=str(e)) from e

    # ---------------------------------------------------------------- internal
    def _headers(self, extra: dict | None, form: bool = False, json: bool = False) -> dict:
        h = {"User-Agent": self._ua, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
        if json:
            h["Content-Type"] = "application/json"
        elif form:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if extra:
            h.update(extra)
        return h

    def _sleep(self, attempt: int) -> None:
        """指数退避: 0.6s, 1.2s, ..."""
        time.sleep(self._base_delay * (2 ** attempt))
