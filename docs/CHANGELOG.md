# 变更记录

本文件记录机场测速工具的版本变更，只陈述事实：新增了什么、修改了什么、修复了什么、移除了什么，以及涉及的参数、阈值、字段名等具体数值。不含评价性描述。

- v3.9 之前没有变更记录。
- v3.9 章节描述的是 v4.0 改造开始时的存量功能（基线）。
- v4.0 至 v4.5 的记录依据各版本实现过程中的实际改动整理。

---

## v4.31.0

### 新增
- **订阅分组对比菜单**（二级3，`profiles.subscription_group_report`）：按节点 `sub_index` 分组横评（节点数/平均速度/最高速度/解锁率/平均延迟/风险均值）；解锁率口径=实际检测服务中"解锁/可用"计数÷检测数（排除"跳过/错误"，坏节点不稀释）；数据源=所选 run 原始 JSON（缺省最近一次，可输编号选历史）；旧数据无 sub_index 字段显示"未知"并提示只有 1 个订阅
- **sub_index 打标**：`parser.parse_subscription_urls` 按订阅顺序给节点赋 sub_index（0=第一份）；单 URL 路径 runner 打 0；结果 JSON 每节点带 sub_index、档案证据带出
- **产物累积清理**（`profiles.cleanup_outputs`）：output/ 保留最近 keep_reports 份 PNG+JSON 配对（10/30/100 默认 30）、log/ 保留最近 keep_logs_days 天（7-365 默认 30）；护栏（只匹配 测速结果_*/测速日志_* 前缀、成对删、profiles.json 永不参与、单文件异常跳过）；自动清理在 run_test 与 _finish_partial 收尾静默执行（事件 `profiles_cleanup`）；维护页 3 手动清理（先 dry_run 统计占用与将删数再确认执行）
- **设置项**：keep_reports（10/30/100 默认 30）、keep_logs_days（7-365 默认 30）；config 常量 KEEP_REPORTS_DEFAULT/KEEP_LOGS_DAYS_DEFAULT

### 修改
- 设置菜单加 7=保留报告份数、8=日志保留天数
- 二级 3 与维护 3 由占位激活

### 修复
- （无）

### 移除
- （无）

## v4.30.0

### 新增
- **快速检测 quick 模式**（菜单一级5 / `--quick`）：TCP 直连 1 次重试 2s 超时（`run_tcp_ping` 加 attempts/timeouts 参数，默认值不变）、无隧道探测；死节点独立规则（非 UDP 直连失败即标"节点不可达"并预填 4 流媒体跳过；UDP 节点不判死进流水线实测，与 v4.28 dead 规则互不干扰）；并行 `QUICK_WORKERS=4` 一条龙（MihomoWorkerPool：load_node → `tester.test_node_quick`（单连接单源 `QUICK_DOWNLOAD_URL` 5MB、窗口上限 `QUICK_WINDOW=5`s）+ `check_one_node_streaming(QUICK_STREAMING)` 4 核心平台 youtube/netflix/disney/chatgpt），池失败回退串行（`_run_quick_serial`，主引擎 switch_proxy）；跳过 IP 质量/网页模拟/补测/油管源/慢速中止
- **quick 报告与档案口径**：报告 quick 列布局（4 流媒体列 + 平均/最高速度，不画 speed_bar 防并行数据误导）、页脚注明"快速模式（并行近似测速）"、页眉"快速检测"；档案 quality=quick、加权统计权重 ×0.5
- **结果对比菜单**（二级2，`profiles.run_compare_report`）：最近 15 次 run 选两个横比，节点对齐（name→剥后缀→(type,server,port) 三级），输出速度/延迟/解锁/组内排名差分，变化>20% 标 ↑↓；原始 JSON 缺失降级档案 evidence（无排名数据）；`_is_peak_hour`（18-23 点或周末）标注晚高峰，两轮恰一高峰时提示时段因素

### 修改
- `engine.run_tcp_ping` 加 attempts/timeouts 参数（默认 3/(2.0,3.0,3.0) 不变；丢包显示改按 attempts 计算）
- `_MODE_NAMES` 加 quick；CLI help 加 --quick 行

### 修复
- （无）

### 移除
- （无）

## v4.29.0

### 新增
- **节点档案库 `core/profiles.py`**：output/profiles.json（version=1）跨 run 记录节点身份与证据——runs 索引保留 50 条（RUNS_MAX）、每档案证据 10 条（EVIDENCE_MAX）更早折叠进 fold（n/speed_sum/speed_ss/reach_n/unlock_sum，按最老时间戳计权重）、appear 列表 20 条算近 N 次出现率；身份识别四级（name 精确 → 剥 `_N` 去重后缀 → `(type,server,port)` → 本轮桥接：同 server:port 同落地 IP 并入，跨 run 不做）；质量标记 standard/quick/streaming，加权统计 `w=0.5^(年龄/3)`、quick 证据 ×0.5；损坏/版本不符自动重建（扫描 output/测速结果_*.json 重放，2-5 秒级）；run 收尾 `run_test` 与 `_finish_partial` 各调 `append_run`（互斥不重复，异常 WARNING 静默降级）；事件 `profiles_written`/`profiles_rebuild`
- **节点稳定性菜单**（二级 1）：常青树/过山车/新面孔/普通分层（新面孔=证据<3；常青树=出现率≥0.8 且 σ/均值<0.3；过山车=出现率≥0.8 且 σ/均值≥0.3，STABILITY_APPEAR_RATIO/STABILITY_SIGMA），显示近 N 次出现率/可达率/平均速度±波动，默认平均速度降序、r 切换可达率降序；history 不足 2 次提示而非报错
- **菜单三级重构**：一级（1 标准测试/2 下载速度/3 AI 网站/4 所有流媒体/5 快速检测占位/6 更多/0 退出）→ 二级「更多」（1 节点稳定性/2 结果对比占位/3 订阅分组对比占位/4 节点筛选测速/5 查看上次结果/6 结果管理/7 订阅管理/8 设置/9 维护/0 返回）→ 三级「维护」（1 更新内核/2 环境信息/3 清理占位/0 返回）；旧 13 项全部映射保留，`--fast` 仅 CLI；Ctrl+C 一级两次退出、二/三级一次返回上级；`menu_choice` 事件加 level
- **测前流量预估**：测速类模式打印 `预计下载约 X-X GB（N 节点）`（节点数×10~30MB）；>50 节点需回车确认（settings.confirm_large_run 可关）
- **报告文件名毫秒级共享时间戳**：`report._new_report_timestamp()`（同秒冲突加毫秒后缀，与 new_run_log 同策略），PNG/JSON 共用同一值（generate_report_image/export_results_json 加 report_ts 参数）
- **PNG 页脚流量显示**：ftr3 追加 `本次实测下载 X`（state._RUN_BYTES，mode!=streaming）；JSON 顶层加 run_bytes
- **设置项**：stability_window（5/10/20 默认 10）、confirm_large_run（bool 默认开）
- **models.ProxyNode.sub_index 字段**（Optional[int]，本版仅透传，v4.31 分组对比使用）

### 修改
- cli.py 菜单分发重构：测速入口合并 `_menu_run_flow`（订阅收集/排序选择/run_test/自动开报告），排序选择 `_menu_choose_sort`，旧 5/6/9/10/11/12/13 动作分别收进 `_menu_view_last/_menu_update_kernel/_menu_filtered_run/_menu_manage_results/_menu_manage_subs/_menu_settings/_menu_env_info`
- runner.py `_finish_partial`/run_test 收尾统一生成 report_ts 并传给 PNG/JSON 导出

### 修复
- **PNG/JSON 文件名跨秒配对竞态**：旧实现两个导出函数各自取秒级时间戳，恰跨秒时同名不同时 → 配对断裂；共享时间戳修复

### 移除
- 菜单 8 快速测速不再单列（CLI `--fast` 保留原语义）

## v4.28.0

