# 迅雷远程下载服务(非官方)

[![GitHub Stars][1]][2]

[1]: https://img.shields.io/github/stars/guchengod/xunlei?style=flat
[2]: https://star-history.com/#guchengod/xunlei&Date

从迅雷群晖套件中提取出来用于其他设备的迅雷远程下载服务程序。仅供研究学习测试。 \
本程序仅提供 Linux 模拟和容器化运行环境，未对原版迅雷程序进行任何修改。

## 特性

- 支持本地运行和容器化运行
- 重构的远程下载运行环境，具备比较完善的回滚流程
- 容器镜像基于 busybox，SPK 运行时从远程下载，镜像体积小，可随时指定迅雷引擎版本
- **对外 HTTP API**（详见 [API.md](API.md)）：添加下载任务（支持按分类目录保存）、任务列表、暂停/恢复/删除、可下载目录树与登录态查询，方便 Agent / Skill 自动化
- **内置 Agent Skill**（`skills/xunlei-download/`，符合 Agent Skills 标准）：任何支持该标准的 agent 可一键安装、自动操作下载
- 跨平台开发：非 Linux 主机也可编译本项目
- 镜像已发布到阿里云容器镜像服务（国内拉取更快）
- 支持面板在线更新

## Agent / Skill 自动化

本仓库自带一个 Agent Skill（`skills/xunlei-download/`），任何支持 Agent Skills 的 agent / AI 工具都可以加载它，通过 HTTP API 自动**添加下载、管理任务**，适合自动化。接口完整说明见 [API.md](API.md)。

### Skill 说明

- `skills/xunlei-download/` 遵循 [Agent Skills 规范](https://agentskills.io/specification)：目录名即 skill 名，含 `SKILL.md` 与辅助脚本，任何支持该标准的工具都能加载。
- 加载后按其 `SKILL.md` 使用即可：添加/管理下载、指定分类目录保存。
- 分类放置：用 `dirs` 查看可下载目录树，按内容类型（剧集/电影/动漫/音乐/其他）匹配子目录保存，或按用户指定的位置保存；未指定则落到下载根目录。

### 从 GitHub 安装（给任何 Agent 的一句话提示词）

可复制给任意支持 skill 的 agent / AI 工具：

> 请从 <https://github.com/guchengod/xunlei> 仓库安装 `skills/xunlei-download` skill：
>
> 1) `git clone` 该仓库；
> 2) 把 `skills/xunlei-download` 目录安装到你的 skill 目录（按你所处 agent 的 skill 注册方式即可）；
> 3) 加载并阅读其 `SKILL.md`，然后用它给迅雷远程下载服务添加下载任务（支持 magnet / HTTP / BT，可指定分类目录）。

或命令行：

```bash
git clone --depth 1 https://github.com/guchengod/xunlei.git /tmp/xunlei && \
  cp -r /tmp/xunlei/skills/xunlei-download <你的 skills 目录>/ && \
  rm -rf /tmp/xunlei
```

（把 `<你的 skills 目录>` 替换为你所用 agent 的 skill 目录，不存在时先用 `mkdir -p` 创建。）

### 注意事项

- 添加下载前需先在网页面板（端口 2345）扫码登录迅雷账号一次；
- 未登录或在容器/进程重启后设备空间未激活时，新增任务会被引擎拒绝（`refresh token not found` / `device_space_not_active`），保持容器常驻可避免大部分情况，已有下载不受影响；
- 迅雷账号有每日免费下载次数限制，超额时新任务会被拒绝。

## 使用

### Docker

#### 镜像

```plain
crpi-7g2swy3pv0gxn73h.cn-beijing.personal.cr.aliyuncs.com/galvin/xunlei:1.2
```

#### 权限要求

容器需能**挂载 proc/dev 并 chroot**，否则将退化运行（跳过挂载）。按优先级：

1. 推荐：`privileged: true`（若平台允许）；
2. 若平台（如飞牛 fnOS）**禁止 privileged**：用 `cap_add: [SYS_ADMIN]`；
3. 若均不可用：本程序已做**降级**——挂载失败自动跳过继续启动，但功能完整度取决于平台（缺少 /proc、/dev 时部分能力可能受限）。

飞牛等 NAS 部署请按上面 2/3 处理，仓库根目录 [`docker-compose.yaml`](docker-compose.yaml) 默认使用 `cap_add: [SYS_ADMIN]`。

