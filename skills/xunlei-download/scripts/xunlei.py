#!/usr/bin/env python3
"""xunlei.py — 迅雷远程下载 (xlp) 对外 HTTP API 的命令行封装。

用法:
  xunlei.py dirs [--depth N]
  xunlei.py add <url> [--name NAME] [--dir DIR] [--path PATH] [--space SPACE]
  xunlei.py list [--all] [--limit N] [--space SPACE]
  xunlei.py pause|resume|delete <task_id>
  xunlei.py info
  xunlei.py login

说明:
  dirs  列出设备本地可下载目录树(根目录下的 电影/动漫/电视剧/其他 等), 供选择保存位置；
  add   --dir 指定下载根目录下的相对目录(如 "电影" / "动漫/2025"), --path 指定完整路径, 二选一。

环境变量:
  XL_HOST  服务地址, 默认 http://localhost:2345
  XL_AUTH  用户名密码 "user:pass" (可选, 服务端设置了 XL_DASHBOARD_PASSWORD 时使用)
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST = "http://localhost:2345"


def request(
    method: str, path: str, body: dict | None = None, query: dict | None = None
):
    host = os.environ.get("XL_HOST", DEFAULT_HOST).rstrip("/")
    url = f"{host}/api/v1{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query, safe="")

    headers = {"Content-Type": "application/json" if body is not None else "text/plain"}
    auth = os.environ.get("XL_AUTH")
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()

    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data or None, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        code = e.code
    except Exception as e:  # network / DNS / refused
        print(
            json.dumps({"error": f"无法连接 {url}: {e}"}, ensure_ascii=False, indent=2)
        )
        sys.exit(1)

    try:
        obj = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        obj = {"raw": raw.decode("utf-8", "replace")}

    print(json.dumps(obj, ensure_ascii=False, indent=2))
    if code >= 400 or (isinstance(obj, dict) and obj.get("error")):
        sys.exit(1)
    return obj


def cmd_dirs(a):
    return request("GET", "/dirs")


def cmd_add(a):
    return request(
        "POST",
        "/download",
        {
            "url": a.url,
            **({"name": a.name} if a.name else {}),
            **({"dir": a.dir} if a.dir else {}),
            **({"path": a.path} if a.path else {}),
            **({"space": a.space} if a.space else {}),
        },
    )


def cmd_list(a):
    q = {"limit": a.limit}
    if a.all:
        q["all"] = "1"
    if a.space:
        q["space"] = a.space
    return request("GET", "/tasks", query=q)


def cmd_action(a):
    return request("POST", f"/tasks/{a.task_id}/action", {"action": a.action})


def main():
    p = argparse.ArgumentParser(description="迅雷远程下载 API 客户端")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("dirs", help="列出可下载目录树").set_defaults(fn=cmd_dirs)

    pa = sub.add_parser("add", help="添加下载任务 (magnet/http/bt 等)")
    pa.add_argument("url")
    pa.add_argument("--name")
    pa.add_argument(
        "--dir", help="下载根目录下的相对目录, 如 电影 / 动漫/2025 (会自动创建)"
    )
    pa.add_argument("--path", help="完整保存路径, 如 /downloads/电影")
    pa.add_argument("--space")
    pa.set_defaults(fn=cmd_add)

    pl = sub.add_parser("list", help="任务列表")
    pl.add_argument("--all", action="store_true", help="包含已完成/已删除等全部")
    pl.add_argument("--limit", type=int, default=100)
    pl.add_argument("--space")
    pl.set_defaults(fn=cmd_list)

    for action in ("pause", "resume", "delete"):
        pa2 = sub.add_parser(action, help=f"{action} 任务")
        pa2.add_argument("task_id")
        pa2.set_defaults(fn=cmd_action, action=action)

    sub.add_parser("info", help="设备配置+登录态").set_defaults(
        fn=lambda _: request("GET", "/info")
    )
    sub.add_parser("login", help="登录状态").set_defaults(
        fn=lambda _: request("GET", "/login")
    )

    args = p.parse_args()
    # 子命令成功时返回的是服务端 JSON 对象，不能把它传给 sys.exit：
    # Python 会把任何非整数对象视为错误消息，并以状态码 1 退出。
    # request() 已在网络、HTTP 和业务错误时显式 sys.exit(1)。
    args.fn(args)


if __name__ == "__main__":
    main()
