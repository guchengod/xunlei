#!/usr/bin/env python3
"""magnetdm.py — 磁力搜索 + 智能挑选 + 多下载器调度 命令行入口.

覆盖技能的四大场景:
  1. 有磁力       -> add <url>                    (直接交给下载器链)
  2. 没有磁力     -> search/best/pick <关键词>     (搜 -> 挑最好 -> 下载)
  3. 首选下载器可用-> add (自动优先 迅雷)
  4. 首选不可用   -> add (自动回退 第二下载器 qBittorrent)

用法:
  magnetdm.py config                        # 打印生效配置
  magnetdm.py search <关键词> [--engines a,b] [--limit N] [--json]
  magnetdm.py best <关键词> [--engines ...] [--json]     # 算法挑一条最优(带理由)
  magnetdm.py pick <关键词> --index N [--json]           # 按排名挑第 N 条(agent 可覆盖算法)
  magnetdm.py add <磁力/链接> [--downloader auto|xunlei|qbittorrent] [--dir D] [--path P] [--name N]
  magnetdm.py get <关键词> [--index N|--best] [--dir D] [--path P]   # 场景2 全流程
  magnetdm.py engines                        # 列出可用引擎/下载器
  magnetdm.py check                          # 探测下载器可用性 (迅雷/qbittorrent)

配置:
  <技能目录>/config.toml (或 DM_CONFIG / --config 指定)
  环境变量覆盖: XL_HOST/XL_AUTH/QBT_HOST/QBT_USER/QBT_PASS
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys

from dm import config as dmc
from dm.downloaders import (
    AllDownloadersFailed,
    DownloaderChain,
    build_downloaders,
)
from dm.engines import EngineError, build_engines, engine_names
from dm.models import DownloadReceipt, SearchResult, human_size
from dm.selection import score_results
from dm.session import HTTPSession

OUT = sys.stdout


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def result_row(d: dict, show_magnet: bool) -> str:
    r: SearchResult = d["result"]
    seeds = str(r.seeders) if r.seeders >= 0 else "-"
    size = human_size(r.size)
    reasons = ",".join(d["reasons"])
    line = f"[{d['rank']:>2}] {r.engine:<11} seeds={seeds:>5} {size:>10}  {r.name[:70]}"
    if reasons:
        line += f"   <{reasons}>"
    if show_magnet:
        line += f"\n        {r.magnet}"
    return line


# ------------------------------------------------------------------ 搜索
def _smart_query(q: str) -> str:
    """智能查询规范化: 去掉会干扰字面匹配的词语后重试。

    例: "葬送的芙莉莲 第二季 高清 中字" -> "葬送的芙莉莲"
    (各引擎标题通常用 S2/Season 2/1080p 等, 中文口语词匹配不到)。
    """
    s = q
    s = re.sub(r"第\s*[一二三四五六七八九十百\d]+\s*(季|部|话|集|卷)", "", s)
    s = re.sub(
        r"(TV版|剧场版|电影版|全集|高清|中字|国语|国配|简中|繁中|"
        r"1080p|720p|2160p|4k|hdr|remux|bluray|web-dl|webrip|全集|完结)",
        "",
        s,
        flags=re.I,
    )
    s = re.sub(r"\s+", " ", s).strip(" ·、，, ")
    return s or q


def do_search(args, cfg) -> list[SearchResult]:
    """多引擎并行搜索, 返回 flatten 的原始结果列表 (带 engine 字段)。"""
    session = HTTPSession(
        proxies=cfg.proxy.as_dict(),
        timeout=cfg.search.per_engine_timeout,
    )
    engines = build_engines(cfg, session)
    if getattr(args, "engines", None):
        wanted = [e.strip() for e in args.engines.split(",") if e.strip()]
        engines = [e for e in engines if e.name in wanted]

    if not engines:
        eprint("没有可用的搜索引擎 (检查 config 引擎列表 / 是否启用代理)")
        sys.exit(2)

    results: list[SearchResult] = []
    errors: dict[str, str] = {}

    def run_one(eng, query) -> tuple[str, list[SearchResult]]:
        try:
            return eng.name, eng.search(query)
        except EngineError as e:
            errors[eng.name] = str(e)
            return eng.name, []

    with cf.ThreadPoolExecutor(max_workers=cfg.search.concurrency) as pool:
        futures = {pool.submit(run_one, e, args.query): e.name for e in engines}
        for fut in cf.as_completed(futures):
            name, rl = fut.result()
            results.extend(rl)

    # 空结果智能兜底: 去掉干扰词后重试一次
    if not results:
        smart = _smart_query(args.query)
        if smart != args.query:
            eprint(f"[info] 原文无人命中, 用精简关键词重试: {smart!r}")
            for eng in engines:
                try:
                    name, rl = run_one(eng, smart)
                except Exception as e:  # noqa: BLE001
                    eprint(f"[warn] 引擎 {eng.name} 重试失败: {e}")
                    rl = []
                results.extend(rl)

    for name, err in errors.items():
        eprint(f"[warn] 引擎 {name} 失败: {err}")
    return results


def print_table(scored: list[dict], show_magnet: bool, limit: int | None = None) -> None:
    if not scored:
        print("(无结果)")
        return
    for d in scored[:limit]:
        print(result_row(d, show_magnet))
    if len(scored) > (limit or len(scored)):
        print(f"... 共 {len(scored)} 条, 显示前 {limit} 条")


def scored_to_json(scored: list[dict]) -> str:
    body = []
    for d in scored:
        r: SearchResult = d["result"]
        item = r.to_dict()
        item["rank"] = d["rank"]
        item["score"] = d["score"]
        item["reasons"] = d["reasons"]
        item["breakdown"] = d["breakdown"]
        body.append(item)
    return json.dumps(body, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ 下载
def do_add(args, cfg) -> DownloadReceipt:
    session = HTTPSession(proxies=cfg.proxy.as_dict(), timeout=20)
    downloaders = build_downloaders(cfg, session)
    if args.downloader and args.downloader != "auto":
        names = [d.name for d in downloaders]
        if args.downloader not in names:
            eprint(f"未知下载器 {args.downloader}; 可用: {names}")
            sys.exit(2)
        ordered = [d for d in downloaders if d.name == args.downloader]
    else:
        ordered = downloaders

    chain = DownloaderChain(ordered)
    try:
        receipt, errors = chain.download(
            args.url, name=args.name or "", dir_=args.dir or "", path=args.path or ""
        )
    except AllDownloadersFailed as e:
        for err in e.errors:
            eprint(f"[下载器失败] {err}")
        print(json.dumps({"ok": False, "url": args.url, "errors": [
            {"downloader": x.downloader, "reason": x.reason, "message": str(x)}
            for x in e.errors
        ]}, ensure_ascii=False, indent=2))
        sys.exit(3)
    if args.json:
        print(json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"✔ 已提交到 [{receipt.downloader}]  task_id={receipt.task_id or '-'}  url={receipt.url}")
        if receipt.message:
            print(receipt.message)
    return receipt


# ------------------------------------------------------------------ 主流程
def main() -> None:
    p = argparse.ArgumentParser(
        prog="magnetdm.py", description="磁力搜索 + 智能挑选 + 多下载器调度"
    )
    p.add_argument("--config", help="配置文件路径 (默认 <技能目录>/config.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("config", help="打印生效配置"); sp.set_defaults(fn=cmd_config)

    sp = sub.add_parser("engines", help="列出可用引擎/下载器"); sp.set_defaults(fn=cmd_engines)

    sp = sub.add_parser("check", help="探测下载器可用性"); sp.set_defaults(fn=cmd_check)

    sp = sub.add_parser("search", help="多引擎搜索")
    sp.add_argument("query")
    sp.add_argument("--engines")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--show-magnet", action="store_true")
    sp.add_argument("--json", action="store_true", help="输出结构化 JSON (供 agent 判断)")
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("best", help="搜索 + 算法挑选最优一条")
    sp.add_argument("query")
    sp.add_argument("--engines")
    sp.add_argument("--top", type=int, default=3, help="额外展示前 N 条给 agent 参考")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_best)

    sp = sub.add_parser("pick", help="搜索后按排名挑第 N 条 (agent 覆盖算法用)")
    sp.add_argument("query")
    sp.add_argument("--index", type=int, required=True, help="1-based 排名序号")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_pick)

    sp = sub.add_parser("add", help="直接提交链接给下载器链 (场景1/3/4)")
    sp.add_argument("url")
    sp.add_argument("--name")
    sp.add_argument("--dir")
    sp.add_argument("--path")
    sp.add_argument("--downloader", default="auto",
                    help="auto(按配置回退) / xunlei / qbittorrent")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("get", help="全流程: 搜索->挑选->下载 (场景2)")
    sp.add_argument("query")
    sp.add_argument("--index", type=int, help="直接挑第 N 名 (跳过算法)")
    sp.add_argument("--dir")
    sp.add_argument("--path")
    sp.add_argument("--downloader", default="auto")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_get)

    args = p.parse_args()
    args.fn(args, dmc.load_config(args.config))


# ------------------------------------------------------------------ 子命令实现
def cmd_config(args, cfg) -> None:
    print(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2))
    print(f"# 配置文件: {cfg.config_path}")


def cmd_engines(args, cfg) -> None:
    print("引擎:", ", ".join(engine_names()))
    session = HTTPSession(proxies=cfg.proxy.as_dict(), timeout=5)
    build = build_engines(cfg, session)
    print(f"当前生效(代理={'开' if cfg.proxy.enabled else '关'}):",
          ", ".join(e.name for e in build) or "(无)")
    from dm.downloaders import downloader_names
    print("下载器:", ", ".join(downloader_names()))
    print("下载器优先级:", " -> ".join(cfg.downloaders.preferred))


def cmd_check(args, cfg) -> None:
    session = HTTPSession(proxies=cfg.proxy.as_dict(), timeout=8)
    for d in build_downloaders(cfg, session):
        try:
            print(d.check())
        except Exception as e:
            print(str(e))


def cmd_search(args, cfg) -> None:
    raw = do_search(args, cfg)
    if args.json:
        print(json.dumps([r.to_dict() for r in raw], ensure_ascii=False, indent=2))
        return
    print_table([{"rank": i + 1, "score": 0.0, "reasons": ["未打分"],
                  "result": r} for i, r in enumerate(raw)], args.show_magnet, args.limit)


def cmd_best(args, cfg) -> None:
    raw = do_search(args, cfg)
    scored = score_results(
        raw, weights=cfg.weights, selection=cfg.selection,
        limit=cfg.selection.max_candidates, query=args.query,
    )
    if not scored:
        print("(无结果)")
        sys.exit(2)
    if args.json:
        top = scored_to_json(scored[: args.top])
        print(top)
        return
    print("===== 算法建议的最优候选 =====")
    print(result_row(scored[0], True))
    if len(scored) > 1:
        print("\n===== 其余候选 (供 agent 复核, 可用 pick --index N 覆盖) =====")
        print_table(scored[1 : min(args.top, len(scored))], True, args.top)


def cmd_pick(args, cfg) -> None:
    raw = do_search(args, cfg)
    scored = score_results(
        raw, weights=cfg.weights, selection=cfg.selection,
        limit=cfg.selection.max_candidates, query=args.query,
    )
    if args.index < 1 or args.index > len(scored):
        eprint(f"索引越界: 只有 {len(scored)} 条")
        sys.exit(2)
    chosen = scored[args.index - 1]
    if args.json:
        print(scored_to_json([chosen]))
    else:
        print(result_row(chosen, True))


def cmd_add(args, cfg) -> None:
    do_add(args, cfg)


def cmd_get(args, cfg) -> None:
    # 1) 搜索
    raw = do_search(args, cfg)
    scored = score_results(
        raw, weights=cfg.weights, selection=cfg.selection,
        limit=cfg.selection.max_candidates, query=args.query,
    )
    if not scored:
        eprint("未搜到结果")
        sys.exit(2)

    # 2) 挑选: agent 指定 index 优先, 否则算法最优
    chosen = scored[args.index - 1] if args.index else scored[0]
    r: SearchResult = chosen["result"]
    if not r.magnet:
        eprint("该候选无磁力, 无法下载")
        sys.exit(2)

    if args.json:
        # 结构化模式: 一次输出唯一 JSON 对象
        out: dict = {
            "query": args.query,
            "selected": r.to_dict() | {"rank": chosen["rank"],
                                       "score": chosen["score"],
                                       "reasons": chosen["reasons"]},
            "dir": args.dir or "",
            "downloader": args.downloader or "auto",
        }
        session = HTTPSession(proxies=cfg.proxy.as_dict(), timeout=20)
        chain = DownloaderChain(build_downloaders(cfg, session))
        try:
            receipt, _ = chain.download(
                r.magnet, name=r.name, dir_=args.dir or "", path=args.path or ""
            )
        except AllDownloadersFailed as e:
            out["ok"] = False
            out["errors"] = [
                {"downloader": x.downloader, "reason": x.reason, "message": str(x)}
                for x in e.errors
            ]
            print(json.dumps(out, ensure_ascii=False, indent=2))
            sys.exit(3)
        out["ok"] = True
        out["receipt"] = receipt.to_dict()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    # 人类可读模式
    print(f"选中 [{chosen['rank']}] {r.engine} seeds={r.seeders}  {r.name}")
    print(f"   磁力: {r.magnet}")
    print(f"   理由: {','.join(chosen['reasons']) or '无'}")
    do_add(
        argparse.Namespace(url=r.magnet, name=r.name, dir=args.dir,
                           path=args.path, downloader=args.downloader, json=False),
        cfg,
    )


if __name__ == "__main__":
    main()
