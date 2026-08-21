---
name: download
description: 磁力搜索与多下载器调度技能 (迅雷远程下载 + 可扩展)。用于当用户需要 ① 搜索磁力/种子 (snowfl·animetosho·tsukihime 国内直连 + 可选代理站) ② 没有磁力时按规则智能挑选最优资源 ③ 把磁力/链接交给首选下载器 (默认迅雷远程下载 xlp, 失败自动回退第二下载器 qBittorrent) 下载。适用于本仓库部署的迅雷远程下载服务 (默认端口 2345), 也支持 qBittorrent WebUI 作为备选。提供零第三方依赖的 Python 脚本 (scripts/magnetdm.py + scripts/xunlei.py)。
license: MIT
metadata:
  version: 2.0.0
---

# 磁力搜索 + 迅雷/qBittorrent 下载

自动化整个 **"要找的资源没有现成磁力 -> 去搜 -> 挑最好 -> 交给下载器"** 的链路。
脚本全部零第三方依赖 (Python3.11+ stdlib), 可在用户机器 / NAS 上直接跑。

## 四大场景 (整体逻辑)

1. **有磁力** 且要下载       → `magnetdm.py add <磁力链>`
2. **没有磁力** (只有片名)  → `magnetdm.py get <片名>`   = 搜索 → 判断最好一条 → 下载
3. **下载用首选下载器**      → 配置 `[downloaders].preferred` 第一个 (默认 `xunlei`), 可用则下载
4. **首选下载器不可用**      → 自动回退配置里的第二下载器 (默认 `qbittorrent`), 再下载

> 场景 3/4 由 DownloaderChain (责任链) 实现: 迅雷**连接失败 / 未登录 / 设备空间未激活 / 每日次数超限** 都会自动落到 qBittorrent, 全部失败才报错。

## 前置条件

- Python ≥ 3.11 (TOML 配置用标准库 tomllib)。
- 场景 1/3/4 至少一个下载器可用:
  - **迅雷:** xlp 服务运行中, 默认 `http://<host>:2345`, 面板扫码登录过一次; 未登录时返回 `refresh token not found`。
  - **qBittorrent:** WebUI 已启用 (默认 8080), 打开"WEB UI"并记下账号密码。
- 场景 2 搜索至少在 `[search].engines_always` 里有一个站可用 (默认三个已实测国内直连):
  - `snowfl` (通用聚合, 国际影视/剧集/音乐/游戏覆盖面最广)
  - `animetosho` (动漫, Nyaa 系全量, 带做种数)
  - `tsukihime` (动漫聚合, 量大)
- 想要国际站 (`nyaa` / `btdig` / `apibay` 海盗湾): 在 `config.toml` 里填代理并 `[proxy] enabled=true`。

## 使用

### 1) 直接给磁力下载 (有磁力 → 下载)

```bash
# 在本 skill 的脚本目录下执行 (仓库: skills/download/scripts; 已安装: ~/.pi/agent/skills/download/scripts)
cd <本skill目录>/scripts
./magnetdm.py add "magnet:?xt=urn:btih:..." --dir 电影
./magnetdm.py add "https://.../x.torrent" --name 我的文件      # http/bt: 同样支持
./magnetdm.py add "magnet:..." --downloader xunlei             # 强制指定下载器 (不自动回退)
```

`--dir` 为迅雷下载根目录下的相对分类 (如 `电影` / `动漫/2025`), 自动创建。
**下载前先看迅雷可用目录**: `./xunlei.py dirs` (根下通常有 `电影/剧集/动漫/音乐/其他`)。

### 2) 没有磁力 → 搜索 → 挑最好 → 下载 (二选一)

```bash
# 方式 A: 全自动 (算法按配置规则打分选最优, 直接下载)
./magnetdm.py get "葬送的芙莉莲" --dir 动漫

# 方式 B: agent/人 介入挑选 (推荐, 更符合"综合判断")
./magnetdm.py best "葬送的芙莉莲"            # 看算法建议 + 理由, 并列出前 N 名候选
./magnetdm.py pick "葬送的芙莉莲" --index 3   # 推翻算法, 手动挑第 3 名
./magnetdm.py get "葬送的芙莉莲" --index 3 --dir 动漫   # 用第 3 名下载
```

所有子命令都带 `--json` 输出结构化结果 (供 agent 二次判断)。

### 3) 只搜索不下载

```bash
./magnetdm.py search "关键词" [--limit 20] [--show-magnet]
./magnetdm.py search "关键词" --json              # agent 友好 JSON
./magnetdm.py search "关键词" --engines snowfl,tsukihime   # 指定引擎
./magnetdm.py best "关键词" --top 5 --json        # 打分排序 + 理由
./magnetdm.py pick "关键词" --index 2 --json      # 取第 2 名
```

