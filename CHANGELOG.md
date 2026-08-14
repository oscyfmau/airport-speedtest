# 变更记录

本文件记录机场测速工具的版本变更，只陈述事实：新增了什么、修改了什么、修复了什么、移除了什么，以及涉及的参数、阈值、字段名等具体数值。不含评价性描述。

- v3.9 之前没有变更记录。
- v3.9 章节描述的是 v4.0 改造开始时的存量功能（基线）。
- v4.0 至 v4.5 的记录依据各版本实现过程中的实际改动整理。

---

## v4.8

### 新增
- 日志独立目录 `log/`（常量 `LOG_DIR`）；文件日志改为 **JSONL**：`log/测速日志_YYYYMMDD_HHMMSS.jsonl`，每行一个 JSON 对象 `{"ts","level","event","msg","data"}`；`JsonlFileHandler` 逐条 flush（强杀/关窗口不丢已写内容）
- `new_run_log()`：每次测试运行新建独立 JSONL 文件（修复菜单多次运行混写同一文件的时间线混乱）
- 结构化事件系统 `_ev(event, data)`（logger extra，控制台忽略、JSONL 记录），事件清单：
  - 运行级：`run_start`（版本/Python 版本/平台/argv/模式/workers/fast/依赖版本）、`run_end`（耗时/节点数/产物路径）、`run_exception`、`uncaught_exception`（全局 `sys.excepthook` + main 兜底，完整 traceback）、`user_interrupt`（含中断阶段）
  - 解析：`parse_done`（节点总数、按类型计数）、`fetch_fallback`（cloudscraper 回退 requests 的原因）
  - TCP：`tcp_ping`（每节点结果）、`tcp_probe`（每候选可达性）
  - 测速：`switch_node`、`yt_source_resolve`（直连/节点隧道/失败）、`yt_source_attempt`（每视频每次尝试）、`speed_conn`（每连接源域名/HTTP状态/字节）、`speed_conn_error`、`speed_abort_slow`、`speed_done`（延迟/平均/峰值/error）
  - 流媒体：`streaming_done`（每节点解锁数）、`streaming_result`（每节点每平台明细）
  - IP：`ip_done`（ip/风险分/类型/ASN/源）、`ip_source_attempt`（每个源每次尝试与失败原因）
  - 其他：`retest_speed`、`retest_done`、`mihomo_start`、`mihomo_stop`、`worker_pool_start`、`mihomo_update`、`menu_choice`、`invalid_input`、`manual_subscribe_input`
- `_pkg_version(name)`：importlib.metadata 读依赖版本；`_log_streaming_details`/`_log_ip_details`：串行与并行池两条路径共用
- 中断提示明确化：中断时提示中断阶段并注明本次为不完整结果

### 修改
- requirements.txt 最低版本提升（防 Python 3.12 缺 cp312 wheel 触发源码编译失败）：`aiohttp>=3.9.5`、`PyYAML>=6.0.1`、`Pillow>=10.1.0`、`tqdm>=4.66.1`、`cloudscraper>=1.2.71`
- run.bat：`where python` 找不到时回退 `py -3` 启动器；依赖安装改 `py -m pip`
- `_try_fetch`：cloudscraper 回退 requests 时记录 `fetch_fallback` 事件

### 修复
- 标准测试（菜单2）流媒体路径核查确认无功能 bug（菜单2 → normal → full + 9 常用流媒体 + IP；`check_one_node_streaming(services=None)` 兜底 FULL 34 平台）；此前"没测到流媒体"系测试中途 Ctrl+C 中断导致（中断前的 JSON 流媒体为空），现由 `user_interrupt` 事件明确记录

### 移除
- 旧文本文件日志（`output/测速日志_*.log`），由 `log/*.jsonl` 取代

---

## v4.7

### 新增
- 油管测速源：`resolve_youtube_download_url(timeout, proxy)` 经 yt-dlp 解析 googlevideo 直链（签名解密/PO token）；视频 ID 回退列表 `YOUTUBE_VIDEO_IDS`（`LXb3EKWsInQ`/`aqz-KE-bpKQ`/`9bZkp7q19f0`）；格式优先级 `137/136/22/18/best`；总耗时上限 30 秒；结果缓存 `_YOUTUBE_DL_URL`
- `_YtDlpNullLogger`：静默 yt-dlp 输出（直连失败属预期，由本模块 logger 记录）
- 可选依赖 `HAS_YTDLP`（同 `HAS_CLOUDSCRAPER` 模式）；requirements.txt 增加 `yt-dlp>=2025.1.1`

