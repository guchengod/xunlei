"""engines/base.py — 搜索引擎基类(模板方法) 与 注册表(工厂)。

每个引擎只需实现 `_search(query) -> list[SearchResult]`, 其余
(会话/代理/超时/错误隔离/统一包装) 都由基类完成。
"""
from __future__ import annotations

import abc
import json

from ..models import SearchResult
from ..session import HTTPSession, HttpError


class EngineError(Exception):
    """引擎级错误 (网络/解析失败)。调用方应捕获并优雅降级。"""

    def __init__(self, engine: str, message: str):
        self.engine = engine
        super().__init__(f"[{engine}] {message}")


class BaseEngine(abc.ABC):
    """搜索引擎模板方法。needs_proxy=True 的引擎仅在代理启用时被构建。"""

    name: str = ""
    needs_proxy: bool = False

    def __init__(self, session: HTTPSession):
        self._s = session

    # ------------------------------------------------------------ 子类实现点
    @abc.abstractmethod
    def _search(self, query: str) -> list[SearchResult]:
        ...

    # ------------------------------------------------------------ 模板方法(固定)
    def search(self, query: str) -> list[SearchResult]:
        """子类 _search 的统一入口; 负责错误隔离与字段兜底。

        任何异常都被包装为 EngineError, 保证单个引擎故障不影响整体搜索。
        """
        try:
            raw = self._search(query)
        except EngineError:
            raise
        except Exception as e:  # noqa: BLE001 —— 引擎内部细节错误统一兜底
            raise EngineError(self.name, f"内部错误: {e}") from e
        out: list[SearchResult] = []
        for r in raw:
            if not r.magnet and not r.info_url:
                continue  # 既无磁力也无详情页, 无法下载
            if not r.engine:
                r.engine = self.name
            out.append(r)
        return out

    # ------------------------------------------------------------------ 工具
    def _get(self, url: str) -> str:
        try:
            return self._s.get(url)
        except HttpError as e:
            raise EngineError(self.name, str(e)) from e


def _parse_json(text: str, engine: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise EngineError(engine, "响应不是合法 JSON")  # noqa: B904


# ---------------------------------------------------------------- 注册表(工厂)
_REGISTRY: dict[str, type[BaseEngine]] = {}


def register(cls: type[BaseEngine]) -> type[BaseEngine]:
    _REGISTRY[cls.name] = cls
    return cls


def engine_names() -> list[str]:
    return sorted(_REGISTRY)


def build_engines(config, session: HTTPSession) -> list[BaseEngine]:
    """按配置构建引擎列表: 代理启用时 = always + with_proxy, 否则仅 always。"""
    from ..config import AppConfig

    cfg: AppConfig = config
    enabled: list[str] = list(cfg.search.engines_always)
    if cfg.proxy.enabled:
        enabled += list(cfg.search.engines_with_proxy)

    engines: list[BaseEngine] = []
    for name in enabled:
        cls = _REGISTRY.get(name)
        if cls is None:
            continue
        if cls.needs_proxy and not cfg.proxy.enabled:
            continue
        engines.append(cls(session))
    return engines
