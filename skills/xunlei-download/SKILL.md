---
name: xunlei-download
description: 通过 xunlei/xlp 提供的本地 HTTP API (/api/v1) 自动化迅雷下载。用于当用户需要添加 magnet/磁力/BT/HTTP 下载任务、指定保存分类目录、查询任务状态、暂停/恢复/删除任务、查看可下载目录，或检查迅雷登录态/设备信息时。适用于本仓库部署的迅雷远程下载服务 (默认端口 2345)。
license: MIT
metadata:
  version: 1.0.0
---

# 迅雷下载 (xunlei-download)

自动化操作本仓库部署的**迅雷远程下载服务 (xlp)** 的对外 HTTP API。核心接口见 [API.md](../../API.md)。

## 前置条件

- xlp 服务正在运行，默认监听 `http://<host>:2345`。
- 迅雷账号已登录（面板扫码登录一次）。未登录时添加下载会返回 `refresh token not found`。
- 可通过环境变量配置：
  - `XL_HOST`：服务地址，默认 `http://localhost:2345`
  - `XL_AUTH`：用户名密码 `user:pass`（仅当服务设置了 `XL_DASHBOARD_PASSWORD` 时需要）

## 使用（推荐用辅助脚本）

```bash
# 脚本: scripts/xunlei.py (已 chmod +x, 依赖 python3)
export XL_HOST=http://your-nas:2345
# 需要认证时: export XL_AUTH=user:pass

./scripts/xunlei.py dirs                          # 列出可下载目录树(选择保存位置)
./scripts/xunlei.py add "magnet:?xt=urn:btih:..." --name "电影"
./scripts/xunlei.py add "magnet:?xt=urn:btih:..." --dir "电影"        # 保存到 /downloads/电影/
./scripts/xunlei.py add "magnet:?xt=urn:btih:..." --dir "动漫/2025"  # 支持多层相对目录
./scripts/xunlei.py add "http://.../x.mp4" --path "/downloads/电影/x.mp4" # 指定完整路径
./scripts/xunlei.py list              # 运行中的任务
./scripts/xunlei.py list --all        # 全部任务
./scripts/xunlei.py pause <task_id>
./scripts/xunlei.py resume <task_id>
./scripts/xunlei.py delete <task_id>
./scripts/xunlei.py info              # 设备配置 + 登录态 + 下载根目录
./scripts/xunlei.py login             # 登录状态
```

脚本直接返回引擎的原始 JSON；任一异常（服务不可达 / 未登录 / 校验失败）会打印错误并返回非零退出码。

## 下载目录与分类选择

添加下载前，**先调用 `dirs` 查看设备可用的下载目录树**（根目录下通常有 `电影/剧集/动漫/音乐/其他` 等分类子目录，Docker 挂载的目录会出现在这里）：

```bash
./scripts/xunlei.py dirs
```

选择保存位置遵循以下优先级：

1. **用户提示词明确指定位置** → 用 `--path /downloads/影视/剧集` 或 `--dir 影视/剧集`；
2. **未指定但 dirs 有匹配分类** → 根据下载内容自动归类到对应子目录（如连续剧→`剧集`、电影→`电影`、动画→`动漫`、音乐→`音乐`、其它→`其他`），目录名**必须与 `dirs` 返回的实际目录名一致**；
3. **都没有** → 下载到下载根目录（如 `/downloads/`）。

若指定的 `--dir`/`--path` 目录在磁盘上不存在，引擎会自动创建（其父级使用下载根目录的身份）。

## API 直接调用（不依赖脚本）

```bash
BASE="${XL_HOST:-http://localhost:2345}/api/v1"
# 列出可下载目录树
curl "$BASE/dirs"
# 添加磁力链下载到 /downloads/动漫/
curl -X POST "$BASE/download" -H 'Content-Type: application/json' \
  -d '{"url":"magnet:?xt=urn:btih:...","name":"动漫","dir":"动漫"}'
# 任务列表（默认进行中；加 all=1 看全部）
curl "$BASE/tasks?all=1"
# 暂停 / 恢复 / 删除（task_id 取任务返回的 id）
curl -X POST "$BASE/tasks/<task_id>/action" -H 'Content-Type: application/json' -d '{"action":"pause"}'
# 状态
curl "$BASE/info" ; curl "$BASE/login"
```

若设置了 `XL_DASHBOARD_PASSWORD`，以上请求需加 `-u user:pass`（Basic Auth）。

## 请求字段

`POST /api/v1/download` body：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `url` | ✅ | `http(s)/magnet/thunder/ftp/ed2k/emule/bt:/file:` 链接 |
| `name` | 否 | 任务名，默认取 url 文件名 |
| `dir` | 否 | 下载根目录下的相对目录，如 `电影` / `动漫/2025`（不存在会自动创建） |
| `path` | 否 | 完整保存路径，如 `/downloads/电影`（与 `dir` 二选一） |
| `space` | 否 | 目标空间，一般留空 |

`GET /api/v1/dirs` 返回下载目录树：`roots[].path` 为根目录，`dirs[]` 为（最多两级）子目录，每项含 `name` / `path`。

任务在 `tasks` 数组，关键字段：`id`、`name`、`phase`（`PHASE_TYPE_PENDING/RUNNING/PAUSED/COMPLETE/ERROR`）、`params`（含 `url`、`real_path`、`progress`/`checked_size`）、`message`。

## 注意事项

- 下载必须登录（面板扫码）。未登录或设备空间未激活（`device_space_not_active`）时新增任务会被引擎拒绝——这通常是服务重启后云端设备状态问题，稍后或保持容器常驻可恢复；已有下载不受影响。
- 迅雷账号有每日免费下载次数限制；超额时新任务会被拒绝。
- 添加下载会自动开始（无需额外 start）。