### 修复
- **本机代理开/关影响工具数据（核心）**：订阅拉取回退（`parser._try_fetch` 的 requests 分支）、末次 cloudscraper 兜底、userinfo 重拉（`_fetch_sub_usage`）、mihomo 内核下载与版本查询（`engine._get_latest_tag`/`_download_mihomo`）未显式指定代理——requests 会读环境变量与 Windows 注册表系统代理，本机代理开启（指向失效端口 127.0.0.1:7897）时这些请求全部失败，导致解析不到节点/内核不可用 → 全部传 `utils.DIRECT_PROXIES`（`{"http": "", "https": ""}` 空串值=该协议不走代理，环境与注册表代理均被屏蔽）
- **yt-dlp 油管直链解析受环境代理影响**：proxy 为空时 yt-dlp 尊重环境代理变量 → 恒显式出口（直连传 `proxy=""`，节点隧道传 mihomo 地址）
- **切换失败节点不记录原因**：`run_speed_test`/`run_streaming_test`/`run_ip_quality_test`/`run_webpage_test` 4 处 switch 失败仅控制台打印，error 字段留空 → 记 `error="切换失败"`（首个失败原因优先，不覆盖已有 error）

### 新增
- **死节点如实标注并跳过检测**：补测后仍直连与隧道均不通的节点（`tcp_ping is None` 且 `tcp_probe is not True`；`tcp_probe=None` 探测池不可用不算死，streaming-only 模式不参与）→ `error="节点不可达"`、流媒体预填 `跳过(节点不可达)`、`ip_info`/`webpage` 预填 error，阶段4 不再对这些节点做检测（不浪费 IP 源配额），结构化事件 `dead_nodes_skipped`
- **系统代理状态提示**：`utils._system_proxy_info()` 读注册表（win32），开启时 `run_test` 启动阶段打印提示（内部请求已强制直连；TUN 模式会接管直连 TCP 属例外）
- **报告速度列显示失败原因**：`report._ctxt` speed 单元格无速度数据且存在 error 时显示 error 文本（`_trunc_width` 截断 10 宽），死节点显示"节点不可达"、失败节点显示"下载失败/速度过低/切换失败"

### 修改
- `parser._try_fetch` 主路径 cloudscraper 的 proxies 改用共享常量 `DIRECT_PROXIES`（行为不变，口径统一）
- `resolve_youtube_download_url` docstring 更新为恒显式出口语义

### 移除
- （无）

## v4.27.0

### 修复
- **runner.py 可达性判定恒真（P1，影响测速结果正确性）**：`tcp_results` 值为 `(latency, ok)` 元组恒非 None——旧判断 `is None` 使"来源B 隧道探测"candidates 恒空（直连失败节点+UDP 节点从不走隧道互验）、`v is not None` 使所有节点（含直连超时死节点）误判可达并进入 HTTP 测速（每死节点白耗至多 30s）；改为 `(…or (None,0))[0] is None` / `v[0] is not None`（与补测阶段 L430 判定一致）
- **parser.py tuic/juicity/ssh authority 段密码被丢弃（P1）**：`_parse_uuid_password`/`parse_ssh` 用 `_` 接住 `parsed`，`tuic://uuid:密码@host`/`ssh://用户:密码@host` 的密码丢失（query `password=` 优先，authority 密码兜底）；对照 parse_socks/parse_http 已正确读取
- **parser.py `_try_fetch` 会话先于流消费关闭（P1）**：finally 里 `scraper.close()` 在 `_read_limited(resp)` 读体之前执行，stream=True 响应可能截断（订阅随机残缺）——会话关闭移到流消费之后；同时补 HTTP 状态码检查（非 2xx 抛错，404/500 错误页不再当正文解析）
- **parser.py 末次 cloudscraper 兜底绕过体积上限（P2）**：`resp.text` 全量读入 → 改 `_read_limited` 流式读取（仍受 `_SUB_MAX_BYTES` 20MB 限制）
- **streaming.py ChatGPT 地区封锁误报解锁（P1）**：`favicon 403 + cdn-cgi/trace 有 loc → 解锁(region)` 会把被封地区误报解锁（trace 的 loc 只是 CF 边缘定位，不代表 OpenAI 放行）——403 一律判"封锁"
- **streaming.py 其余**：netflix 非 200（5xx 瞬时）一律 blocked 不触发重试 → 403/404 才 blocked、其余归"错误"类；bilibili_tw 412 风控 `resp.json()` 抛异常被吞判"失败"（不重试）→ 非 200 归"错误(HTTP x)"触发重试；youtube 非 200 统一"失败(无Premium标识)"掩盖 403 → 暴露真实状态码
- **ip_quality.py 令牌桶死循环（v4.26.0 引入的 while 重取暴露）**：容量 `min(self._rate, …)` 被 cap 在 0.667 <1，令牌永远凑不齐（v4.26.0 无重取时表现为"假节流"）——容量与速率分离（`_capacity = rate_per_min`），并发等待者醒来后循环重取
- **runner.py ip_lock 持锁做网络请求（P2）**：坏节点最坏 4源×2次×10s ≈ 80s 持锁阻塞其余 worker → 锁只保护间隔簿记，网络请求移出锁外（配合令牌桶全局节流）
- **utils.py `_mask_url` 遮蔽旁路（P2）**：`?a=1?token=SECRET` 嵌套 query、`;` 分隔参数、大写 `HTTP://user:pass@` 未遮蔽——嵌套值递归遮蔽、`[&;]` 分割、scheme 正则 IGNORECASE
- **parser.py YAML 解析错误明文进日志（P2）**：`ScannerError` 的 `str(e)` 含出错行上下文（proxies 段 password/uuid 明文）→ 只记异常类型+行列号
- **report.py print_console_summary 无类型守卫（P2）**：`"解锁" in v` 遇 None 抛 TypeError 使小结静默消失 → 加 `isinstance(v, str)`
- **settings.py `bool("false")` 为 True**：字符串 "false"/"0" 手写进配置文件被误判开启自动开报告 → 白名单式解析
- **utils.py b64decode_pad**：`padding != 4` 恒真死判断、多行 base64 失败 → 清理全部空白 + 移除死判断
- **parser.py `_looks_like_yaml`**：只认 `proxies:`/`mixed-port`，`port: 7890` 开头合法 YAML 误判 → 补 port:/socks-port:/allow-lan:/proxy-providers:/mode:
- **cli.py `--workers` 后跟 flag 被吞**：`--workers --full` 中 `--full` 被 skip_next 跳过静默失效 → 参数解析成功才 skip
- **logging_setup.py excepthook 链式叠加**：setup_logging 多次调用重复写异常日志 → 模块级标记只装一次
- **parser.py parse_trojan allowInsecure 只认 "true"** → 与 hysteria2/anytls 统一（true/1/yes）
- **webpage.py 回退结果加 `group` 字段**（intl/cn），区分实际测的站点组

### 修改
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.26.0

### 修改
- **IP 质量：全局节流防免费源 429 降级**：新增 `ip_quality._TokenBucket` 令牌桶（`config.IP_RATE_LIMIT_PER_MIN = 40`），`check_ip_quality` 每个源请求前 `acquire()`——ip-api.com 免费版限 45 请求/分钟/出口 IP，并行路径（--workers>1）多节点同时打主源会触发 429 并降级到无风控字段的回退源（ipwho.is/api.ip.sb），导致报告 IP 类型/风险列显示 "--"；实测 3 节点 normal 全量走通 ip-api.com 主源（source=ip-api.com，proxy/hosting/mobile 字段齐全）
- **网页模拟：国际站点全失败回退国内站点**：`check_one_node_webpage` 国际站点（google/youtube/bing/github）全部失败（落地 CN 但 IP 检测失败、或线路屏蔽国际站）时，自动清空并回退用国内站点（baidu/bilibili/qq）再测一轮，网页均耗列不再空白

### 修复
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.25.0

### 修改
- **柱状图配色变回老前辈（SSRSpeedN v1.04 origin 色表同款）**：`_bar_color` 色板由"红慢绿快 7 档"（0→深红…60MB/s+→深绿，v4.24.0）改为 **origin 7 档**——≤4MB/s→浅绿 (102,255,102)、4-8→黄 (255,255,102)、8-16→橙 (255,178,102)、16-24→红 (255,102,102)、24-32→紫 (226,140,255)、32-40→蓝 (102,204,255)、40MB/s+→深蓝 (102,102,255)，阈值间线性插值（慢=浅绿、快=深蓝，跨行可比）；与 SSRSpeedN v1.04 `ssrspeed_config.example.json` 的 `exportResult.colors.origin` 完全一致（config.SPEED_COLORS 同源）；柱高（行内 min-max 起伏形状）与退化分支（8 根等高矮柱 12px + `_bar_color(平均速度)`）不变

