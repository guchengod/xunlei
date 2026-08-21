"""models.py — 领域数据模型 (DTO) 与公共工具。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


# ---------------------------------------------------------------- SearchResult
@dataclass
class SearchResult:
    """一条磁力搜索结果 (统一 DTO, 屏蔽不同引擎的字段差异)。"""

    engine: str  # 来源引擎名 (snowfl / animetosho / ...)
    name: str  # 资源标题
    magnet: str  # magnet 链接 (可能为空串 -> 需要二次解析)
    size: int = -1  # 字节; -1=未知
    seeders: int = -1
    leechers: int = -1
    site: str = ""  # 聚合来源站 (snowfl 提供)
    published: str = ""  # 发布时间 (原始串, 便于 agent 判断)
    info_url: str = ""  # 详情页链接 (可选)
    trusted: bool = False  # 官方/可信标记 (如 animetosho official / tpb vip)
    query_filtered: bool = False  # 引擎已在服务端按关键词过滤 (动漫类引擎=True)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["size_human"] = human_size(self.size)
        return d


# ---------------------------------------------------------------- DownloadReceipt
@dataclass
class DownloadReceipt:
    """一次下载调度的回执。"""

    downloader: str  # 实际承担任务的下载器名
    url: str
    task_id: str = ""
    status: str = "submitted"  # submitted / already / failed
    name: str = ""
    dir_: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- size helpers
_SIZE_RE = re.compile(r"([\d.]+)\s*(KiB|KB|MiB|MB|GiB|GB|TiB|TB|B)", re.IGNORECASE)
_SIZE_UNITS = {
    "B": 1,
    "KB": 1024,
    "KIB": 1024,
    "MB": 1024**2,
    "MIB": 1024**2,
    "GB": 1024**3,
    "GIB": 1024**3,
    "TB": 1024**4,
    "TIB": 1024**4,
}


def _safe_int(v, default: int = -1) -> int:
    """安全转 int: 非法输入返回 default 而不抛异常。"""
    try:
        return int(v)
    except (ValueError, TypeError, OverflowError):
        return default


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (ValueError, TypeError, OverflowError):
        return default


def parse_size(text: str | int | None) -> int:
    """把 "755.53 MB" / "1.2 GiB" / 12345678 / None 统一转成字节数; 失败返回 -1。"""
    if text is None:
        return -1
    if isinstance(text, (int, float)):
        return _safe_int(text)
    s = str(text).strip().replace(",", "")
    m = _SIZE_RE.search(s)
    if m:
        try:
            return int(_safe_float(m.group(1)) * _SIZE_UNITS[m.group(2).upper()])
        except (KeyError, ValueError):
            return -1
    try:
        return int(s)
    except ValueError:
        return -1


def parse_int(text: str | int | None) -> int:
    if text is None:
        return -1
    if isinstance(text, int):
        return text
    m = re.search(r"\d+", str(text))
    return _safe_int(m.group(0)) if m else -1


def human_size(size: int) -> str:
    if size is None or size < 0:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    v = _safe_float(size)
    for u in units:
        if v < 1024 or u == "TB":
            return f"{v:.1f} {u}" if u != "B" else f"{_safe_int(v, 0)} B"
        v /= 1024
    return "-"
