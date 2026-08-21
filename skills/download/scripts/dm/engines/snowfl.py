"""engines/snowfl.py — Snowfl (snowfl.com) 通用聚合搜索引擎.

JSON API, 分三步: 取首页 -> 从 JS 提取 api_key -> 检索 JSON。
聚合 limetorrents / tpb / 1337x 等公开站磁力, 通用覆盖最好。
"""
from __future__ import annotations

import re
from urllib.parse import quote

from ..models import SearchResult, parse_int, parse_size
from .base import BaseEngine, EngineError, register, _parse_json

_BASE = "https://snowfl.com/"
_RE_JS = re.compile(r'((?:b\.min\.js).*?)(?=")')
_RE_KEY = re.compile(r'findNextItem.*?"(.*?)"')
_SORT = {
    "seed": "/DH5kKsJw/0/SEED/NONE/",
    "size": "/DH5kKsJw/0/SIZE/NONE/",
    "date": "/DH5kKsJw/0/DATE/NONE/",
    "none": "/DH5kKsJw/0/NONE/NONE/",
}


@register
class SnowflEngine(BaseEngine):
    name = "snowfl"
    needs_proxy = False

    def _api_key(self) -> str:
        home = self._get(_BASE)
        m = _RE_JS.search(home)
        if not m:
            raise EngineError(self.name, "首页未找到 JS 引用")
        js = self._get(_BASE + m.group(0))
        k = _RE_KEY.search(js)
        if not k:
            raise EngineError(self.name, "JS 中未找到 API key")
        return k.group(1)

    def _search(self, query: str) -> list[SearchResult]:
        key = self._api_key()
        url = f"{_BASE}{key}/{quote(query, safe='')}/{_SORT['seed']}0"
        data = _parse_json(self._get(url), self.name)
        if not isinstance(data, list):
            raise EngineError(self.name, "返回结构异常 (非数组)")

        results: list[SearchResult] = []
        for item in data:
            magnet = str(item.get("magnet") or "").strip()
            if not magnet:
                continue  # snowfl 聚合项无磁力时需二次解析, 此处先跳过
            results.append(
                SearchResult(
                    engine=self.name,
                    name=str(item.get("name") or ""),
                    magnet=magnet,
                    size=parse_size(item.get("size")),
                    seeders=parse_int(item.get("seeder")),
                    leechers=parse_int(item.get("leecher")),
                    site=str(item.get("site") or ""),
                    published=str(item.get("age") or ""),
                    trusted=bool(item.get("trusted")),
                )
            )
        return results