### 修改
- `test_node_speed` 源列表：`SPEED_TEST_URLS` + 油管直链（解析成功时），4 连接每源 1 路；每连接新增 DEBUG 日志 `测速 connN 源=<域名> 状态=<HTTP码> 下载=<字节>`
- `run_test` 阶段2 前解析油管源：先本机直连（timeout=10），失败则切换首个可达节点经其隧道再试；仍失败 WARNING 并回退 3 个基础源
- 实测（2026-08-15）：本机直连 player API 触发 YouTube 机器人检测（"Sign in to confirm you're not a bot"），经节点隧道解析成功（`rr3---sn-ogueln67.googlevideo.com`）；3 节点抽查每节点 4 源全部参与下载（speed.cloudflare.com/cachefly.cachefly.net/proof.ovh.net/googlevideo 各 1 路）

### 修复
- （无）

### 移除
- （无）

---

## v4.6

### 新增
- `_flag_to_text(s)`：控制台显示用节点名转换——国旗 emoji 对（U+1F1E6–U+1F1FF）转为 `[国家代码]`（🇯🇵→`[JP]`），其余 astral-plane 字符（ord>0xFFFF）删除；无国旗的字符串原样返回
- `_ConsoleFormatter`：logging.Formatter 子类，`format()` 对整行套用 `_flag_to_text`，仅用作控制台 StreamHandler 的 Formatter；文件日志用普通 Formatter，保留原始节点名（国旗 emoji）
- `_pbar_ticker(pbar, stop_event)`：每秒调用一次 `pbar.refresh()` 的 asyncio 任务

### 修改
- 6 处 tqdm 进度条（TCP Ping/TCP探测/HTTP测速/解锁检测/IP检测/节点测试）统一加 `mininterval=1.0`
- `run_speed_test`/`run_streaming_test`/`run_ip_quality_test` 三个串行阶段循环改为：节点开始时立即显示"节点名 测速中/检测中..."，结束时 `set_postfix_str(结果, refresh=False)` 后 `update(1)`；循环内启动 `_pbar_ticker`，finally 中取消并回收
- 全部 `set_postfix_str` 调用点的节点名经 `_flag_to_text` 转换；节点原名（dict key/`switch_proxy`/PNG 报告/JSON/文件日志）不变
- `run_tcp_ping`/`run_tcp_probe_pool` 的结果 postfix 改为 `refresh=False` + `update(1)`

### 修复
- 同一节点结果在进度条两个相邻计数重复出现（原因：`set_postfix_str` 默认 refresh=True 先渲染一帧、`update(1)` 再渲染一帧，计数与 postfix 错位一帧）
- 节点名国旗 emoji 在 cmd 控制台无法渲染（乱码/方框）
- 进度条仅节点边界刷新（HTTP测速每节点 10-26 秒才有一次显示）；现串行阶段每秒刷新一次

### 移除
- （无）

---

## v4.5

### 新增
- `_cleanup_stale_configs()`：启动时清理历史运行（异常退出）残留的临时配置文件（`mihomo_*.yaml`、`mihomo_worker_*.yaml`）
- `_wait_auto_selected(api_port, name, timeout, interval, request_timeout)`：轮询 mihomo API 校验 Auto 组选中节点，供引擎与 worker 共用
- `_parse_uuid_password(uri, type_name, allow_insecure)`：tuic/juicity 解析共用实现

### 修改
- `parse_tuic`/`parse_juicity` 改为调用 `_parse_uuid_password`（参数行为不变：tuic 支持 insecure，juicity 不支持）
- `switch_proxy` 与 `MihomoWorker._verify_node` 的校验轮询改为调用 `_wait_auto_selected`（逻辑不变）

### 修复
- cloudscraper session 未关闭：`_try_fetch` 与 `parse_subscription_url` 的 cloudscraper 回退路径在 finally 中调用 `scraper.close()`

---

## v4.4

