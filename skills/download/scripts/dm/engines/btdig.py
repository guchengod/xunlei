"""engines/btdig.py — BTDigg (btdig.com) 通用 DHT 磁力搜索引擎 (需代理).

历史 DHT 索引超 10 亿, 冷门/老资源强。服务端渲染, 列表即含磁力。
参考: galaris/BTDigg-qBittorrent-plugin 解析结构。
"""
from __future__ import annotations

import re
from urllib.parse import quote

from ..models import SearchResult, parse_size
from .base import BaseEngine, register

_BASE = "https://btdig.com/"
_BLOCK_RE = re.compile(r'<div class="one_result".*?(?=<div class="one_result"|$)', re.S)
_MAGNET_RE = re.compile(r'href="(magnet:\?xt=urn:btih:[^"]+)"')
_NAME_RE = re.compile(
    r'<div class="torrent_name".*?<a.*?>(.*?)</a>', re.S
)
_SIZE_RE = re.compile(r'<span class="torrent_size"[^>]*>(.*?)</span>', re.S)


@register
class BTDiggEngine(BaseEngine):
    name = "btdig"
    needs_proxy = True

    def _search(self, query: str) -> list[SearchResult]:
        # 旧式 /<kw>.html 与服务端渲染的 /search?q= 两条都尝试; 先 /search?q=
        url = f"{_BASE}search?q={quote(query)}&order=0"
        html = self._get(url)
        blocks = list(_BLOCK_RE.finditer(html))
        if not blocks:
            # 兜底: 尝试 /<kw>.html 变体 (同样是服务端渲染)
            html = self._get(f"{_BASE}{quote(query)}.html")
            blocks = list(_BLOCK_RE.finditer(html))

        results: list[SearchResult] = []
        for b in blocks:
            block = b.group(0)
            magnet_m = _MAGNET_RE.search(block)
            name_m = _NAME_RE.search(block)
            size_m = _SIZE_RE.search(block)
            if not (magnet_m and name_m):
                continue
            name = re.sub(r"<[^>]+>", "", name_m.group(1)).strip()
            results.append(
                SearchResult(
                    engine=self.name,
                    name=name,
                    magnet=magnet_m.group(1),
                    size=parse_size(size_m.group(1)) if size_m else -1,
                    seeders=-1,
                    leechers=-1,
                )
            )
        return results