### 修复
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.24.0

### 修改
- **柱状图配色回到绝对速度分档（变回老前辈 SSRSpeedN 的做法）**：主分支颜色由"行内相对 7 档"（v4.23.0 `_bar_color_rel`）改回**绝对速度 7 档**（`_bar_color`：0→深红、0.5→红、2→橙、6→黄、15→黄绿、30→绿、60MB/s+→深绿，阈值间线性插值）——柱高仍为行内 min-max（只管起伏形状，不代表快慢），颜色表达真实快慢（红=慢、绿=快，跨行可比；高柱子也可以配慢色：行内全相等时柱满高、颜色按该绝对速度上色，不再固定中性黄）；`_bar_color_rel` 保留接口（v4.24.0 起未调用）
- **退化分支样式**：无每秒数组节点（仅平均速度）由"满宽单色条"改为 **8 根等高矮柱（12px）**，颜色用 `_bar_color(平均速度)`——视觉上与其他行统一为多根柱子，并以矮柱区分"无每秒数据"节点

### 修复
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.23.0

### 修改
- **柱状图配色改行内相对（参考 SSRSpeedN v1.04）**：颜色由"绝对速度 7 档分级"（v4.22.0）改为**行内 min-max 归一化上色**——新增 `report._bar_color_rel(t)`，柱高与颜色共用同一归一化 `t=(sp-row_min)/(row_mx-row_min)`：行内最慢槽 t=0 → 深红 (178,34,34)、行内最快槽 t=1 → 深绿 (0,128,0)，中间经 红(221,51,51)/橙(221,102,51)/黄(221,187,0)/黄绿(154,180,34)/绿(51,170,51) 等距插值（红=慢、绿=快，颜色跟随柱高起伏；0.5→2MB/s 的低速行内波动从深红变深绿，差异明显）；行内全相等（span==0）柱满高、颜色中性黄 (221,187,0)；分档插值结构经源码考证参考 SSRSpeedN v1.04 origin 色表（`ssrspeed_config.example.json` 的 `exportResult.colors`，与 config.SPEED_COLORS 同源），色系按需求改为红慢绿快；`_bar_color`（绝对速度 7 档）保留接口，仅用于退化分支（无每秒数组时按平均速度上色）

### 修复
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.22.0

### 修改
- **柱状图柱高生成规则**：由"0→行内最大线性归一化 + 最低 3px"（`bh = max(3, int((rh-6)*sp/row_mx))`，行内峰值远大于其余槽时半数柱子撞 3px 下限成平头）改为**行内 min-max 归一化**（`bh = 3 + int((rh-6-3)*(sp-row_min)/(row_mx-row_min))`）：行内最慢槽固定 3px、最快槽满高 20px，**每行必有起伏**；行内全相等（span==0）兜底满高；速度绝对值由颜色表达，柱子只管行内起伏形状
- **柱状图配色 `_bar_color` 分级合理化**：由 5 档（0→红、0.5→橙红、4→黄、16→黄绿、32MB/s+→深绿）改为 **7 档绝对速度分级**——0→深红 (178,34,34)（几乎无速度）、0.5→红 (221,51,51)（很慢）、2→橙 (221,102,51)（慢）、6→黄 (221,187,0)（一般）、15→黄绿 (154,180,34)（较快）、30→绿 (51,170,51)（快）、60MB/s+→深绿 (0,128,0)（很快），阈值间线性插值；函数名与接口不变，`SPEED_COLORS` 历史表保留

### 修复
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.21.0

### 修改
- **柱状图恢复 v4.19.0 绘制方式**（撤销 v4.20.0 的柱状图改动）：两遍绘制恢复为"第一遍浅灰底（柱高 bh）立柱子 + 第二遍按绝对速度上色"，柱体矩形右端恢复含入（`bx+bw`，柱子无间隔连排）；删除浅灰全高轨道与"无数据节点显示 `--` 占位"分支（v4.20.0 引入，实测观感不佳）；退化分支（无每秒数组但平均速度存在时单色条）与行内相对高度、绝对速度配色不变

### 修复
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.20.0

### 修复
- **柱状图相邻柱子连成块**：PIL `rectangle` 端点含入（矩形实际覆盖 `bx..bx+bw` 共 `bw+1` 像素），绘制宽度恰等于间距，1px 间隔被吞，相邻等高校柱合并成扁平色块（慢启动槽全部为最低 3px 时，如本行峰值远高于其余秒槽的极端节点，前 3-5 根柱子连成 24-40px 宽扁平块）；现柱体右端减 1（`bx+bw-1`）恢复 1px 间隔，每秒一柱清晰可辨
- **部分节点柱状图"未生成"观感**：下载失败/超时节点（无每秒速度数据）柱状图单元格完全空白；现显示灰色 `--` 占位，与其他列一致；第一遍"立柱子"改为浅灰全高轨道（每秒槽一条 `(225,225,225)`），极端节点行不再显得柱体缺失

### 修改
- 日志文件策略：`new_run_log()` 不再删除旧日志、不再迁移交互事件（`_migrate_interact_lines` 保留接口未调用），`log/` 保留全部历史文件，每次 bat 运行一个独立文件；`runner.run_test` 不再每次测试新建日志文件（一次 bat 会话内多次测试共用本次会话文件，互不覆盖、互不混写）
- 报告页脚不再追加"流量倍率"（`report.generate_report_image` 移除 `_RATE_INFO` 页脚拼接）

### 移除
- 流量倍率功能彻底停用：`runner` Step 7 不再重拉订阅流量头（`_fetch_sub_usage` 不再调用）、不再计算 `_RATE_INFO`、不再输出控制台"流量倍率"行与 `rate_done` 事件；`state._RATE_INFO`/`_RUN_BYTES`/`_SUB_INFO` 与 `parser._fetch_sub_usage` 保留接口未删

### 新增
- （无）

---

## v4.19.0

### 修复
- **IP 质量主源失效导致类型/风险全显示 `--`**：ipapi.is（原主源）实测屏蔽多数机场出口 IP——经香港/日本/美国节点代理访问全部 `ClientConnectorError: Cannot connect to host api.ipapi.is:443`（直连本机 IP 正常），真实测试因此降级到无风控字段的 ipwho.is，报告"IP类型/IP风险"列显示 `--`；实测 ip-api.com 免费接口（`http://ip-api.com/json/`，fields 限定）经机场出口可用且带 `proxy`/`hosting`/`mobile` 三风控标志
- **IP 类型判定只有机房/家宽两档**：`report._ctxt` 的 `ip_type` 列仅区分"商宽/机房 IP"与"家宽 IP"，代理/Tor/移动出口无法体现；现扩展五档——Tor 出口（is_tor）/ 代理-VPN IP（is_proxy 或 is_vpn）/ 商宽机房 IP（is_datacenter）/ 移动网络 IP（is_mobile）/ 家宽 IP；无风控数据判定改为核心三字段（is_datacenter/is_proxy/is_mobile）全 None → `--`（原仅查 is_datacenter，ip-api.com 源 is_tor/is_vpn 为 None 不影响）
- **报告 IP 类型颜色**：Tor/代理/VPN 红 `#DD3333`、机房橙 `#DD8833`、家宽/移动绿 `#33AA55`（原仅机房橙/其余绿）

### 修改
- `ip_quality.py` 新增 `_ipapi_com_to_info` 映射器（`query`→ip、`countryCode`→country、`city`、`isp`、`as` 正则提取 ASN、`org`、`hosting`→is_datacenter、`proxy`→is_proxy、`mobile`→is_mobile，is_vpn/is_tor/is_abuser/is_crawler 置 None 不编造；风险分与共享级沿用启发式）
- `IP_SOURCES` 顺序调整：ip-api.com（主源，http+fields 限定，限速 45 请求/分钟/出口 IP）→ api.ipapi.is（回退，风控字段最全但屏蔽多数机场出口）→ ipwho.is 加 `?security=1` 参数（实测免费版仍无 security 字段）→ api.ip.sb（最后回退）；429 退避重试与换源逻辑不变

### 新增
- （无）

### 移除
- （无）