### 4) 运维

```bash
./magnetdm.py config      # 查看生效配置 (含代理/权重/下载器优先级)
./magnetdm.py engines     # 查看可用引擎, 及当前代理开关下实际启用了哪些
./magnetdm.py check       # 探测迅雷/qBittorrent 可用性
./xunlei.py list --all    # 迅雷任务列表 (原生脚本, 仍可用)
```

## Agent 判断规则 (场景 2 的"挑一条")

系统先按 `config.toml [weights]` 的权重打底分 (Quality/Chinese/Seeders/Size),
再结合以下**用户语义**做最终裁决, 可随时用 `pick --index N` / `get --index N` 覆盖:

- **首选质量**: 1080p/2160p/Remux/BluRay > 720p > DVDrip/HDTV > CAM/TS(直接排除)。
- **首选有中文**: 名称含 `中字/简中/繁中/双语/国语/中配/国配/chs/cht/mandarin` 优先;
  中文动漫优先考虑带"中文字幕"或"国语配音"的版本, 做种太低 (<20) 的中配可以降级选英配+中字。
- **首选做种多**: 做种数太少 (<30) 除非质量/语言明显更优否则不选; 冷门资源可放宽。
- **大小合理性**: 明显过小 (<50MB 往往是 sample) 直接排除; 电影/剧集参考 1080p 常见体积。
- **关键词技巧**: 中文搜不到或搜到少时, 用英文/罗马音重搜 (如 "葬送的芙莉莲" → "sousou no frieren");
  脚本已内置"去第X季/高清/中字等词"的自动重试, 但仍建议 agent 主动尝试同义关键词。
- **引擎分工**: 动漫资源优先 animetosho/tsukihime; 影视/剧集/音乐/游戏优先 snowfl;
  开代理后可加 nyaa(动漫)/btdig(冷门老资源)/apibay(全球最新)。

## 配置 (config.toml)

```toml
[search]
engines_always      = ["snowfl", "animetosho", "tsukihime"]   # 国内直连站
engines_with_proxy  = ["nyaa", "btdig", "apibay"]             # 有代理才启用
max_results_per_engine = 60

[proxy]
enabled = false
http    = ""      # 例 "http://127.0.0.1:7890"; 启用即自动加上面国际站

[selection]
chinese_markers = ["中字","简中","繁中","双语","中文字幕","国语","中配","国配","chs","cht","mandarin"]  # 按需增删
bad_markers     = ["sample","trailer","预告","测试","demo"]   # 命中则大幅降权

[weights]
quality = 30   # 画质 (1080p/remux...)
chinese = 25   # 中文字幕/配音
seeders = 30   # 做种数
size    = 15   # 大小合理性

[downloaders]
preferred = ["xunlei", "qbittorrent"]    # 顺序 = 首选 -> 回退

[xunlei]
host = "http://localhost:2345"           # XL_HOST 可覆盖
auth = ""                                # XL_AUTH 可覆盖

[qbittorrent]
host = "http://localhost:8080"           # QBT_HOST/QBT_USER/QBT_PASS 可覆盖
username = "admin"
password = "adminadmin"
save_path = ""
```

改完配置立即生效, 无需重启。完整示例见 `config.example.toml`。

## 目录结构

```
scripts/
  magnetdm.py         主入口 (search/best/pick/add/get/config/engines/check)
  xunlei.py           迅雷原生命令行 (dirs/add/list/pause/resume/delete/info)
  dm/                 设计模式包
    engines/          搜索引擎: 模板方法+工厂注册表 (snowfl/animetosho/tsukihime/nyaa/btdig/apibay/dmhy)
    downloaders/      下载器: 策略模式+责任链 (xunlei/qbittorrent)
    selection.py      加权评分算法 (可配置, agent 可覆盖)
    session.py        统一 HTTP (代理/超时/重试/UA)
    config.py         配置加载 (TOML + 环境变量)
    models.py         SearchResult / DownloadReceipt 数据模型
```

## 注意事项

- 磁力站偶发抖动属正常; 单个引擎失败会被自动隔离 (打印 `[warn]`) 不影响其它引擎。
- 迅雷免费账号有每日次数限制; 超额 (`limit/quota`) 会自动回退 qBittorrent。
- 迅雷面板登录态失效会返回 `refresh token not found` -> 自动回退 qBittorrent, 或让用户重新扫码。
- 下载必须尊重版权与当地法规; 避免 sample/疑似广告的异常小文件。
