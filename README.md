# 迅雷远程下载服务(非官方)

[![GitHub Stars][1]][2] [![Docker Pulls][3]][5] [![Docker Version][4]][5]

[1]: https://img.shields.io/github/stars/cnk3x/xunlei?style=flat
[2]: https://star-history.com/#cnk3x/xunlei&Date
[3]: https://img.shields.io/docker/pulls/cnk3x/xunlei.svg
[4]: https://img.shields.io/docker/v/cnk3x/xunlei
[5]: https://hub.docker.com/r/cnk3x/xunlei

> **本仓库为 [cnk3x/xunlei](https://github.com/cnk3x/xunlei) 的 fork**
>
> fork 自 [https://github.com/cnk3x/xunlei.git](https://github.com/cnk3x/xunlei.git)，用于研究、学习与个人使用的二次开发。
> 感谢原作者 [cnk3x](https://github.com/cnk3x) 及其贡献者，本仓库保留上游全部功能与文档。

本 fork 在上游基础上的主要改动：

- 新增对外 **HTTP API**（详见 [API.md](API.md)）：`POST /api/v1/download` 添加下载任务、任务列表/暂停/恢复/删除、登录态与设备信息查询，方便 Agent / Skill 自动化操作；
- 面板登录保护改为可选：仅设置 `XL_DASHBOARD_PASSWORD`（`--dashboard_password`）时才启用用户名密码，未设置则直接开放（直达迅雷扫码登录）；
- 修复 index.cgi 登录态校验在部分容器（glibc < 2.34，如 ubuntu:focal）中失败的问题（将嵌入的 `authenticate_cgi` 改为静态编译）；
- 非 Linux 平台（如 macOS 开发机）可正常编译本项目。

从迅雷群晖套件中提取出来用于其他设备的迅雷远程下载服务程序。仅供研究学习测试。 \
本程序仅提供 Linux 模拟和容器化运行环境，未对原版迅雷程序进行任何修改。

**3.20 版本介绍在此: (<https://github.com/cnk3x/xunlei/tree/v3.20.2>)**

## 特性

- 支持本地运行和容器化运行
- 重构了运行环境，有比较完善的回滚流程。
- 容器镜像基于busybox，不再内嵌SPK，改成从远程下载，大幅减小了镜像体积(50M->5M)。
- 不再内嵌SPK，不在受镜像包的luncher限制，理论上随时可以使用任何指定的版本。

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

本 fork 已发布镜像（阿里云容器镜像服务，国内拉取更快），内置**迅雷引擎 v3.23.5**（xunlei-pan-cli 3.23.5）：

```plain
crpi-7g2swy3pv0gxn73h.cn-beijing.personal.cr.aliyuncs.com/galvin/xunlei:3.23.5
```

上游镜像（可作参考）：

```plain
cnk3x/xunlei:beta
ghcr.io/cnk3x/xunlei:beta


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

#### 示例: docker-compose

```yaml
services:
  xunlei:
    container_name: xunlei
    image: cnk3x/xunlei:beta
    restart: unless-stopped

    # 宿主机名，迅雷远程控制的名称与此相关，会显示 `群晖-r66s`
    hostname: r66s

    # 必须, cap_add: [SYS_ADMIN] 和 privileged: true 二选一
    cap_add: [SYS_ADMIN]

    # 面板访问端口，如需更改访问端口到5432，替换前面的2345为5432即可
    ports: [2345:2345/tcp]
    network_mode: bridge
    # 可以通过环境变量 XL_DASHBOARD_PORT=5432 来更改内部端口, 不过bridge网络模式没有必要更改默认端口
    # 如果设置 network_mode: host, 将忽略上面的端口映射配置(ports), 但可以通过环境变量 XL_DASHBOARD_PORT=5432 来更改端口
    # network_mode: host

    environment:
      ##如果需要指定多个下载目录，手动指定XL_DIR_DOWNLOAD
      ##多个以冒号`:`隔开，都必须以 /xunlei 开头，迅雷面板选择保存路径显示会去掉/xunlei前缀
      ##指定后可以在 volumes 中绑定宿主机实际目录
      ##迅雷云盘的缓存会使用第一个目录会缓存
      ##/xunlei/后面可以用中文
      ##不设置默认一个目录 /xunlei/downloads
      #- XL_DIR_DOWNLOAD=/xunlei/下载:/xunlei/影音:/xunlei/大人

      # 设置用户身份，请确保该用户对 XL_DIR_DOWNLOAD 指定的目录或者默认的 /xunlei/downloads 有读写权限
      - XL_UID=1000 # 用户ID
      - XL_GID=1000 # 用户组ID
    volumes:
      ## 二选一必须，对应 XL_DIR_DOWNLOAD 指定的目录, 请替换冒号前面的路径为实际路径
      #- /vol1/1000/下载:/xunlei/下载
      #- /vol1/1000/影音/下载:/xunlei/影音
      #- /vol1/1000/大人/下载:/xunlei/大人

      ## 二选一必须，如果没有通过 XL_DIR_DOWNLOAD 指定下载目录，请将下面这行代码替换为上面代码
      - /vol1/1000/下载:/xunlei/downloads

      # 必须，数据目录，迅雷运行时，插件，升级，包括登录数据都在这
      - ./data:/xunlei/data

      # 可选，首次初始化，会从远程下载迅雷套件到此处，如果不配置每次重新创建都会重新从远程下载
      - ./cache:/xunlei/var/packages/pan-xunlei-com
```