---

## v4.18.0

### 修改
- **控制台日志消息列对齐**：`logging_setup.py` 控制台格式 `"%(asctime)s %(levelname)s %(message)s"` → `"%(asctime)s %(levelname)-8s %(message)s"`，级别固定 8 显示宽，INFO/WARNING/ERROR 的消息列从同一列开始
- **解析节点列表对齐**：`runner.py` 节点预览行由 `- 名称 (类型://地址:端口)` 改为两列——名称 `_pad_right(name, 32)`（CJK 按 2 宽计）+ 地址 `{:>38}` 右对齐
- **测试结束汇总标签对齐**：`runner.py` 结尾的 可达/流媒体解锁节点/报告/数据/日志 五行的标签统一 `_pad_right(label, 14)`，冒号与值列对齐
- **菜单 10 结果管理列表对齐**：模式列（简单测速/标准测试/全部流媒体等）`_pad_right(mode, 10)` 固定显示宽，报告文件名列对齐
- **菜单 13 环境信息对齐**：全部标签（工具版本/Python/依赖/cloudscraper/mihomo/订阅/报告文件/日志文件/当前设置）统一 `_pad_right(label, 16)`；"报告/日志" 计数行改名 "报告文件/日志文件" 并入标签列；"当前设置" 行由复用 `_current_settings_line()` 改为内联对齐格式
- **README×2 下载指引 zip 文件名随版本同步**：`airport-speedtest-v4.10.1.zip` → `airport-speedtest-v4.18.0.zip`（v4.18.0 发布配套，4 处：README/README_EN 的下载步骤与免 git 说明）

### 新增
- （无）

### 修复
- （无）

### 移除
- （无）

---

## v4.17.0

### 修复
- **YouTube 送中判定误报（`可用(CN)` 扩散到境外节点）**：新 /premium 页面变体把 Google 广告位地址 `https://www.google.cn/pagead/lvz?...` 嵌入页面 JS 配置（与出口地区无关，2026-08-15 实测 4 个美/日/港节点页面均出现 1 次、同日晚间另一变体 0 次），旧判定 `"www.google.cn" in text` 命中即误判送中；实测上次全量运行 5 个境外节点（美国堪萨斯/日本1/新加坡1/新加坡2/2x专线-新加坡-1）被判 `可用(CN)`。现改为三重送中信号：请求重定向到 google.cn / 页面含非 pagead 的 google.cn 链接（`www.google.cn/(?!pagead)` 或 href 形式）/ 地区码 == CN
- **YouTube 地区提取失效（countryCode 消失 + GL 固定 US）**：新页面变体不再含 `"countryCode":"XX"`（旧正则永不命中），`INNERTUBE_CONTEXT_GL` 与 `ytcfg gl` 固定为 US（不反映出口 IP）；新增 `_extract_yt_region(text)` 优先解码 `visitorData`（base64url + URL 编码 + JSON 转义，protobuf 内嵌 `\x0a\x02<CC>`，来自 Google 对出口 IP 的地理定位），实测 4 节点全部正确（US/JP/HK/CN），回退 countryCode / INNERTUBE_CONTEXT_GL；真实 CN 出口节点（新加坡1|高速下载|移动优化，visitorData=CN）稳定返回 `可用(CN)` 而非误报
- **报告自动打开失败（WinError 1155）**：本机无 .png 默认应用关联时 `os.startfile` 抛 `[WinError 1155] 没有应用程序与此操作的指定文件有关联`，每次运行结束记一条 ERROR 且报告打不开；`cli._open_report` 现捕获 OSError 后回退 `explorer /select,<path>` 打开所在目录并选中报告文件

### 修改
- `check_youtube` 逻辑顺序调整：先提取地区（visitorData 优先）再做送中/区域限制/ad-free 判定；`streaming.py` 新增 `base64`/`urllib.parse.unquote` 模块级导入与 `_extract_yt_region` 辅助函数（加入 `__all__`）

### 新增
- （无）

### 移除
- （无）

---

## v4.16.0

### 修复
- **v4.10.0 模块化回归：串行路径流媒体/IP/网页检测必崩 NameError**：`streaming.py`/`ip_quality.py`/`webpage.py` 使用 `_pbar_ticker` 但未定义也未导入（`from .engine import *` 不透出该符号），设置并行数=1 或并行池启动失败回退串行时，`run_streaming_test`/`run_ip_quality_test`/`run_webpage_test` 抛 `NameError: name '_pbar_ticker' is not defined`；初修加 `from .tester import _pbar_ticker` 引发循环导入（tester↔streaming），最终把 `_pbar_ticker` 定义下沉至零依赖的 `core/utils.py`（tester 经 `from .utils import *` 获得并保留 `__all__` 中的名字维持 `from core.tester import _pbar_ticker` 兼容）；实测串行解锁检测 1 节点 8 平台正常、并行 pipeline 全链路（流媒体→IP→网页）正常
- **菜单 12 设置保存失败导致程序崩溃**：`save_settings` 写 `~/.airport_speedtest.json` 失败（只读/权限/磁盘满）抛 OSError 未被捕获，直接"程序异常退出"；现统一捕获并打印 `[错误] 保存设置失败`，菜单不中断
- **管道输入提前结束被记为异常**：`echo 1 | python core/speed_test.py` 等管道输入耗尽时 `input()` 抛 EOFError，被 main 的兜底记"程序异常退出"（exit 非 0）；现 EOFError 静默正常退出

### 修改
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.15.0

### 新增
- **多条订阅手动选择**：菜单 1/2/3/4/8/9 读取 代理.txt 后，若含多条订阅（>1 条）先列出全部 URL（`_mask_url` 遮蔽显示）并询问选择——逗号分隔多选（如 `1,3`，去重保序）、回车=全部、无效选择回退全部、Ctrl+C 取消回菜单；选择结果记 JSONL 事件 `subscribe_select`（仅遮蔽 URL）；单条订阅保持原流程不变，CLI 直跑不受影响

### 修改
- `_INTERACT_EVENTS` 加入 `subscribe_select`：订阅选择事件与 menu_choice 等一致，在 `new_run_log()` 轮换日志时迁移保留（不被吞掉）

### 修复
- （无）

### 移除
- （无）

---

## v4.14.0

### 修复
- **Netflix 检测误报"错误(连接失败)"**：title 双剧探测（自制剧/非自制剧）异常（连接瞬断/响应头超限）时直接判错误，可达节点被误判；现 title 探测异常时回退首页可达性判定（200 即可用 + 区域从重定向 URL 提取，如 `/hk-en/`→HK、`/tw-en/`→TW），实测香港/台湾节点由"错误(连接失败)"修正为"可用(HK)/可用(TW)"
- **Gemini 等 Google 系误报"错误(连接失败)"**：gemini.google.com 响应头超 aiohttp 默认 8190 字节限制抛 `Header value is too long`；流媒体/IP/网页检测的全部 `ClientSession` 增加 `max_field_size=65536, max_line_size=65536`，实测香港节点由"错误(连接失败)"修正为"可用"
- **`check_generic` 403 误判风险**：原逻辑 403 页面含 `"<html"` 即判"可用"（Cloudflare/JS 挑战页几乎都含，挑战文案变体时会误判可用）；现按序判定——挑战特征（原 6 个 + 新增 verify you are human / checking your browser / enable javascript / cf-turnstile / challenge-platform / recaptcha / hcaptcha / turnstile）→ 封锁；页面 title 含平台名 → 可用；>15KB 且含前端框架特征（__NUXT/react-root/__NEXT_DATA__/id=root）→ 可用；其余 403 一律封锁
- **`check_youtube` 误报"失败(无Premium标识)"**：premium 页返回 200 但无可识别特征（consent/登录墙等变体）时判失败；现 200 无特征 → "可用"，并跟进重定向（allow_redirects=True）

### 修改
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.13.0

### 修改
- **流媒体服务表移除大陆 BiliBili（`bilibili` 条目）**：`STANDARD_STREAMING_SERVICES`、`SIMPLE_STREAMING_SERVICES`、`_COMMON_IDS` 删除该条目，保留 `bilibili_tw`（港澳台，专用检测器 `check_bilibili_tw` 不变）；FULL 34 → 33 个平台，COMMON（菜单2）9 → 8 个（youtube/netflix/disney/bilibili_tw/chatgpt/tiktok/primevideo/max），SIMPLE 4 → 3 个（youtube/netflix/disney）
- `check_bilibili` 函数与 `STREAMING_CHECKERS["bilibili"]` 条目保留（接口不删，无服务引用即不执行）；README×2 平台数同步（菜单2 8 个常用流媒体、菜单4 33 个平台全测、10 个在用专用检测器）

