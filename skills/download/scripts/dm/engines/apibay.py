"""engines/apibay.py — The Pirate Bay (apibay.org 官方 JSON API) (需代理).

/ q.php 返回干净 JSON: {name, info_hash, seeders, leechers, size, ...}
由 info_hash 构造磁力。体量最大、更新快, 但磁力需要二次筛选。
"""
from __future__ import annotations

from urllib.parse import quote

from ..models import SearchResult, parse_int, parse_size
from .base import BaseEngine, EngineError, register, _parse_json

_API = "https://apibay.org/q.php?q={query}&cat=0"


@register
class ApiBayEngine(BaseEngine):
    name = "apibay"
    needs_proxy = True

    def _search(self, query: str) -> list[SearchResult]:
        data = _parse_json(self._get(_API.format(query=quote(query))), self.name)
        if not isinstance(data, list):
            raise EngineError(self.name, "返回结构异常 (非数组)")

        results: list[SearchResult] = []
        for item in data:
            btih = str(item.get("info_hash") or "").strip()
            name = str(item.get("name") or "")
            if not btih or not name:
                continue
            magnet = f"magnet:?xt=urn:btih:{btih}&dn={quote(name, safe='')}"
            results.append(
                SearchResult(
                    engine=self.name,
                    name=name,
                    magnet=magnet,
                    size=parse_size(item.get("size")),
                    seeders=parse_int(item.get("seeders")),
                    leechers=parse_int(item.get("leechers")),
                    published=str(item.get("added") or ""),
                    trusted=str(item.get("status") or "") == "vip",
                    info_url="",
                )
            )
        return results
