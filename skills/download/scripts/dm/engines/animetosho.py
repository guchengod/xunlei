"""engines/animetosho.py — AnimeTosho (animetosho.org) 动漫搜索引擎.

官方 JSON API (feed.animetosho.org/json), 返回字段含 magnet_uri /
seeders / leechers / total_size, 是 Nyaa 系资源的聚合 (Nyaa+Anidex+Nekobt)。
"""
from __future__ import annotations

import urllib.parse

from ..models import SearchResult, parse_int, parse_size
from .base import BaseEngine, EngineError, register, _parse_json

_JSON_URL = "https://feed.animetosho.org/json?q={query}"


@register
class AnimetoshoEngine(BaseEngine):
    name = "animetosho"
    needs_proxy = False

    def _search(self, query: str) -> list[SearchResult]:
        data = _parse_json(
            self._get(_JSON_URL.format(query=urllib.parse.quote(query))), self.name
        )
        if not isinstance(data, list):
            raise EngineError(self.name, "返回结构异常 (非数组)")

        results: list[SearchResult] = []
        for item in data:
            magnet = str(item.get("magnet_uri") or "").strip()
            if not magnet:
                continue
            results.append(
                SearchResult(
                    engine=self.name,
                    query_filtered=True,
                    name=str(item.get("title") or ""),
                    magnet=magnet,
                    size=parse_size(item.get("total_size")),
                    seeders=parse_int(item.get("seeders")),
                    leechers=parse_int(item.get("leechers")),
                    published=str(item.get("timestamp") or ""),
                    info_url=str(item.get("link") or ""),
                )
            )
        return results