### 新增
- 日志系统：`logging` 模块双输出——控制台 INFO（格式 `时间 级别 消息`）+ 文件 DEBUG（`output/测速日志_YYYYMMDD_HHMMSS.log`，UTF-8）；`setup_logging()` 在 `main()` 入口调用；模块级 `logger = logging.getLogger("speed_test")`
- 日志事件点：订阅解析（URL 遮蔽后记录）、每节点测速结果（延迟/平均/峰值/error）、每节点流媒体解锁数（DEBUG）、每节点 IP 检测结果（DEBUG）、阶段标题、mihomo 启停、异常堆栈（`logger.exception`）
- `_mask_url(url)`：打印/记录订阅 URL 时将 `token`/`password`/`passwd`/`key`/`secret`/`auth` 参数值替换为 `***`
- `_open_report(path)`：封装 `os.startfile`，异常时记录日志返回 False（不崩溃）
- `CHANGELOG.md`：本文件
- `MIHOMO_SUPPORTED_TYPES` 白名单：`{"ss","ssr","vmess","vless","trojan","hysteria","hysteria2","tuic","anytls","wireguard","socks5","http","ssh"}`（用 mihomo v1.19.29 的 `-t` 参数逐类型实测得出）
- `parse_subscription_urls(urls)`：解析多个订阅 URL 并合并节点，跨订阅同名去重（`_dedupe_nodes` 从 `parse_subscription_content` 抽出）
- 多订阅 URL 支持：菜单读入 `代理.txt` 全部 URL；`-i file.txt` 读取文件内全部 URL；`run_test` 的 `subscribe_url` 参数接受字符串或列表
- ssr 解析：`group` 参数（base64 解码后）作为节点名
- vless 解析：reality 节点的 `pbk`/`sid`/`spx` 查询参数映射为 `reality-opts`（`public-key`/`short-id`/`spiderX`）
- hysteria2 解析：`obfs`/`obfs-password` 查询参数映射为 `obfs`/`obfs-password`
- 菜单选项 5（查看上次结果）：会话内结果不存在时回退扫描 `output/` 目录最新 PNG
- `_no_verify_ssl()`：构建跳过证书校验的 SSL 上下文，替换 5 处重复代码
- `_finish_partial()`：合并两段相同的"提前结束生成报告"路径
- `export_results_json`/`generate_report_image` 新增 `display_mode` 参数：文件名与报告头使用原始模式名

### 修改
- 约 70 处 `print()` 改为 `logger.info/warning/error/debug`；交互菜单提示与 `input()` 上下文保留 `print`；tqdm 进度条不变
- `_download_mihomo()` 增加 `target_dir` 参数（默认 `MIHOMO_DIR`）
- 菜单选项 6（更新内核）：先下载到临时目录，成功后删除旧 `bin/` 并移入新内核；失败保留旧内核
- 订阅 URL 打印：由 `[:60]` 截断改为 `_mask_url` 遮蔽后完整输出
- `--workers` 参数：支持 `--workers=N` 形式；参数缺失或非法时记录 WARNING 并使用默认值 4
- `parse_subscription_url` 的 UA 循环：每个 UA 拉取/解析失败原因记录 WARNING（原静默）
- YAML 订阅解析：逐条 proxy 转换，单条坏条目跳过并记 WARNING（原整份放弃）
- IP 源回退链：每个源失败原因记录 DEBUG
- worker 热重载失败重启：记录 WARNING
- `MihomoEngine.start()`：已有进程但未就绪时不再直接返回，走完整启动流程（原 `if self.process: return`）
- full 模式报告列：渲染本次实际测过的全部流媒体列（原硬编码 4 列）
- 列宽估算：遍历全部结果行（原只取前 60 行）
- `_get_speed_color`：删除 `u==l` 恒假分支
- 测速流水线（`_run_node_pipeline`）：节点任务元组由 4 元素改为 3 元素，移除恒为 False 的 `do_speed` 元素及其分支

### 修复
- B1：`shadowtls`/`naive`/`juicity` 类型节点在 `_is_valid_node` 中被过滤（mihomo 不支持，原会导致整份配置加载失败、整轮测速跳过）；wireguard 缺少 `public-key` 的节点同样过滤
- B2：YAML 单条坏条目（port 为 null、条目非字典）不再拖垮整份 YAML 解析
- B3/B4：ss（SIP002 两种分支）与 ssr 的 IPv6 服务器地址剥离方括号（原保留 `[]` 导致连接失败）
- B5：`streaming_ai`/`streaming_all` 模式名保留到输出文件名、PNG 页眉、JSON `mode` 字段（原被覆盖为 `streaming`）
- B7：ss 明文 userinfo 回退逻辑按 `method:password` 拆分（原将整串当作密码）
- B8：ssr 节点名改用 `group` 参数（原为服务器地址）
- zip-slip：mihomo 压缩包解压前校验成员路径不越出目标目录
- 订阅 URL 的 token 前缀泄漏：改用 `_mask_url` 遮蔽
- `os.startfile` 无异常保护：`--report` 与菜单 5 改用 `_open_report`

