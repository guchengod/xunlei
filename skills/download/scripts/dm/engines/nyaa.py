"""engines/nyaa.py — Nyaa (nyaa.si) 动漫搜索引擎 (需代理).

服务端渲染 HTML 表格; 列表即含磁力/大小/做种/下载次数。
参考: MadeOfMagicAndWires/qBit-plugins 的 nyaasi 插件思路。
"""
from __future__ import annotations

import re
from urllib.parse import quote

from ..models import SearchResult, parse_int, parse_size
from .base import BaseEngine, register

_BASE = "https://nyaa.si/"
_ROW_RE = re.compile(r"<tr class=\"default\">(.*?)</tr>", re.S)
_NAME_RE = re.compile(r'<a[^>]*title="([^"]+)"', re.S)
_MAGNET_RE = re.compile(r'href="(magnet:\?xt=urn:btih:[^"]+)"')
_SIZE_RE = re.compile(r"([\d.]+\s*(?:KiB|KB|MiB|MB|GiB|GB|TiB|TB))")
_TD_RE = re.compile(r'<td[^>]*class="text-center"[^>]*>(.*?)</td>', re.S)


@register
class NyaaEngine(BaseEngine):
    name = "nyaa"
    needs_proxy = True

    def _search(self, query: str) -> list[SearchResult]:
        url = f"{_BASE}?f=0&c=0_0&q={quote(query)}"
        html = self._get(url)
        results: list[SearchResult] = []
        for m in _ROW_RE.finditer(html):
            row = m.group(1)
            magnet_m = _MAGNET_RE.search(row)
            if not magnet_m:
                continue
            name_m = _NAME_RE.search(row)
            size_m = _SIZE_RE.search(row)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in _TD_RE.findall(row)]
            # 行内 text-center 单元格顺序: [link, size, date, seeders, leechers, completed]
            seeders = parse_int(cells[3]) if len(cells) > 3 else -1
            leechers = parse_int(cells[4]) if len(cells) > 4 else -1
            results.append(
                SearchResult(
                    engine=self.name,
                    query_filtered=True,
                    name=name_m.group(1).strip() if name_m else "",
                    magnet=magnet_m.group(1),
                    size=parse_size(size_m.group(1)) if size_m else -1,
                    seeders=seeders,
                    leechers=leechers,
                )
            )
        return results
