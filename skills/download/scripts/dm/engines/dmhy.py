"""engines/dmhy.py — 动漫花园 (share.dmhy.org, 中文动漫) 搜索引擎.

中文动漫/字幕组老牌; 列表部分条目含磁力, 缺失时回退详情页取磁力。
直连可达但偶有抖动, 失败会优雅降级。
参考: diazchika/dmhy 与 ZH1637/dmhy 插件思路 (改走 share.dmhy.org 镜像)。
"""

from __future__ import annotations

import re
from urllib.parse import quote

from ..models import SearchResult, parse_int, parse_size
from .base import BaseEngine, EngineError, register

_BASE = "https://share.dmhy.org"
_SEARCH_URL = _BASE + "/topics/list?keyword={kw}&sort_id=2"
_MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]+")
_ROW_RE = re.compile(r"<tr class=\"p-title\">(.*?)</tr>", re.S)
_DETAIL_LINK_RE = re.compile(r'href="(/topics/view/[0-9_]+)"')


def _cells(row: str) -> list[str]:
    return [c.strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]


@register
class DMHYEngine(BaseEngine):
    name = "dmhy"
    needs_proxy = False  # share.dmhy.org 国内直连可达 (偶抖动)

    def _search(self, query: str) -> list[SearchResult]:
        url = _SEARCH_URL.format(kw=quote(query))
        html = self._get(url)
        results: list[SearchResult] = []
        for m in _ROW_RE.finditer(html):
            row = m.group(1)
            magnet_m = _MAGNET_RE.search(row)
            detail_m = _DETAIL_LINK_RE.search(row)
            name_m = re.search(r"alt=\"([^\"]+)\"", row) or re.search(
                r"title=\"([^\"]+)\"", row
            )
            name = re.sub(r"<[^>]+>", "", (name_m.group(1) if name_m else "")).strip()
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in _cells(row)]
            # 典型列: 标题 | 大小 | 来源(发布者) ... 做种列视模板而定
            size = parse_size(cells[0]) if cells else -1
            for c in cells[1:]:
                if re.search(r"\d", c) and ":" not in c:
                    break
            # 做种数一般在含"声望/做种"的单元格, 取不到则 -1
            seeds = -1
            for c in cells:
                n = parse_int(c)
                if n > 0:
                    seeds = n
                    break
            if magnet_m:
                magnet = magnet_m.group(0)
            elif detail_m:
                # 无磁力时走详情页取磁力 (二次请求)
                try:
                    page = self._get(_BASE + detail_m.group(1))
                    fm = _MAGNET_RE.search(page)
                    magnet = fm.group(0) if fm else ""
                except EngineError:
                    magnet = ""
            else:
                magnet = ""
            if not magnet:
                continue
            results.append(
                SearchResult(
                    engine=self.name,
                    query_filtered=True,
                    name=name,
                    magnet=magnet,
                    size=size,
                    seeders=seeds,
                    leechers=-1,
                )
            )
        return results