### 修复
- （无）

### 新增
- （无）

### 移除
- （无）

---

## v4.12.0

### 新增
- **菜单 9「节点筛选测速」**：测速前按节点名关键字筛选（空格/逗号分隔=任一匹配，如 `香港 JP`）或只测订阅顺序前 N 个（`N=10`）；选简单/标准/快速模式后沿用现有排序流程；`run_test` 新增 `node_filter`/`node_limit` 参数（解析去重后过滤，`run_start` 事件 data 带 `node_filter`/`node_limit`）
- **菜单 10「结果管理」**：`_list_reports` 列出 output/ 最近 15 份报告（PNG/JSON 按同名前缀配对、时间/模式标注），输入编号打开（优先 PNG）、`D编号` 删除（配对文件一起删）
- **菜单 11「订阅管理」**：遮蔽显示 代理.txt 全部 URL（`_mask_url`，不打印完整 URL），`A`=添加（`_append_subscribe_url` 去重/换行处理）、`D编号`=删除某条、`O`=系统默认程序打开文件编辑；增删记 JSONL 事件（`manual_subscribe_input` 带 added/deleted）
- **菜单 12「设置」+ 新增 `core/settings.py`**：测速窗口秒数（3-30，默认 8）、流媒体/IP/网页并行数（1-8，默认 4）、自动打开报告开关（默认开），恢复默认；持久化到 `~/.airport_speedtest.json`（JSON，进程内缓存 `load_settings`，损坏自动回退默认）；菜单模式运行测试时生效（窗口经 `run_test(window_seconds=)` 传入，非 fast 且 >0 时覆盖默认 8s、钳制 3-30；`--fast` 恒 5s），命令行直跑不受影响
- **菜单 13「环境信息」**：一页显示工具版本 / Python 版本与平台 / 依赖版本（aiohttp/PyYAML/Pillow/tqdm/requests）/ cloudscraper 与 yt-dlp 可用性 / mihomo 版本与路径（`_get_mihomo_version`）/ 订阅条数 / 报告与日志文件数 / 当前设置

### 修改
- `run_test` 签名新增 `node_filter: str = ""`、`node_limit: int = 0`、`window_seconds: int = 0`（默认值保持旧调用完全兼容）
- 菜单 1-4/8 运行测试时套用设置（workers/窗口/自动打开报告）
- 菜单提示与 README×2 菜单表同步更新为 1-13

### 修复
- **日志写入遇非法 surrogate 崩溃**：管道输入/异常文本在 locale 非 UTF-8 时经 surrogateescape 解码可能携带 U+D800-DFFF，控制台 handler 写 UTF-8 抛 `UnicodeEncodeError`（logging 报错并把该条日志吞掉）、JSONL handler 同病（首次失败后静默丢日志）；新增 `utils._sanitize_surrogates`（将 surrogate 替换为 U+FFFD），`_ConsoleFormatter.format` 与 `JsonlFileHandler.emit` 写前净化
- **`_append_subscribe_url`/菜单 11 删除破坏 代理.txt 换行风格**：原实现以通用换行模式读写（读时 \r\n→\n 归一、写时 \n→\r\n 翻译），LF 文件增删后变 CRLF、尾随换行状态改变；现读写均 `newline=""` 字节级保持原风格（增补按文件内换行风格 `\n`/`\r\n` 与尾随状态写分隔，删除按原始行逐行保留）

### 移除
- （无）

---

## v4.11.0

### 新增
- **菜单 8「快速测速」**：等价命令行 `--fast`（5s 测速窗口/跳过 IP 检测），菜单 1-7 编号不变
- **菜单状态行**：`show_menu` 顶部显示订阅文件配置状态（`已配置 (N 条)`/`未配置`）与上次结果摘要（`output/` 最新 PNG 的模式与时间；会话内优先本次结果）；新增提示行「回车=重绘菜单 · 连续两次 Ctrl+C=退出」
- **菜单 Ctrl+C 软化**：菜单输入处第一次 Ctrl+C 提示"再按一次退出"并返回菜单，连续两次才退出（正常输入后计数清零）
- **手动输入订阅 URL 保存询问**：菜单无 `代理.txt` 手动输入 URL 后询问 `保存到 代理.txt 吗？[y/N]`（默认否；重复行跳过；保存事件 JSONL 记 `manual_subscribe_input` 且 saved=True）
- **控制台 TOP5 小结**：`report.py` 新增 `print_console_summary(results, sort_by, top=5)`（名称/延迟/HTTP/平均/最大，有流媒体数据加解锁列、有 IP 数据加风险列，按排序取前 5 并提示剩余总数）；`run_test` 正常结束与 `_finish_partial` 提前结束两条路径均调用
- **订阅解析进度反馈**：`parse_subscription_url` 每个 UA 尝试成功后输出 `UA {ua} 解析到 N 个节点`；`parse_subscription_urls` 每个订阅开始输出 `[i/N] 订阅解析中: {masked url}`
- **测速阶段小结**：HTTP 测速完成后输出 `测速完成: 成功 X/Y | 最快 Z MB/s (节点名) | 平均 W MB/s[ | 失败 N]`
- **内核下载进度增强**：`_download_mihomo` 进度行显示 `已下载/总量 百分比 速度/秒 剩余秒数`；下载完成与就绪日志带 mihomo 版本 tag
- **菜单 6 版本对比**：更新前对现有内核跑 `mihomo -v` 显示当前版本与远程最新 tag（`_get_mihomo_version` 静态方法；解析失败静默降级），更新完成行显示新版本
- **控制台编码自愈**：`main()` 在 win32 且 `sys.stdout.isatty()` 时执行一次 `chcp 65001`（不经 run.bat 直接运行菜单边框/中文不再乱码）
- **进度条不残留**：全部 6 处 tqdm（TCP Ping/TCP 探测/HTTP 测速/解锁检测/IP 检测/网页模拟/节点流水线）统一 `leave=False`

### 修改
- **测速结果行紧凑化**：`run_speed_test` 中 `speed_done` 事件由 `logger.info` 降为 `logger.debug`（JSONL 文件 handler 为 DEBUG 级，结构化事件不丢）；控制台改为无时间戳逐节点行 `[i/N] 节点名 延迟 速度/错误注记`（`_trunc_width` 按显示宽度截断节点名、`_pad_right` 对齐）
- **`run.bat` 依赖安装显示进度**：`pip install` 去掉 `-q`（首次安装不再静默数分钟）
- **README×2**：菜单表新增选项 8；控制台输出示例更新为紧凑结果行 + 阶段小结 + TOP5 格式；特性列表补控制台体验条目；平台支持标注更新为 v4.11.0

### 修复
- **cloudscraper / yt-dlp 软依赖在 v4.10.0 模块化后实际失效**：`core/parser.py` 未本地导入 `cloudscraper`/`yt_dlp`（`utils.py` 探测的 `HAS_*` 标志经 `*` 透出、模块名不透出），`HAS_CLOUDSCRAPER=True` 时调用 `cloudscraper.create_scraper()` 抛 NameError 被 except 静默吞掉——cloudscraper 反爬回退与油管测速源（yt-dlp）分支从未真正执行；现 parser.py 本地 try-import（失败置 None）并在调用处加 `is not None` 守卫，实测不再出现 `name 'cloudscraper' is not defined` 警告

### 移除
- （无）

---

## v4.10.1

