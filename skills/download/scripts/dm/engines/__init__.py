"""engines/__init__.py — 引擎包: 导入所有引擎以完成注册。

注意: 各引擎模块通过 ``@register`` 装饰器在 import 时完成注册,
因此这里必须显式 import 以确保全量注册。
"""
from . import snowfl, animetosho, tsukihime, nyaa, btdig, apibay, dmhy  # noqa: F401
from .base import (  # noqa: F401
    BaseEngine,
    EngineError,
    build_engines,
    engine_names,
    register,
)
