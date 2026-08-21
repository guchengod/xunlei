"""selection.py — 磁力候选挑选算法 (配置驱动加权评分).

设计目标:
  1. 确定性: 同一批结果 + 同一配置 => 相同排序 (可复现, 便于测试)。
  2. 透明性: 每个候选给出 score 及各维度分解与 reason, 供 agent 复核/覆盖。

评分维度 (均 0~1 标准化, 权重来自 config [weights]):
  - quality : 画质/压制版本 (2160p/4k/1080p/remux/web-dl...)
  - chinese : 名称是否含中文字幕标记 (中字/简中/chs...)
  - seeders : 做种数 (对数归一化, 防少数大包垄断)
  - size    : 大小是否落在合理区间 (防 sample/假资源 + 防过大)

坏标记 (sample/trailer/测试...) 触发 0.3 倍惩罚; trusted/vip 有少量加成。
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from .models import SearchResult

if TYPE_CHECKING:
    from .config import SelectionCfg, WeightsCfg

# ------------------------------------------------ 分辨率/版本档次 (高分在前)
_RES_TIERS = [
    (1.00, [r"\b2160p\b", r"\b4k\b", r"\buhd\b", r"\b2160\b"]),
    (0.88, [r"\b1080p\b", r"\b1080\b", r"\bfhd\b", r"\bfullhd\b"]),
    (0.72, [r"\b720p\b", r"\bhd\b"]),
    (0.52, [r"\b480p\b", r"\bdvdrip\b", r"\bwmv\b"]),
]
_SOURCE_BOOST = [
    (0.15, [r"remux", r"bluray", r"blu-ray", r"brrip", r"bdrip", r"uhd"]),
    (
        0.10,
        [
            r"web-dl",
            r"webrip",
            r"webdl",
            r"amzn",
            r"dsnp",
            r"netflix",
            r"hulu",
            r"dsnyp",
        ],
    ),
    (0.00, [r"hdtv", r"hdtvrip"]),
    (
        -0.45,
        [
            r"\bcam\b",
            r"\bts\b",
            r"\btelesync\b",
            r"\bscr(screen)?\b",
            r"\br6\b",
            r"\bhdsc\b",
            r"hdtc",
        ],
    ),
]
_H265 = [r"x265", r"h265", r"hevc", r"10bit"]


def _match_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def quality_score(name: str, prefer_h265: bool = True) -> float:
    base = 0.5
    for tier, pats in _RES_TIERS:
        if _match_any(name, pats):
            base = tier
            break
    boost = 0.0
    for bonus, pats in _SOURCE_BOOST:
        if _match_any(name, pats):
            boost = bonus
            break
    if prefer_h265 and _match_any(name, _H265):
        boost += 0.03
    return max(0.0, min(1.0, base + boost))


def chinese_score(name: str, markers: list[str]) -> float:
    for m in markers:
        if m.lower() in name.lower():
            return 1.0
    return 0.0


def seeders_score(seeders: int, max_seeders: int) -> float:
    if seeders < 0 and max_seeders <= 0:
        return 0.4  # 无信息 -> 中性
    if seeders < 0:
        return 0.4
    if max_seeders <= 0:
        return 0.9 if seeders > 0 else 0.4
    # 对数归一化: 1 个做种约 0.36, 100 个约 0.80, 1000 个约 0.93
    return min(1.0, math.log1p(seeders) / math.log1p(max_seeders) * 0.92 + 0.08)


def size_score(size_bytes: int, min_bytes: int, max_bytes: int) -> float:
    if size_bytes < 0:
        return 0.5
    if size_bytes < min_bytes:
        return 0.25  # 过小 -> 疑似 sample/不完整
    if size_bytes > max_bytes:
        return 0.62  # 过大 -> 略降权但保留
    # 落在区间内, 越接近中位数分越高 (简单线性)
    mid = (min_bytes + max_bytes) / 2
    dist = abs(size_bytes - mid) / max(mid - min_bytes, 1)
    return max(0.8, 1.0 - dist * 0.4)


def has_bad_marker(name: str, markers: list[str]) -> bool:
    return _match_any(name, [re.escape(m) for m in markers])


# ---------------------------------------------------------------- 相关性
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[a-zA-Z0-9]{3,}")


def relevance(query: str, name: str) -> float:
    """资源名与查询的相关性 (0~1)。

    - 查询含英文/数字词 (>=3 字符): 按词元命中率
    - 查询含中文: 共享中文 2-gram 即可视为相关 (中文名 vs 罗马音名不要求同文)
    返回 1.0 表示强相关, 0.0 表示完全不相关。
    """
    if not query:
        return 1.0
    low = name.lower()
    words = [w.lower() for w in _WORD_RE.findall(query)]
    cjk_chars = _CJK_RE.findall(query)
    cjk_grams = {a + b for a, b in zip(cjk_chars, cjk_chars[1:], strict=False)}
    if not words and not cjk_grams:
        return 1.0  # 查询无有效特征词, 不做相关性约束

    w_hits = sum(1 for w in words if w in low)
    c_hits = sum(1 for g in cjk_grams if g in low)
    wr = (w_hits / len(words)) if words else 0.0
    cr = 1.0 if (cjk_grams and c_hits) else 0.0
    if words and cjk_grams:
        return max(wr, cr)
    return wr if words else cr


# ---------------------------------------------------------------- 主入口
Scored = dict  # {result: SearchResult, score: float, reasons: dict, ...}


def score_results(
    results: list[SearchResult],
    *,
    weights: WeightsCfg,
    selection: SelectionCfg,
    limit: int | None = None,
    query: str = "",
) -> list[dict]:
    """对一批结果打分并按降序排序, 返回带分解的 dict 列表。

    query 非空时施加相关性守卫: 通用引擎 (非服务端过滤型) 返回的不相关条目
    会被大幅降权, 防止"做种多但不相关"的垃圾排到最前。
    """
    if not results:
        return []

    cands = results[: (limit or len(results))]
    # 先算每个候选的相关性 (供做种归一化只用相关候选, 避免垃圾大做种污染最大值)
    rels = [1.0 if r.query_filtered else relevance(query, r.name) for r in cands]
    relevant = [r for r, rel in zip(cands, rels, strict=False) if rel >= 0.35]
    max_seed = max((r.seeders for r in relevant), default=0)
    min_b = selection.size_min_mb * 1024 * 1024
    max_b = selection.size_max_gb * 1024 * 1024 * 1024

    scored: list[dict] = []
    for r, rel in zip(cands, rels, strict=False):
        q = quality_score(r.name, selection.prefer_h265)
        c = chinese_score(r.name, selection.chinese_markers)
        s = seeders_score(r.seeders, max_seed)
        z = size_score(r.size, min_b, max_b)
        bad = has_bad_marker(r.name, selection.bad_markers)

        # 相关性守卫: 引擎若已在服务端按关键词过滤(query_filtered=True)则信任,
        # 否则用 query 与 name 的命中判定, 不相关重罚 (rel 来自循环头)
        raw = (
            weights.quality * q
            + weights.chinese * c
            + weights.seeders * s
            + weights.size * z
        )
        total = (
            sum((weights.quality, weights.chinese, weights.seeders, weights.size))
            or 1.0
        )
        score = (raw / total) * 100.0
        if bad:
            score *= 0.35
        score *= 0.12 + 0.88 * rel  # 不相关 => 大幅降权但保留可见
        if r.trusted:
            score = min(100.0, score + 2.0)

        reasons = []
        if q >= 0.88:
            reasons.append("画质优")
        elif q < 0.6:
            reasons.append("画质一般")
        if c:
            reasons.append("含中文字幕")
        if s >= 0.9:
            reasons.append("做种充足")
        elif r.seeders < 0:
            reasons.append("做种未知")
        if rel < 0.4:
            reasons.append("疑似不相关")
        if bad:
            reasons.append("疑似sample/预告")
        if r.trusted:
            reasons.append("可信来源")

        scored.append(
            {
                "rank": 0,  # 排序后回填
                "score": round(score, 1),
                "reasons": reasons,
                "breakdown": {
                    "quality": round(q, 2),
                    "chinese": round(c, 2),
                    "seeders": round(s, 2),
                    "size": round(z, 2),
                    "relevance": round(rel, 2),
                },
                "result": r,
            }
        )

    scored.sort(key=lambda d: d["score"], reverse=True)
    for i, d in enumerate(scored):
        d["rank"] = i + 1
    return scored