### 修复
- **mihomo 内核下载在 Linux/macOS 完全不可用**：官方发布件 Windows 为 `.zip`、Linux/macOS 为**单文件 `.gz`（gzip）且无 zip**（v1.19.29 资产实测核对），`_download_mihomo` 候选名与解压逻辑硬编码 zip → Linux/macOS 永远下载失败；现按平台分支——Windows 保持 `.zip` + zip-slip 校验解压，Linux/macOS 候选 `mihomo-{plat}-{tag}.gz`/`-v1-`/`-go124-`，gzip 解压写 `mihomo`（无扩展名）+ chmod 755；已用模拟 Linux 环境实测：linux-amd64 下载→解压→ELF 魔数 7f454c46 正确（48.3MB）
- **mihomo 内核下载架构硬编码**：`_download_mihomo` 原固定 `amd64`（windows/linux/darwin），ARM 设备（linux-arm64 / darwin-arm64 / windows-arm64）下载 x86_64 版无法执行，Apple Silicon 依赖 Rosetta 2（macOS 26 起弃用）；现按 `platform.machine()` 映射——`x86_64/AMD64/x64`→`amd64`、`arm64/aarch64`→`arm64`，不支持的架构返回空并记 WARNING（v1.19.29 资产实测含 linux-arm64 / darwin-arm64 / windows-arm64 的 plain 名）

### 修改
- 平台支持声明更新（README×2）：明确 **Windows 10+（x86_64/arm64）为唯一实测平台**；Linux 与 macOS 按跨平台编写、静态审查通过但**未经实测**（内核下载路径已实测验证）；已知降级行为文档化——macOS Gatekeeper 拦截手动放置的 mihomo（用自动下载/菜单 6）、Linux 无图形界面不自动打开报告（xdg-open 缺失，不影响测试与手动查看）、无中文字体时 PNG 中文显示方框（安装 Noto Sans CJK）
- `_find_or_download` 失败提示由"手动把 mihomo.exe 放入 bin/"改为通用表述（Linux/macOS 二进制无 .exe）

### 新增
- （无）

### 移除
- （无）

---

## v4.10.0

### 修改
- **代码模块化拆分**（维护性重构，行为不变）：`core/speed_test.py` 4137 行单文件拆为 16 个模块——`config.py`（常量）/`models.py`（数据类）/`utils.py`（遮蔽与工具）/`logging_setup.py`（日志）/`procs.py`（子进程）/`state.py`（运行时全局）/`parser.py`（解析器）/`engine.py`（引擎+TCP 检测）/`tester.py`（测速）/`streaming.py`（流媒体）/`ip_quality.py`（IP 质量）/`webpage.py`（网页模拟）/`report.py`（报告）/`runner.py`（编排）/`cli.py`（入口）/`image.py`（兼容重导出）；`speed_test.py` 收口为入口 + 兼容重导出（`__all__` 109 个旧公开符号，`from core.speed_test import X` 与 `from core import X` 路径全部保留）；依赖方向自底向上无环，可变全局统一经 `core.state` 访问（`reset_run_state()`）
- **mihomo 外部控制器认证**：`_build_config_dict` 增加 `secret` 字段（每实例 `secrets.token_hex(16)`），引擎与 worker 全部 API 请求（/version、/proxies/Auto、/configs）携带 `Authorization: Bearer` 头
- **URL 遮蔽扩充**：`_SENSITIVE_PARAMS` 新增 sid/user/username/pass/access_token/refresh_token/token_type/api_key/apikey/secret_key/private_key/client_secret/session/sessionid/cookie；`_mask_url` 支持权威段 basic-auth 遮蔽（`https://user:pass@host` → `https://user:***@host`）
- **菜单6 内核更新改为原子替换**：旧目录 `rename` 为 `MIHOMO_DIR.bak` → `move` 新内核 → 成功删除备份/失败回滚旧目录
- **`_download_mihomo` 资源管理**：非 200 响应显式 `close()`；下载中途异常删除半截压缩包
- **`_mark_reuse` 入口 key**：由 `node.server` 改为 `f"{server}:{port}"`（同主机不同端口不再误判同入口）；空 server 不参与计数
- **`check_generic` 403 判定收紧**：Cloudflare 特征（cf-chl/cf-challenge/challenges.cloudflare/cf-browser-verification/Attention Required/Just a moment）一律判"封锁"，仅正常业务页面结构判"可用"；删除不可达的 `aiohttp.ClientResponseError` 分支
- **`check_disney` 区域校验**：最终 URL 含 not-available/unavailable 或页面含区域文案时判"失败(区域不可用)"，不再仅凭 200 判解锁
- **`check_bilibili_tw` 错误码判定**：`code == -10403` 直接判"失败(区域限制)"（message 匹配降为兜底）
- **`check_ip_quality` 429 退避**：每源最多重试 2 次（间隔 1.0s + attempt），不再 429 即降级到无风控字段的回退源
- **`parse_vmess`**：tls 判定改白名单式（`"tls"/"true"/"1"` 为真；`"none"/""/"0"/"false"` 不再误判开启）；network 分支补 `quic`/`h2`
- **`parse_anytls`**：insecure/allowInsecure 判定改白名单式（`"true"/"1"/"yes"`；`insecure=0`/空值不再置 `skip-cert-verify: true`）
- **`parse_ssr`**：新增 `remarks` 参数（base64 节点名）解码，优先于服务器地址作节点名
- **`_is_valid_node`**：wireguard 增加 private-key 存在性校验（缺 private-key 一并过滤）
- **`_try_fetch`**：订阅响应改流式读取 + 20MB 体积上限（`_read_limited`），读取后 `resp.close()`；解析阶段流量头捕获经 `state._SUB_INFO`（修复静默失效）
- **`_dedupe_nodes`**：新增节点名清洗（去控制符/换行、限长 100）
- **`_find_free_port`**：新增 `exclude` 参数，mixed/api 端口互不相同
- **`export_results_json`**：`json.dump` 增加 `allow_nan=False`
- **`_fmt_ss`**：增加类型守卫（非字符串返回 `--`，不再抛 TypeError 拖垮报告）
- **`run_end` 事件 schema 统一**：固定键 `completed/reason/partial/nodes`（正常完成含 total_seconds/mode/report）
- **`new_run_log` 交互事件迁移**：删除旧日志前将 `menu_choice`/`invalid_input`/`manual_subscribe_input` 事件行迁移到新日志（不再被轮换吞掉）
- **油管源解析不阻塞事件循环**：`resolve_youtube_download_url` 调用改 `asyncio.to_thread`
- **`run.bat`**：增加 Python >= 3.9 版本断言（失败输出明确提示）
- **订阅文件读取**：`read_subscribe_urls` 与 `-i` 改 `utf-8-sig`（兼容 UTF-8 BOM），GBK 解码失败时回退
- **报告页脚时区**：硬编码 `(CST)` 改为本地时区名（`time.strftime("%Z")`）
- **报告类型列**：`type[:7]` 截断改为缩写映射（hysteria2→hy2、wireguard→wg）
- **`_open_report` 跨平台**：Windows `os.startfile`、macOS `open`、Linux `xdg-open`
- **`_str_width`**：改用 `unicodedata.east_asian_width` 判宽（é/ü 等窄字符计宽 1）
- **子进程登记回收**：新增 `_untrack_proc`（正常回收后注销，防列表无限增长）；`_cleanup_procs` 对已退出进程补 `wait`
- **`_font` 回退链扩充**：新增 Noto CJK 多路径/SimSun/PingFang/STHeiti；无任何 CJK 字体时 WARNING 提示（不再静默出方框）
- **异常日志统一遮蔽**：YAML 解析/yt-dlp/IP 源/节点流水线/测速连接/流量倍率/JSON 导出异常及 `JsonlFileHandler` exc 字段、excepthook traceback 全部过 `_safe_exc_str`

