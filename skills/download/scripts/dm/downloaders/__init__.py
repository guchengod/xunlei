"""downloaders/__init__.py — 下载器包注册。"""
from . import xunlei, qbittorrent  # noqa: F401
from .base import (  # noqa: F401
    AllDownloadersFailed,
    Downloader,
    DownloaderChain,
    DownloaderError,
    build_downloaders,
    downloader_names,
    register,
)
