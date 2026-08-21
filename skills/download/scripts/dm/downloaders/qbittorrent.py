"""downloaders/qbittorrent.py — qBittorrent WebAPI 策略.

通过 qBittorrent WebAPI (/api/v2) 添加磁力/BT 任务, 作为迅雷之后
的第二下载器回退选项 (需求案例 4)。依赖 qBittorrent 已运行且开了
WebUI (默认 8080)。
"""

from __future__ import annotations

from ..models import DownloadReceipt
from ..session import HttpError
from .base import Downloader, DownloaderError, register


@register
class QBittorrentDownloader(Downloader):
    name = "qbittorrent"

    def __init__(self, config, session):
        self._host = (config.qbittorrent.host or "http://localhost:8080").rstrip("/")
        self._user = config.qbittorrent.username
        self._pass = config.qbittorrent.password
        self._save_path = config.qbittorrent.save_path
        self._paused = config.qbittorrent.add_paused
        self._s = session
        self._cookie = None

    # ---------------------------------------------------------------- 登录
    def _login(self) -> None:
        try:
            code, text = self._s.post_form(
                f"{self._host}/api/v2/auth/login",
                {"username": self._user, "password": self._pass},
                headers={"Referer": self._host + "/"},
            )
        except HttpError as e:
            raise DownloaderError(
                self.name, f"无法连接 {self._host}", reason="unreachable"
            ) from e
        # 200 "Ok." 或 204 (免登录白名单) 均视为认证通过
        if text.strip() == "Ok." or code == 204:
            self._cookie = "SID=bypass"
            return
        if code != 200 or text.strip() != "Ok.":
            raise DownloaderError(
                self.name,
                f"登录失败 (HTTP {code}): {text[:80]}",
                reason="not_authenticated",
            )

    def _ensure_login(self) -> None:
        if self._cookie is None:
            self._login()

    # ---------------------------------------------------------------- 协议接口
    def check(self) -> str:
        try:
            code, text = self._s.post_form(
                f"{self._host}/api/v2/auth/login",
                {"username": self._user, "password": self._pass},
            )
        except HttpError as e:
            raise DownloaderError(
                self.name, f"无法连接 {self._host}", reason="unreachable"
            ) from e
        ok = text.strip() == "Ok." or code == 204
        return (
            f"qbittorrent WebUI 可达 @ {self._host} (登录: {'Ok' if ok else 'failed'})"
        )

    def add(
        self,
        url: str,
        name: str = "",
        dir_: str = "",
        path: str = "",
    ) -> DownloadReceipt:
        self._ensure_login()
        data: dict = {"urls": url}
        if path:
            data["savepath"] = path
        elif self._save_path:
            data["savepath"] = self._save_path
        if self._paused:
            data["paused"] = "true"

        try:
            code, text = self._s.post_form(
                f"{self._host}/api/v2/torrents/add",
                data,
                headers={"Referer": self._host + "/"},
            )
        except HttpError as e:
            raise DownloaderError(self.name, "提交失败", reason="unreachable") from e

        if code != 200:
            raise DownloaderError(
                self.name,
                f"qBittorrent 添加失败 (HTTP {code}): {text[:120]}",
                reason="rejected",
            )
        # 200 => 已接受; qbittorrent 不返回任务 id
        return DownloadReceipt(
            downloader=self.name,
            url=url,
            task_id="",
            status="submitted",
            name=name,
            dir_=dir_ or self._save_path,
            message="qBittorrent 已接受任务(HTTP 200)",
        )
