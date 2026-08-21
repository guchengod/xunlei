"""downloaders/xunlei.py — 迅雷远程下载 (xlp) 策略.

复用 xunlei.py 的 API 契约: POST /api/v1/download, GET /api/v1/login。
把引擎返回的各类拒绝原因 (未登录 / 设备空间未激活 / 每日次数 / 连接失败)
分类映射为 DownloaderError.reason, 供责任链决定是否继续回退 (需求案例 3/4)。
"""

from __future__ import annotations

import base64
import json

from ..models import DownloadReceipt
from ..session import HttpError
from .base import Downloader, DownloaderError, register

_NOT_AUTH = ("refresh token", "not logged", "login", "未登录")
_DEVICE = ("device_space_not_active", "space_not_active", "设备空间")
_QUOTA = (
    "daily download",
    "次数已达",
    "免费下载",
    "limit",
    "quota",
    "downloaded times",
)


def _map_reason(obj, msg: str) -> str:
    if any(k in msg for k in _NOT_AUTH):
        return "not_authenticated"
    if any(k in msg for k in _DEVICE):
        return "device_not_active"
    if any(k in msg for k in _QUOTA):
        return "quota"
    return "rejected"


@register
class XunleiDownloader(Downloader):
    name = "xunlei"

    def __init__(self, config, session):
        self._host = (config.xunlei.host or "http://localhost:2345").rstrip("/")
        self._auth = config.xunlei.auth
        self._default_dir = config.xunlei.default_dir
        self._s = session

    # --------------------------------------------------------------- 内部请求
    def _headers(self, json_body: bool = False) -> dict:
        h = {"Content-Type": "application/json" if json_body else "text/plain"}
        if self._auth:
            h["Authorization"] = (
                "Basic " + base64.b64encode(self._auth.encode()).decode()
            )
        return h

    def _api(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self._host}/api/v1{path}"
        try:
            if method == "POST":
                code, text = self._s.post_json(url, body or {}, self._headers(True))
            else:
                code = 200
                text = self._s.get(url, headers=self._headers())
        except HttpError as e:
            # 连接层失败 (拒连/超时/DNS) -> 可恢复, 供责任链回退
            raise DownloaderError(
                self.name, f"无法连接 {self._host}: {e}", reason="unreachable"
            ) from e
        try:
            obj = json.loads(text) if text else {}
        except json.JSONDecodeError:
            obj = {"raw": text[:200]}
        if code >= 400:
            msg = str(
                obj.get("message") or obj.get("error") or obj.get("msg") or text
            ).lower()
            reason = _map_reason(obj, msg)
            raise DownloaderError(
                self.name,
                f"HTTP {code}: {json.dumps(obj, ensure_ascii=False)}",
                reason=reason,
            )
        return obj

    # --------------------------------------------------------------- 协议接口
    def check(self) -> str:
        obj = self._api("GET", "/login")
        logged = bool(
            obj.get("logged_in")
            or obj.get("ok")
            or (isinstance(obj.get("data"), dict) and obj["data"].get("logged_in"))
        )
        return f"xunlei 可达 @ {self._host} (登录态: {logged})"

    def add(
        self,
        url: str,
        name: str = "",
        dir_: str = "",
        path: str = "",
    ) -> DownloadReceipt:
        body: dict = {"url": url}
        if name:
            body["name"] = name

        # 目标目录校验: 不在迅雷索引树中的目录直接回退到下载根目录 (避免 422 整单被拒)
        target_dir, dir_note = self._resolve_dir(dir_ or self._default_dir)
        if target_dir and not path:
            body["dir"] = target_dir
        if path:
            body["path"] = path

        obj = self._api("POST", "/download", body)

        if dir_note:
            note = dir_note
        else:
            note = ""

        # 引擎可能返回 200 但带 error 字段 (部分实现如此)
        if isinstance(obj, dict) and obj.get("error"):
            msg = str(obj["error"]).lower()
            raise DownloaderError(
                self.name,
                json.dumps(obj, ensure_ascii=False),
                reason=_map_reason(obj, msg),
            )

        # 兼容不同返回形态: {id}, {task_id}, {data:{id}}, [...]
        task_id = ""
        if isinstance(obj, dict):
            data = obj.get("data")
            task = obj.get("task")
            task_id = str(
                obj.get("id")
                or obj.get("task_id")
                or obj.get("taskId")
                or (isinstance(task, dict) and task.get("id"))
                or (isinstance(data, dict) and data.get("id"))
                or ""
            )
        elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
            task_id = str(obj[0].get("id", ""))

        return DownloadReceipt(
            downloader=self.name,
            url=url,
            task_id=task_id,
            status="submitted",
            name=name,
            dir_=target_dir or "",
            message=(note + " " if note else "") + json.dumps(obj, ensure_ascii=False),
        )

    # ---------------------------------------------------------------- 目录校验
    def _dirs_tree(self) -> list[str]:
        """拉取迅雷可下载目录树, 返回所有绝对路径 (可能为空; 失败返回空)。"""
        try:
            obj = self._api("GET", "/dirs")
        except DownloaderError:
            return []
        paths: list[str] = []
        roots = obj.get("roots") or []

        def walk(nodes) -> None:
            for n in nodes or []:
                if not isinstance(n, dict):
                    continue
                p = n.get("path") or ""
                if p:
                    paths.append(p.rstrip("/"))
                walk(n.get("dirs"))

        walk(roots)
        # 兜底: 有些实现 dirs 直接就是列表
        if not paths and isinstance(roots, list):
            walk(roots)
        return paths

    def _resolve_dir(self, target: str) -> tuple[str, str]:
        """校验目标目录; 返回 (应使用的 dir 值, 说明)。

        - 目标为空 -> 不指定 (下载根目录)
        - 目标在迅雷索引树中 -> 原样使用
        - 目标不存在 -> 回退根目录并给出提示 (附带可用的顶层目录)
        """
        if not target:
            return "", ""
        tree = self._dirs_tree()
        if not tree:
            return target, ""  # 拉取目录失败时不臆断, 走原样(让引擎给出真实报错)

        # 推导根前缀 (最短路径通常是 /downloads 或 /downloads/)
        base = min(tree, key=len)
        base = base if base.endswith("/") else base + "/"
        t = target.strip()
        t_abs = t if t.startswith("/") else base + t
        if t in tree or t_abs.rstrip("/") in tree:
            return target, ""
        # 宽松: 名称完全匹配叶子目录
        for p in tree:
            if p.rstrip("/").split("/")[-1] == t.split("/")[-1]:
                return p.split("/")[
                    -1
                ], f"目录 {target!r} 未完全匹配, 已改用已索引的 {p!r}"
        # 提示语只列顶层目录 (根下第一层, 如 tv/video/云盘缓存文件), 避免刷屏
        tops = sorted(
            {
                [seg for seg in p.rstrip("/").split("/") if seg][-1]
                for p in tree
                if len([seg for seg in p.rstrip("/").split("/") if seg]) == 2
            }
        )
        hint = ", ".join(tops) if tops else "根目录"
        return (
            "",
            f"目录 {target!r} 不在迅雷索引中, 已回退到下载根目录 (当前可写顶层: {hint})",
        )