### 移除
- `parse_subscription_url` 中未使用的局部变量 `best_ua`
- 补测阶段的 `active_speed += to_test`（追加后无读取）
- `_run_node_pipeline` 的 `do_speed` 分支与元组元素（测速恒串行，不经过流水线）
- `_get_speed_color` 的 `if u==l: return cl` 分支（阈值两两不同，恒假）

---

## v4.3

### 新增
- 报告"UDP类型"列：按节点传输层显示 `QUIC`（hysteria/hysteria2/tuic/juicity 或 vless quic）、`UDP`（wireguard）、`KCP`（kcp 传输层）、`TCP`（其余）；JSON 导出增加 `udp_type` 字段
- `README.md`：使用说明、报告术语解释（超时/代理可达/HTTP 状态码/解锁/仅自制剧/封锁/跳过(节点不可达)/速度过低/下载失败/IP 风险分与共享级别）、JSON 字段说明、常见问题、已知限制
- `COMMON_STREAMING_SERVICES`：9 个平台（youtube/netflix/disney/bilibili/bilibili_tw/chatgpt/tiktok/primevideo/max），从 FULL 列表按 id 构建
- `check_bilibili_tw` 检测器：用 TW-only 番剧 playurl API 判定港澳台解锁；`BILI_TW_EP_IDS = [268176, 268177, 268178, 268173]`（2026-08 实测校准：台湾节点可播，新加坡节点返回 -10403）
- FULL 流媒体列表增加 `bilibili_tw`（33 → 34 个平台）

### 修改
- `DEFAULT_WORKERS` 由 1 改为 4：流媒体/IP 阶段默认 4 路并行（测速阶段保持串行，不受影响）
- 补测超时节点阶段位置：由流媒体/IP 之后移到测速完成之后立即执行
- 菜单 2（标准测试）流媒体集合：由 SIMPLE（4 个）改为 COMMON（9 个）
- `--workers` 帮助文案与 CLAUDE.md 说明同步

---

## v4.2

### 新增
- `is_udp_node(node)`：判定 UDP 传输节点（协议类型或 kcp/quic 传输层），替换 5 处 `node.type in UDP_TYPES`
- 柱状图配色 `_bar_color(sp)`：按绝对速度分级，0→红 (221,51,51)、0.5MB/s→橙红 (221,102,51)、4MB/s→黄 (221,187,0)、16MB/s→黄绿 (119,170,34)、32MB/s+→深绿 (34,170,34)，阈值间线性插值
- 报告前补测超时节点：直连 TCP 重试 + 隧道探测重试，恢复的节点补跑测速

### 修改
- `UDP_TYPES` 增加 `wireguard`
- 柱状图高度：由全表最大值归一化改为行内相对归一化（每行满高 = 该行自身最大秒速），最低 3px
- 柱状图绘制：两遍绘制（第一遍浅灰底立柱子，第二遍按速度上色）；删除全表 darken 与顶部白色高亮
- 可达统计：汇总输出由固定变量改为从最终结果重新计算（补测后仍准确）

---

## v4.1

### 新增
- TCP 检测双来源：来源A=本机直连 TCP 握手（并发 40，重试 2 次，间隔 0.3s）；来源B=经 mihomo 隧道并发探测（`run_tcp_probe_pool`，并发上限 4，直连失败节点与 UDP 节点兜底互验）；可达=任一来源成功
- `TestResult.tcp_probe` 字段；报告 ping 列显示 `代理可达`；JSON 导出 `tcp_probe`
- 单节点多连接下载：`DOWNLOAD_CONNS = 4` 路并发连接轮流取 `SPEED_TEST_URLS`（3 个源）
- 慢节点提前终止：窗口内前 3 秒累计下载 < 64KB（`SLOW_ABORT_BYTES`）判定"速度过低"
- 串行 `switch_proxy` 切换后校验：轮询 `GET /proxies/Auto` 确认 `now == 节点名`（10 次 × 0.2s），失败重试一次
- 流媒体死节点早期终止：先测前 3 个服务，全为连接错误则其余服务标"跳过(节点不可达)"
- IP 质量多源回退：ipapi.is 主源 + ipwho.is + api.ip.sb；无风控字段的源不编造风险值
- `--fast` 参数：测速窗口 5s 且跳过 IP 检测