### 修复
- **vmess 节点误判不可达**：v2rayN 禁用 TLS 写 `"tls":"none"` 被真值判断误判为开启 TLS（mihomo 对纯 TCP 发起 TLS 握手失败）
- **菜单6 更新损坏旧内核**：`shutil.rmtree` 先删后移，move 失败即丢失旧内核且无回滚
- **订阅 URL 凭据泄露面**：basic-auth 与 sid/user/access_token 等参数未遮蔽，可进日志（ISSUE_TEMPLATE 引导外发日志）
- **mihomo API 无认证**：external-controller 无 secret，本机进程/DNS 重绑定可读取节点凭据与篡改出口
- **YAML 解析异常日志泄露**：`%e` 裸写异常（PyYAML 错误消息可能带凭据上下文），改 `_safe_exc_str(e)`
- **SSR 节点名缺失**：`remarks` 参数未解码，节点名显示为服务器地址
- **复用检测误判**：同主机不同端口节点被标"中转复用/完全复用"
- **IP 源 429 静默降级**：主源瞬时限流直接换到无风控字段回退源，风险列变 `--`
- **bilibili_tw 区域限制误分类**：未按错误码 -10403 判定，message 措辞变化时标为普通"失败"
- **check_generic 误报解锁**：Cloudflare 拦截页含 `<!DOCTYPE` 被判"可用"
- **订阅响应无体积上限**：恶意端点可耗尽内存
- **菜单交互事件丢失**：`menu_choice` 等事件写入的日志被 `new_run_log` 轮换删除
- **UTF-8 BOM 首行解析失败**：`代理.txt`/`-i` 文件带 BOM 时首行 URL 带 `\ufeff`
- **`_fmt_ss` 崩溃**：streaming 值为 None 时 TypeError 致 PNG 报告整体失败
- **流量倍率静默失效**（模块化引入）：`_SUB_INFO` 在解析器模块中未定义，捕获被 except 吞掉；改为 `state._SUB_INFO`
- **JSON 导出失败**（模块化引入）：report 模块缺 `import json`；另缺 `sys`（runner）/`tempfile`（logging_setup）/`time`（webpage）/`typing.Optional`（engine/parser/report）已补齐
- **节点流水线全灭**（模块化引入）：runner 模块缺 `import aiohttp`，流媒体/IP/网页检测 33/33 报 `name 'aiohttp' is not defined`；已修复并全量回归验证

### 移除
- `check_generic` 不可达的 `aiohttp.ClientResponseError` 分支
- `generate_report_image` 中未使用的 `has_http` 变量
- 报告页脚硬编码 `(CST)` 时区标注


### 新增
- **TCP Ping 丢包率**：`tcp_ping_retry` 重试 2→3 次，返回 (最小延迟, 成功次数)；报告延迟列显示 `312ms(1丢)`（有丢失时），JSON 新增 `tcp_loss` 字段（UDP 节点为 null）
- **复用检测四档**（借鉴 SSRSpeedN）：`_mark_reuse` 按入口（node.server）与落地 IP 统计——完全复用（入口+落地都相同）/中转复用（入口同、落地异）/落地复用（入口异、落地同），O(n)，结果写入 `ip_info.reuse`；报告 normal/full 模式新增"复用"列
- **网页模拟测速**（借鉴 SSRSpeedN）：`WPS_INTERNATIONAL_URLS`（google generate_204 / youtube / bing / github）+ `WPS_CN_URLS`（baidu / bilibili / qq），落地国家为 CN 时自动换国内站点；`check_one_node_webpage` 并发 GET 记首字节耗时（失败=-1），汇总 `avg_ms`；normal/full 模式在 IP 检测后自动运行（`--fast` 跳过、basic/streaming 模式不跑）；报告新增"网页均耗(ms)"列；JSON 新增 `webpage` 字段；事件 `webpage_done`
- **流量倍率**（借鉴 SSRSpeedN）：解析阶段捕获订阅响应头 `subscription-userinfo`（`_SUB_INFO`，首个带 header 的响应为准）；测速阶段累计实测下载字节（`_RUN_BYTES`）；Step 7 重拉订阅头取 download 增量（`_fetch_sub_usage`），倍率 = 计费流量增量 ÷ 实测字节（`_RATE_INFO`）；控制台输出"流量倍率: X.XX" + 事件 `rate_done` + 报告页脚追加"流量倍率: X.XX"；订阅服务器不支持该 header 时静默跳过

### 修改
- normal/full 模式阶段 4 加入网页模拟（步骤标签"流媒体/IP/网页检测"，streaming 模式标签不变）；`node_tasks` 3 元组扩为 4 元组（增加 do_web）
- 报告 normal/full 列布局新增"复用"、"网页均耗"两列（有对应数据时才渲染）
- `run_tcp_ping` 返回结构由 {名称: 延迟} 改为 {名称: (延迟, 成功次数)}，run_test 初测与补测两处调用点同步
- README×2 重构（GitHub 页面工程）：头部改为一句话简介 + 徽章 4 枚（License/Release/Python/Downloads，统一 flat-square 风格）；命令行参数改为表格；新增 `[!IMPORTANT]`/`[!NOTE]` 提示块（订阅 token 敏感、测速消耗流量）；新增控制台输出示例（--fast 节选）；特性列表 14 条压缩为 10 条；JSON 数据说明补 `tcp_loss`/`webpage`/`reuse` 字段；新增「更新记录与致谢」一节（CHANGELOG 入口 + mihomo/SSRSpeedN 致谢 + Issues 反馈指引）
- 新增 `.github/ISSUE_TEMPLATE/`：bug_report.yml（要求附 log/ 的 jsonl）、feature_request.yml、config.yml（关闭空白 issue，链接 README 常见问题）
- 新增 `docs/social_preview.png`：1280x640 社交预览图（报告缩略图 + 控制台输出模拟，假数据）

---

## v4.8.1