#### 参数

程序默认参数

```shell
OPTIONS:
      --dashboard_port uint16       网页访问的端口 [XL_DASHBOARD_PORT, XL_PORT] (default 2345)
      --dashboard_ip ip             网页访问绑定IP，默认绑定所有IP [XL_DASHBOARD_IP, XL_IP]
      --dashboard_username string   网页访问的用户名 [XL_DASHBOARD_USERNAME, XL_BA_USER]
      --dashboard_password string   网页访问的密码 [XL_DASHBOARD_PASSWORD, XL_BA_PASSWORD]
  -d, --dir_download strings        下载保存文件夹，可多次指定，需确保有权限访问 [XL_DIR_DOWNLOAD] (default [/mnt/d/Code/github.com/cnk3x/xunlei/artifacts/xunlei/downloads])
  -D, --dir_data string             程序数据保存文件夹，其下'.drive'文件夹中，存储了登录的账号，下载进度等信息 [XL_DIR_DATA] (default "/mnt/d/Code/github.com/cnk3x/xunlei/artifacts/xunlei/data")
  -u, --uid uint32                  运行迅雷的用户ID [XL_UID, UID]
  -g, --gid uint32                  运行迅雷的用户组ID [XL_GID, GID]
      --prevent_update              阻止更新 [XL_PREVENT_UPDATE]
  -r, --chroot string               主目录 [XL_CHROOT] (default "/mnt/d/Code/github.com/cnk3x/xunlei/artifacts/xunlei")
      --spk string                  SPK 下载链接 [XL_SPK] (default "https://down.sandai.net/nas/nasxunlei-DSM7-x86_64.spk")
  -F, --force_download              强制下载 [XL_SPK_FORCE_DOWNLOAD]
      --launcher_log_file string    迅雷启动器日志文件 [XL_LAUNCHER_LOG_FILE]
      --debug                       是否开启调试日志 [XL_DEBUG]
```

容器内参数默认值（在容器内运行时，覆盖程序默认参数）

```shell
#网页访问的端口
XL_DASHBOARD_PORT=2345
#网页访问绑定IP
XL_DASHBOARD_IP=
# 网页访问的用户名
XL_DASHBOARD_USERNAME=
# 网页访问的密码
XL_DASHBOARD_PASSWORD=
# 如果需要指定多个下载目录，手动指定XL_DIR_DOWNLOAD
# 多个以冒号`:`隔开，在容器内,都必须以 /xunlei 开头，迅雷面板选择保存路径显示会去掉/xunlei前缀
# 指定后可以在 volumes 中绑定宿主机实际目录
# 迅雷云盘的缓存会使用第一个目录会缓存
# /xunlei/后面可以用中文
# 不设置默认一个目录 /xunlei/downloads
XL_DIR_DOWNLOAD=/xunlei/downloads
# 程序数据保存文件夹，存储了登录的账号，下载进度等信息,容器内不要更改
XL_DIR_DATA=/xunlei/data
# 阻止更新
XL_PREVENT_UPDATE=false
# SPK下载链接, 默认指向官方下载地址，如果失效，请自行指定 ***.spk的下载地址
# 可以使用 file:/// 访问本地文件, 真实使用路径会去掉 file://, 所以如果是绝对路径, 三个斜杠不能少
XL_SPK=
# 是否强制下载SPK, 0: 不强制, 1: 强制，如果不指定强制下载，不会重复下载SPK
XL_SPK_FORCE_DOWNLOAD=0
# 运行迅雷的用户ID, 默认0,即 root 账号
# 推荐使用当前账号的UID和GID, 一般来说是 1000, 以免出现下载后普通账号无法处理文件的情况
XL_UID=0
# 运行迅雷的用户GID
XL_GID=0
# 是否开启调试日志
XL_DEBUG=false
```

#### Docker Compose

仓库根目录提供可直接使用的 [`docker-compose.yaml`](docker-compose.yaml)（含镜像、环境变量、Volume 挂载与注释），直接 `docker compose up -d` 即可，此处不再重复示例。

## 上游与本仓库的关系

本仓库是基于 [cnk3x/xunlei](https://github.com/cnk3x/xunlei)（fork 自 <https://github.com/cnk3x/xunlei.git>）的 fork，用于研究、学习与个人使用，保留上游全部功能；感谢原作者 [cnk3x](https://github.com/cnk3x) 及其贡献者。