### 修改
- 测速阶段恒串行（单节点单时刻），与 `--workers` 解耦
- 平均速度计算：排除首秒槽（TCP 慢启动剥离），窗口 ≥2s 时按 `(总量-首槽)/(窗口-1s)` 折算
- `DEFAULT_WORKERS` 由 4 改为 1（当时流媒体/IP 默认串行）
- `STREAMING_TEST_TIMEOUT` 由 12s 改为 10s；HTTP 延迟探测超时由 10s 改为 5s
- `check_netflix` 连接异常返回"错误(连接失败)"（与其它检测器语义一致）
- `check_generic` 403 判定关键词删除 `root`/`app`
- 流媒体错误重试：异常条目与"错误"前缀结果重试一次

---

## v4.0

### 新增
- mihomo 并行工作池：`MihomoWorker`（单节点配置热重载 `PUT /configs?force=true`，JSON body `{path, payload}`）+ `MihomoWorkerPool`（N 路并行，池失败回退串行）
- `--workers` 参数（1-8）；`--fast` 参数
- 测速下载多源：`SPEED_TEST_URLS = [Cloudflare 20MB, CacheFly 100MB, OVH 100MB]`
- 5 个流媒体专用检测器：check_tiktok / check_spotify / check_steam / check_primevideo / check_max
- IP 质量多源（初版）：ipapi.is + ipwho.is + api.ip.sb
- JSON 导出 `udp_node` 字段
- 报告页脚 UDP 节点统计

### 修改
- 测速计时：从首字节起计（原从请求发出起计，含连接握手时间）
- 测速窗口边界：8 秒后的字节不再计入末槽
- 末槽折算：不足 1 秒的末槽按实际时长折算（后续 v4.2 加 0.25s 下限）
- `MIN_SPEED_BYTES = 256 * 1024`：低于此值不记速度
- TCP Ping 重试：2 次尝试（2s/3s），并发 30 → 40
- 报告列：ping 列对 UDP 节点显示 `UDP`（原显示"超时"）

### 修复
- UDP/QUIC 协议节点（hysteria/hysteria2/tuic/juicity）被 TCP 握手误判为不可达：跳过直连 TCP Ping，强制纳入测速队列
- >300 节点时页脚被顶出画布：绘制循环截断到 `nh` 行
- 并行池部分启动失败时泄漏 worker 进程：worker 先登记后启动
- 快速节点峰值被压平：末槽折算修复
- Ctrl+C（asyncio CancelledError）中断后生成部分报告
- 早退路径补 JSON 导出

---

## v3.9（基线）

v4.0 改造开始时的存量功能，描述如下：

- 单文件 `core/speed_test.py` 承载全部逻辑；`core/config.py`、`core/models.py`、`core/parser.py`、`core/engine.py`、`core/tester.py`、`core/image.py` 为重导出薄模块
- 订阅解析：20 种协议 URI（vmess/vless/trojan/ss/ssr/hysteria/hysteria2/tuic/anytls/wg/wireguard/naive/naiveproxy/shadowtls/juicity/ssh/socks4/socks5/http/https）；base64 自动识别；Clash YAML 支持；多 UA（curl/ClashMeta/v2rayN/浏览器）取节点最多的一次
- TCP Ping：并发 30，无重试
- mihomo 单实例引擎：临时配置文件 + `switch_proxy`（PUT /proxies/Auto）
- HTTP 测速：gstatic 204 延迟 + Cloudflare 20MB 单源下载，8 秒窗口
- 流媒体：FULL 33 个平台，5 个专用检测器（youtube/netflix/disney/chatgpt/bilibili）
- IP 质量：ipapi.is 单源
- 报告：PNG（StairSpeedTest 风格配色）+ JSON
- 交互菜单 7 项；`--full`/`--report`/`--menu`/`-i`/`-h` 参数
- 已知限制（当时）：UDP 类型列恒为 `--`；IP 质量无备用源；UDP 协议节点被误判超时
