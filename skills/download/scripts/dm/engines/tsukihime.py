"""engines/tsukihime.py — TsukiHime (tsukihime.org) 动漫聚合搜索引擎.

官方 JSON API (api.tsukihime.org), 返回 btih, 由 btih 构造 magnet。
聚合 Nyaa / Nekobt / 其自身索引。
"""
from __future__ import annotations

from urllib.parse import quote
from ..models import SearchResult, parse_int, parse_size
from .base import BaseEngine, EngineError, register, _parse_json

_API = "https://api.tsukihime.org/v1/search/torrents?q={query}"


@register
class TsukihimeEngine(BaseEngine):
    name = "tsukihime"
    needs_proxy = False

    def _search(self, query: str) -> list[SearchResult]:
        payload = _parse_json(
            self._get(_API.format(query=quote(query))), self.name
        )
        if not isinstance(payload, dict):
            raise EngineError(self.name, "返回结构异常 (非对象)")
        items = payload.get("results") or []
        if not isinstance(items, list):
            raise EngineError(self.name, "results 结构异常")

        results: list[SearchResult] = []
        for item in items:
            btih = str(item.get("btih") or "").strip()
            name = str(item.get("name") or "")
            if not btih:
                continue
            magnet = (
                f"magnet:?xt=urn:btih:{btih}&dn={quote(name, safe='')}"
                + "&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce"
            )
            results.append(
                SearchResult(
                    engine=self.name,
                    query_filtered=True,
                    name=name,
                    magnet=magnet,
                    size=parse_size(item.get("totalsize")),
                    seeders=-1,  # 聚合接口不提供做种数
                    leechers=-1,
                    published=str(item.get("added_date") or ""),
                    info_url=f"https://api.tsukihime.org/v1/torrents/{item.get('id')}",
                )
            )
        return results