### 新增
- 日志独立目录 `log/`（常量 `LOG_DIR`）；文件日志改为 JSONL：`log/测速日志_YYYYMMDD_HHMMSS.jsonl`（每次运行新建一个文件，`log/` 只保留最新一个），每行一个 JSON 对象 `{"ts","level","event","msg","data"}`；`JsonlFileHandler` 逐条 flush（强杀/关窗口不丢已写内容）
- `new_run_log()`：每次测试运行新建一个 JSONL 文件，并删除更早的日志文件（`log/` 只保留最新一个；菜单多次运行不混写同一文件）
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
- 油管下载源默认隐藏：新增 `YOUTUBE_SOURCE_ENABLED = False` 开关——关闭时不解析、不产生任何油管相关日志，只测 3 个基础源；改为 `True` 恢复第 4 源行为（代码与 yt-dlp 依赖保留）
- requirements.txt 最低版本提升（防 Python 3.12 缺 cp312 wheel 触发源码编译失败）：`aiohttp>=3.9.5`、`PyYAML>=6.0.1`、`Pillow>=10.1.0`、`tqdm>=4.66.1`、`cloudscraper>=1.2.71`
- run.bat：`where python` 找不到时回退 `py -3` 启动器；依赖安装改 `py -m pip`
- `_try_fetch`：cloudscraper 回退 requests 时记录 `fetch_fallback` 事件
- 文件结构整理（不动代码）：`README.md`、`README_EN.md`、`CHANGELOG.md`、`LICENSE`、示例报告图 `preview_report.png` 移入 `docs/` 目录（原 `assets/` 目录删除）；两个 README 的文件结构段落与图片相对路径同步更新
- 版本号改用 SemVer（X.Y.Z）：`VERSION = "4.8.1"`（此前 "v4.8"）；PNG 页眉/页脚与菜单标题显示 `v{VERSION}`，JSON 导出 `version` 字段为纯数字
- run.bat：依赖安装提示"首次可能需要几分钟"、成功后 `[OK] 依赖安装完成`、失败提示国内镜像 `pip install -r core\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
- mihomo 下载失败时控制台追加修复指引（手动把 mihomo.exe 放入 bin/ 或菜单 6 更新内核）；README×2 FAQ 增补对应条目
- README×2：菜单表补全 5/6/7 项；FAQ 日志文件名 `测速日志_*.json` → `.jsonl`；PNG 国旗表述改"控制台与 PNG 均显示国家代码"
- `_ipapi_to_info`：按 ipapi.is 免费接口实际扁平响应重写映射——实测返回 `cc`/`company_name`/`asn_num`/`asn_org` 等扁平字段（无 `location`/`asn`/`company` 嵌套对象、无城市与移动网络标志），此前映射读嵌套对象导致主源的国家/ISP/ASN/组织全部为空（报告 ASN 列显示 `--`）
- `_ipwho_to_info`：免费接口（含 `?security=1` 参数）实测无 `security` 字段、`type` 恒为 IPv4/IPv6——无风控数据时类型/风险标志置 None（报告显示 `--`，不编造），此前全部按 False 处理误报"家宽 IP / 风险 0%"；有 `security` 字段时仍按原逻辑映射

### 修复
- **安全（P1）**：`run_start` 事件的 `argv` 中 http(s) 参数经 `_mask_url` 遮蔽——此前 CLI 直传订阅 URL（`python speed_test.py "https://xxx/sub?token=SECRET"`）时 token 明文写入 JSONL 日志
- run.bat 被重写为 LF 行尾（cmd.exe 无法正确解析多行 if 块与 goto 标签，双击直接报错）→ 恢复 CRLF 行尾并加 `.gitattributes`（`*.bat -text`）保证 zip 分发字节正确
- run.bat 括号块内嵌套 `%ERRORLEVEL%` 比较（批处理为解析期展开、取值过期）导致 `py -3` 回退分支永不生效 → 改为 `if errorlevel 1` 动态判断 + goto 标签结构
- run.bat：`where python` 结果只认 `.exe`（跳过微软商店别名与 .cmd/.bat 垫片——批处理调用批处理不会返回控制流，实测复现静默终止）；依赖安装失败时提示并退出
- run.bat 与文档的 Python 版本要求改为 **3.9+**（代码使用 PEP 585 泛型注解，3.8 导入即 TypeError；全面审计实证）
- `new_run_log()`：文件名 1 秒分辨率导致同秒两次运行同文件追加混写（实测复现）→ 同秒自动加毫秒后缀；旧日志文件在新建时统一删除（只保留最新）；进程退出时 `_cleanup_empty_log` 清理空日志（--help/--report/菜单直接退出不再留 0 字节文件）
- `JsonlFileHandler`：写失败（文件被占用/磁盘满）首次向 stderr 提示一次，不再静默丢日志；`exc_info` 为 `(None,None,None)` 时不再写入误导性 exc
- 早退路径（订阅为空/解析失败/无节点/提前生成部分报告）补 `run_end(completed=false)` 事件，日志可区分"完成/中断/失败"
- `_cleanup_stale_configs` 只删超过 6 小时的残留配置（防误删并发运行实例的配置）
- `_install_excepthook` 链式调用既有 excepthook（不覆盖其他工具的 hook）
- 测试完成后自动打开 PNG 报告（`async_main` 的 CLI 与菜单两处调用点）——此前只在菜单5/--report 打开，与 README 承诺不符
- 纯流媒体模式（菜单3/4）补 mihomo 二进制存在性检查——此前缺失时串行路径抛 RuntimeError
- `run_test` 的 `workers` 参数钳制到 1-8（防异常入参开过多 mihomo 进程）
- 标准测试（菜单2）流媒体路径核查确认无功能 bug（菜单2 → normal → full + 9 常用流媒体 + IP；`check_one_node_streaming(services=None)` 兜底 FULL 34 平台）；此前"没测到流媒体"系测试中途 Ctrl+C 中断导致（中断前的 JSON 流媒体为空），现由 `user_interrupt` 事件明确记录
- **安全（P0）**：订阅抓取失败时 requests/cloudscraper 异常文本携带完整订阅 URL（含 token）进入控制台与 JSONL（实测复现 `ConnectTimeout: ... url: /sub?token=SECRET123&flag=clash`）→ 新增 `_safe_exc_str`（异常文本内完整 URL 与 `url: /path?token=` 相对形式统一过 `_mask_url`），`fetch_fallback`、`订阅下载失败` RuntimeError、两处 UA 拉取失败、`订阅解析失败`、run_test 解析兜底共 6 处日志点改用遮蔽文本
- `_mask_url` 盲区补全：敏感参数白名单扩展 `sub`/`subid`/`code`/`id`；无 query 时 path 末段长度≥16 且不含 "." 视为内嵌 token 遮蔽（`https://host/xxxx...` 形态）
- **Ctrl+C 清理失效**：`except asyncio.CancelledError` 吞掉取消后 finally 内首个 await 即再次抛 CancelledError（Python 3.11+ asyncio.run 下 Ctrl+C 主路径），mihomo/worker 清理与部分报告生成被跳过 → 子进程统一登记 `_track_proc` + `main()` 注册 `atexit` 同步兜底 terminate（`_cleanup_procs`）；run_test finally 清理改 `asyncio.shield` 包裹（取消时 stop 在后台跑完）
- `parse_vless`：`security=tls`/`xtls` 现映射 `tls: true`（此前仅 reality 特判，标准 TLS vless 节点全部误报不可达）；reality 分支补 `tls: true`（mihomo v1.19 `-t` 实测报 "REALITY requires TLS"）；security 为 reality/tls/xtls 时映射 `servername`（`sni` 优先、`host` 兜底，add 为 IP 时证书校验必需）
- `parse_vmess`：`tls` 时映射 `servername`（`sni`/`host`）；`net=grpc` 时映射 `grpc-opts.grpc-service-name`（v2rayN 把 serviceName 放 `path` 字段，两处都读）
- `parse_vless`：`type=grpc` 时映射 `grpc-opts.grpc-service-name`（`serviceName`/`path`）
- YAML 订阅：识别改 `_looks_like_yaml`（容忍 `#`/`//` 注释行开头，此前注释头导致整份订阅报"未解析到任何节点"）；YAML 路径与 URI 路径统一过 `_is_valid_node` + `_dedupe_nodes`（此前 naive/juicity/本地地址/重名节点原样进配置，单条即可致整份配置加载失败）
- `_is_valid_node` 过滤名为 `DIRECT`/`Auto` 的节点（与 mihomo 内置名称冲突，`_build_config_dict` 实测产生 `['DIRECT','Auto','DIRECT']` 组）
- hysteria2/hysteria/tuic：`insecure` 判定 `== "true"` → `in ("true","1","yes")`（实测 `insecure=1` 此前不生效）
- `_parse_userhost_port`：username 现 `unquote`（实测 `user%40name` 此前原样进配置致认证失败）
- `parse_ssr`：`obfsparam` 明文值（如 `tls1.2_ticket_auth`）此前 b64 解码抛异常致整条节点被静默丢弃 → 解码失败回退保留明文
- `MihomoEngine.start`：轮询中检测 `process.poll()`，进程秒退（配置错误/二进制损坏）立即报错，不再等满 15s
- `_download_mihomo`：候选名追加 `mihomo-{plat}-v1-{tag}.zip`（v1.19.29 起官方新增 v1/v2/v3 变体；plain 名经各版本 API 核对目前保留，防未来移除）
- `check_steam`：cookie 兜底同时查 `steamCountry`/`steamcountry`（实测响应头为 `steamCountry` 大写 C，原查询永不命中）；body 正则改 `re.IGNORECASE`
- `check_spotify`：Location 无国家码时跟到落地页提取 `"territory"` 字段（实测现代 Spotify 统一 301 → `https://open.spotify.com/`，旧式 `/xx/` 国家码路径已消失）
- 报告图片生成失败时不再中断后续：Step7 与 `_finish_partial` 包 try/except，图片失败仍导出 JSON
- 串行 IP 检测 `same_ip_warning` 改 seen_ips 全集比较（此前只比相邻节点，`--workers 1` 与并行路径行为不一致）
- 报告渲染：PNG 节点名套 `_flag_to_text`（国旗 emoji 此前渲染为空心方框，实测 msyh 无区域指示符字形）+ 超 24 字符截断补省略号；`normal/full` 列头 "TLS延迟"→"延迟RTT"（数据为 TCP 握手）；HTTP延迟无数据显示 `--`（此前显示"超时"，与 README 术语表不符）；流媒体列按 `FULL_STREAMING_SERVICES` 定义顺序（此前 set 迭代乱序）；CLI `--full` 页眉"标准测试"→"完整测速"；`ip_risk` 无数据 `--` 灰色（此前按 0 分染绿）
- CLI：未知参数加 `logger.warning`（此前 `--falt` 等拼错静默忽略）；`-i` 缺参数提示并跳过；`--workers N` 值参数跳过后续解析；帮助文本路径改 `python core/speed_test.py` 并补 `--workers=4` 等号形式
- 菜单：空回车重绘菜单（此前报"无效选择"）；完成文案改"测试完成! 耗时 X 秒，共 N 个节点"
- `_YOUTUBE_DL_URL` 每次 `run_test` 开始重置（此前菜单连续运行复用上一次 googlevideo 签名 URL，约 6h 过期）
- `main()`：stdout/stderr 非 TTY 时 `reconfigure(encoding="utf-8")`（Windows 重定向/管道此前按 ANSI 代码页输出乱码）

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
