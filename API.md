# 对外 HTTP API (Agent / Skill 用)

xlp 内置一套供外部程序(Agent / Skill / 脚本)调用的 JSON API, 用于自动添加/管理迅雷下载任务。
它把请求转发到迅雷主程序 (pan-cli engine) 的 unix socket, 无需逆向或模拟登录流程。

- 基地址: `http://<host>:2345/api/v1`
- 认证: 仅当设置了 `--dashboard_password` / `XL_DASHBOARD_PASSWORD` 时才启用 HTTP Basic Auth;
  未设置则完全开放 (推荐内网使用, 暴露到公网前请务必设置密码)。
- 响应: `application/json`, 引擎错误会原样透传 (如 `{"error":"...","error_description":"..."}`)。

> 说明: 迅雷下载需要账号登录。登录后即可使用; 未登录时 API 会返回
> `refresh token not found` 之类的引擎错误。登录方式与网页面板一致 (扫码)。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/info` | 设备配置、下载目录、登录态、用户信息 |
| GET | `/api/v1/dirs` | 列出可下载目录树 (选择保存位置) |
| GET | `/api/v1/login` | 登录状态 (`logged_in`) |
| POST | `/api/v1/download` | 添加下载任务 (URL / magnet / 种子等，自动开始) |
| GET | `/api/v1/tasks` | 任务列表 (支持 `all=1` 看全部) |
| GET | `/api/v1/tasks/{id}/files` | 用任务原始 URL 重新解析下载文件列表 (磁力/种子文件树) |
| POST | `/api/v1/tasks/{id}/action` | 暂停 / 恢复 / 删除任务 |

## 可下载目录

```
GET /api/v1/dirs
```

返回设备本地下载目录树 (由 xlp 直接扫描 Docker 挂载/download 根目录得到):

```json
{
  "roots": [
    {
      "name": "downloads",
      "path": "/downloads/",
      "dirs": [
        { "name": "电影", "path": "/downloads/电影", "dirs": [] },
        { "name": "动漫", "path": "/downloads/动漫", "dirs": [
            { "name": "2025", "path": "/downloads/动漫/2025" }
        ] }
      ]
    }
  ]
}
```

`roots[].path` 为下载根目录 (Docker 里通常对应挂载卷), `roots[].dirs` 为最多两级的子目录。
添加任务时通过 `dir` 或 `path` 指定保存位置即可。

## 添加下载

```
POST /api/v1/download
Authorization: Basic ...
Content-Type: application/json

{
  "url":   "magnet:?xt=urn:btih:...",   // 必填: http/https/magnet/thunder/ftp/ed2k/emule/bt:/file:
  "name":  "任务名(可选)",               // 默认取 url 文件名
  "dir":   "电影/2025(可选)",           // 下载根目录下的相对目录, 应来自 /dirs
  "path":  "/downloads/子目录(可选)",    // 完整保存路径, 与 dir 二选一
  "space": "目标空间(可选)"             // 账户无目标时留空由引擎决定
}
```

返回: 引擎创建任务的原始响应 (成功时含 `task`)。

服务端创建流程与迅雷面板一致：

1. 从当前 `user#runner` 任务的 `params.target` 获取活动设备空间；
2. 调用 `/drive/v1/resource/list` 解析链接，取得真实任务名、文件大小、文件数量和文件树；
3. 默认选择解析出的全部文件，再调用 `/drive/v1/task` 创建并启动任务。

因此磁力链接即使没有 `dn` 参数，也会使用迅雷解析出的真实名称。解析、登录或设备空间错误会返回非 2xx HTTP 状态，并保留引擎原始错误 JSON。

## 任务列表

```
GET /api/v1/tasks?all=1&limit=100&page_token=
```

- 默认只返回未完成任务 (`PHASE_TYPE_PENDING/RUNNING`); 加 `all=1` 返回全部。
- 响应为引擎原始 JSON, 任务在 `tasks` 数组, 常用字段: `id`、`name`、`params`、
  `phase`(如 `PHASE_TYPE_RUNNING`)、`error` 等。

## 任务操作

```
POST /api/v1/tasks/{task_id}/action
Content-Type: application/json

{ "action": "pause" }    // 暂停
{ "action": "resume" }   // 恢复
{ "action": "delete" }   // 删除
```

## 示例 (Shell)

```sh
AUTH="admin:你的密码"
BASE="http://127.0.0.1:2345/api/v1"

# 添加 magnet 下载 (自动开始)
curl -u "$AUTH" -X POST "$BASE/download" \
  -H 'Content-Type: application/json' \
  -d '{"url":"magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"}'

# 列出可下载目录, 再按分类保存
curl -s "$BASE/dirs"
curl -u "$AUTH" -X POST "$BASE/download" \
  -H 'Content-Type: application/json' \
  -d '{"url":"magnet:...","dir":"动漫/2025"}'

# 查询任务
curl -su "$AUTH" "$BASE/tasks"

# 暂停
curl -u "$AUTH" -X POST "$BASE/tasks/<task_id>/action" \
  -H 'Content-Type: application/json' -d '{"action":"pause"}'
```

## 实现

- `xlapi.go` — 路由与处理器
- `pkg/drive/` — 引擎 unix socket 客户端 (自动获取引擎签发的 `pan-auth` JWT 并透传)

内部实际调用的是引擎的 `/drive/v1/resource/list`、`/drive/v1/task`、`/drive/v1/tasks` 等接口。
创建任务请求体中的 `name`、`file_size`、`total_file_count` 来自解析结果，`space` 与 `params.target` 使用当前 runner 的设备空间；全部下载时 `sub_file_index` 使用迅雷面板兼容的全选值。
