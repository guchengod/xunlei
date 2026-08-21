"""dm —— 磁力搜索与多下载器调度包 (Design-Pattern driven).

技能内目录结构:
  magnetdm.py            命令行入口 (search / best / pick / add / get / status)
  dm/config.py           配置加载 (TOML, 内置默认值, 环境变量覆盖)
  dm/models.py           数据模型 (SearchResult / DownloadReceipt)
  dm/session.py          统一 HTTP 会话 (代理 / 超时 / 重试)
  dm/engines/            搜索引擎: 工厂+注册表+模板方法
  dm/selection.py        候选挑选: 加权评分算法 + 可配置规则
  dm/downloaders/        下载器: 策略模式 + 责任链回退 (迅雷 / qBittorrent)

设计模式:
  - Strategy    : XunleiDownloader / QBittorrentDownloader 实现同一 Downloader 协议
  - Chain of Resp: DownloaderChain 依次尝试首选->次选下载器 (案例3/4)
  - Factory+Registry: 引擎按名字注册/构建 (dm.engines)
  - Template Method: BaseEngine 固化 会话/代理/错误吞没, 子类只实现 _search
  - DTO         : SearchResult / DownloadReceipt 纯数据对象
"""
