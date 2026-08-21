"""downloaders/base.py — 下载器协议 + 错误模型 + 责任链回退.

设计模式:
  - Strategy: XunleiDownloader / QBittorrentDownloader 实现同一 Downloader 协议,
    通过注册表按名字实例化。
  - Chain of Responsibility: DownloaderChain 按 [preferred] 顺序依次尝试,
    前一个失败(recoverable)自动落到下一个 (对应需求案例 3/4)。
"""
from __future__ import annotations

import abc

from ..models import DownloadReceipt


class DownloaderError(Exception):
    """下载器错误。recoverable=True 表示后端可运维恢复 (换下载器继续)。"""

    def __init__(self, downloader: str, message: str, reason: str = "unknown"):
        self.downloader = downloader
        self.reason = reason          # unreachable / not_authenticated / rejected / ...
        super().__init__(f"[{downloader}] {message} (reason={reason})")


class Downloader(abc.ABC):
    name: str = ""

    def __init__(self, config, session):
        """策略实例构造入口; 子类各自接管需要的字段。

        基类这里仅占位, 让注册表 `cls(config, session)` 调用类型安全。
        """
        self._config = config
        self._session = session

    @abc.abstractmethod
    def add(
        self,
        url: str,
        name: str = "",
        dir_: str = "",
        path: str = "",
    ) -> DownloadReceipt:
        """提交一个链接 (magnet / http / bt: ...)。失败抛 DownloaderError。"""
        ...

    def check(self) -> str:
        """探测下载器可用性, 返回人类可读描述; 异常抛 DownloaderError。"""
        return f"{self.name} 可用"


# ---------------------------------------------------------------- 注册表(工厂)
_REGISTRY: dict[str, type[Downloader]] = {}


def register(cls: type[Downloader]) -> type[Downloader]:
    _REGISTRY[cls.name] = cls
    return cls


def downloader_names() -> list[str]:
    return sorted(_REGISTRY)


def build_downloaders(config, session) -> list[Downloader]:
    """按 config.downloaders.preferred 顺序实例化; 未知名字自动跳过。"""
    out: list[Downloader] = []
    for name in config.downloaders.preferred:
        cls = _REGISTRY.get(name)
        if cls:
            out.append(cls(config, session))
    return out


# ---------------------------------------------------------------- 责任链
class AllDownloadersFailed(Exception):
    def __init__(self, errors: list[DownloaderError]):
        self.errors = errors
        super().__init__(
            "所有下载器均失败:\n" + "\n".join(f"  - {e}" for e in errors)
        )


class DownloaderChain:
    """依次尝试每个下载器; 前一个失败则进入下一个。"""

    def __init__(self, downloaders: list[Downloader]):
        self._downloaders = downloaders

    def download(
        self,
        url: str,
        name: str = "",
        dir_: str = "",
        path: str = "",
    ) -> tuple[DownloadReceipt, list[DownloaderError]]:
        errors: list[DownloaderError] = []
        for d in self._downloaders:
            try:
                r = d.add(url, name=name, dir_=dir_, path=path)
                return r, errors
            except DownloaderError as e:
                errors.append(e)
        raise AllDownloadersFailed(errors)
