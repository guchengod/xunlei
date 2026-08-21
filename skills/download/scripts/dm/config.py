"""config.py — 配置加载 (TOML + 内置默认 + 环境变量覆盖).

配置来源优先级:
  1. --config 参数 / DM_CONFIG 环境变量指定的文件
  2. <技能目录>/config.toml (存在则用)
  3. 内置默认值

全部为零第三方依赖实现 (stdlib tomllib, Python>=3.11)。
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomllib

SKILL_DIR = Path(__file__).resolve().parent.parent.parent  # .../skills/xunlei-download
DEFAULT_CONFIG_PATH = SKILL_DIR / "config.toml"


@dataclass
class ProxyCfg:
    enabled: bool = False
    http: str = ""
    https: str = ""
    socks5: str = ""

    def as_dict(self) -> dict:
        proxies = {}
        if self.http:
            proxies["http"] = self.http
        if self.https:
            proxies["https"] = self.https
        elif self.http:
            proxies["https"] = self.http
        if self.socks5:
            # urllib 原生不支持 socks5, 但保留字段以便未来扩展 (或交给系统代理)
            proxies = {}
        return proxies


@dataclass
class SearchCfg:
    engines_always: list[str] = field(
        default_factory=lambda: ["snowfl", "animetosho", "tsukihime", "dmhy"]
    )
    engines_with_proxy: list[str] = field(
        default_factory=lambda: ["nyaa", "btdig", "apibay"]
    )
    max_results_per_engine: int = 60
    per_engine_timeout: int = 12
    concurrency: int = 4


@dataclass
class SelectionCfg:
    max_candidates: int = 300
    size_min_mb: int = 50
    size_max_gb: int = 80
    prefer_h265: bool = True
    chinese_markers: list[str] = field(
        default_factory=lambda: [
            "中字",
            "简中",
            "繁中",
            "简繁",
            "双语",
            "中文字幕",
            "中文",
            "国语",
            "中配",
            "国配",
            "国粤",
            "国英",
            "mandarin",
            "chs",
            "cht",
            "简",
            "繁",
        ]
    )
    bad_markers: list[str] = field(
        default_factory=lambda: [
            "sample",
            "preview",
            "trailer",
            "promo",
            "预告",
            "测试",
            "demo",
        ]
    )
    quality_keywords: list[str] = field(
        default_factory=lambda: [
            "2160p",
            "4k",
            "uhd",
            " 4k ",
            "1080p",
            "1080",
            "720p",
            "hd",
            "remux",
            "bluray",
            "blu-ray",
            "brrip",
            "bdrip",
            "web-dl",
            "web-dl",
            "webrip",
            "hdtv",
            "dvdrip",
            "cam",
            "ts",
            "tc",
            "h265",
            "x265",
            "hevc",
        ]
    )


@dataclass
class WeightsCfg:
    quality: float = 30.0
    chinese: float = 25.0
    seeders: float = 30.0
    size: float = 15.0


@dataclass
class XunleiCfg:
    host: str = "http://localhost:2345"
    auth: str = ""  # "user:pass"
    default_dir: str = ""  # 相对下载根目录 (如 "电影")


@dataclass
class QBittorrentCfg:
    host: str = "http://localhost:8080"
    username: str = "admin"
    password: str = "adminadmin"
    save_path: str = ""  # 空=客户端默认
    add_paused: bool = False


@dataclass
class DownloadersCfg:
    preferred: list[str] = field(default_factory=lambda: ["xunlei", "qbittorrent"])


@dataclass
class AppConfig:
    proxy: ProxyCfg = field(default_factory=ProxyCfg)
    search: SearchCfg = field(default_factory=SearchCfg)
    selection: SelectionCfg = field(default_factory=SelectionCfg)
    weights: WeightsCfg = field(default_factory=WeightsCfg)
    xunlei: XunleiCfg = field(default_factory=XunleiCfg)
    qbittorrent: QBittorrentCfg = field(default_factory=QBittorrentCfg)
    downloaders: DownloadersCfg = field(default_factory=DownloadersCfg)

    config_path: str = ""  # 实际生效的配置文件路径 (便于展示)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("config_path", None)
        return d


def _merge(dst: object, src: dict, section: str) -> None:
    """把 TOML section dict 合并进 dataclass 实例 (仅覆盖已定义字段)。"""
    for key, value in (src or {}).items():
        if hasattr(dst, key):
            setattr(dst, key, value)
        else:
            raise ValueError(f"未知配置项 [{section}].{key}")


def load_config(path: str | None = None) -> AppConfig:
    cfg = AppConfig()

    # 1) 显式路径或默认路径
    chosen = path or os.environ.get("DM_CONFIG") or str(DEFAULT_CONFIG_PATH)
    path_obj = Path(chosen)

    if path_obj.is_file():
        try:
            with open(path_obj, "rb") as f:
                raw = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ValueError(f"无法解析配置文件 {path_obj}: {e}") from e
        if "proxy" in raw:
            _merge(cfg.proxy, raw["proxy"], "proxy")
        if "search" in raw:
            _merge(cfg.search, raw["search"], "search")
        if "selection" in raw:
            _merge(cfg.selection, raw["selection"], "selection")
        if "weights" in raw:
            _merge(cfg.weights, raw["weights"], "weights")
        if "xunlei" in raw:
            _merge(cfg.xunlei, raw["xunlei"], "xunlei")
        if "qbittorrent" in raw:
            _merge(cfg.qbittorrent, raw["qbittorrent"], "qbittorrent")
        if "downloaders" in raw:
            _merge(cfg.downloaders, raw["downloaders"], "downloaders")
        cfg.config_path = str(path_obj)
    else:
        cfg.config_path = "(内置默认)"

    # 2) 环境变量覆盖 (命令行参数--config优先级更高, 放在CLI层处理)
    if os.environ.get("XL_HOST"):
        cfg.xunlei.host = os.environ["XL_HOST"]
    if os.environ.get("XL_AUTH"):
        cfg.xunlei.auth = os.environ["XL_AUTH"]
    if os.environ.get("QBT_HOST"):
        cfg.qbittorrent.host = os.environ["QBT_HOST"]
    if os.environ.get("QBT_USER"):
        cfg.qbittorrent.username = os.environ["QBT_USER"]
    if os.environ.get("QBT_PASS"):
        cfg.qbittorrent.password = os.environ["QBT_PASS"]

    return cfg
