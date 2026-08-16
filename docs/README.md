> 语言 / Language: [中文](README.md) | [English](README_EN.md)

# 机场测速

把机场订阅里的所有节点拉下来，一键测完延迟、速度、流媒体解锁与 IP 质量，自动生成图文报告。不用懂 mihomo 配置，也能知道自己该用哪个节点。

[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![Release](https://img.shields.io/github/v/release/oscyfmau/airport-speedtest?style=flat-square)](https://github.com/oscyfmau/airport-speedtest/releases)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Downloads](https://img.shields.io/github/downloads/oscyfmau/airport-speedtest/total?style=flat-square)](https://github.com/oscyfmau/airport-speedtest/releases)

版本：v4.32.0 ｜ 仓库：[github.com/oscyfmau/airport-speedtest](https://github.com/oscyfmau/airport-speedtest) ｜ [更新记录](CHANGELOG.md)

> 本项目由 AI 编写完成，因个人测速需求而开发，按需取用。

## 预览

![示例测速报告](preview_report.png)

（示例报告，数据为演示用途）

## 快速上手（三步，不会命令行也能用）

1. **下载**：打开 [Releases 页面](https://github.com/oscyfmau/airport-speedtest/releases)，下载最新版的 `airport-speedtest-v4.32.0.zip`（精简包，含运行所需的全部文件）并解压，解压后先看里面的 `使用教程.txt`（会用 git 也可以 `git clone`）
2. **填订阅**：把解压目录里的 `代理.txt.example` 复制一份，改名为 `代理.txt`，用记事本打开，粘贴你的订阅链接后保存
   - 什么是订阅链接？机场服务商提供的网址（一般以 `https://` 开头，内含全部节点信息），在机场官网或客户端 App 的「复制订阅」处获得
3. **运行**：
   - 安装 Python 3.9+（[python.org](https://www.python.org/downloads/)，安装时勾选 "Add python.exe to PATH"）
   - 在解压目录执行 `pip install -r core/requirements.txt`
   - 双击 `run.bat` → 菜单选 `2` 下载速度 → 等待几分钟 → 自动打开 PNG 报告（报告文件在 `output/` 文件夹，日志在 `log/` 文件夹）

mihomo 内核无需手动下载，首次运行时自动下载到 `bin/`（约 47MB）。

> [!IMPORTANT]
> 订阅链接包含账号 token：`代理.txt` 只保存在本地（已加入 .gitignore），不要发到公开场合。工具自身也会在日志与异常记录里自动遮蔽订阅 token。

> [!NOTE]
> 测速会消耗节点流量（每节点约 10-30MB）；标准测试还会为每个节点额外做一轮网页模拟（约 3-8 秒）。节点套餐写明「勿跑大流量」的，请用 `--fast` 或谨慎全量测试。

## 特性

- 协议解析：支持 vmess / vless / trojan / ss / ssr / hysteria2 / tuic / wireguard / anytls 等 20 种协议，多个订阅 URL 可合并去重
- TCP 延迟：本机直连握手 + mihomo 隧道双来源互验减少误判，3 次握手统计丢包率（延迟列显示 `312ms(1丢)`）
- 测速：节点串行互不干扰、单节点 4 路连接 + 3 个下载源聚合（Cloudflare/CacheFly/OVH），8 秒窗口、剥离首秒慢启动
- 流媒体解锁：33 个平台、10 个专用检测器（Netflix/Disney/YouTube/B站港澳台/TikTok/Steam 等），死节点提前跳过不浪费时间
- IP 质量：类型（家宽/机房/代理/移动）+ ASN + 风险评分 0-100，ip-api.com 主源，ipapi.is / ipwho.is / api.ip.sb 回退
- 复用检测四档：完全复用 / 中转复用 / 落地复用，一眼看穿机场共用线路（借鉴 SSRSpeedN）
- 网页模拟：并发加载 4 个代表性站点记首字节耗时，落地 CN 自动换国内站点（百度/哔哩哔哩/腾讯）
- 补测机制：报告前自动补测超时节点，恢复的节点补跑测速
- 输出：PNG 可视化报告（整格色块 + 每秒速度柱 + 白色网格线）+ JSON 结构化数据 + JSONL 结构化日志（订阅 token 自动遮蔽）
- 控制台体验：订阅解析按 UA 逐次反馈、测速逐节点实时结果行、每阶段小结、结束时控制台 TOP5 排行（不开图也能看结果）；进度条阶段结束自动消失不残留
- 菜单管理：节点稳定性视图（近 N 次出现率/可达率/波动）、节点筛选测速（按关键字/前 N 个）、历史结果管理（打开/删除）、订阅管理（遮蔽显示/添加/删除）、设置页（窗口秒数/并行数/自动开报告/稳定性窗口/大流量确认，跨会话保存）、环境信息页

## 安装与运行

### 环境要求

- Windows 10+（x86_64 / arm64）—— **唯一实测平台**（完整回归验证）
- Linux（x86_64 / arm64）与 macOS（Intel / Apple Silicon）—— 代码按跨平台编写、静态审查通过，但**未经实测**；如遇问题请到 [Issues](https://github.com/oscyfmau/airport-speedtest/issues) 反馈（附 `log/` 最新 jsonl）
- Python 3.9+
- 依赖：`pip install -r core/requirements.txt`
- mihomo 内核无需手动下载，首次运行时自动下载到 `bin/`（约 47MB）

### 获取代码

两种方式任选：

- 不用 git：到 [Releases 页面](https://github.com/oscyfmau/airport-speedtest/releases) 下载最新版 `airport-speedtest-v4.32.0.zip`（精简包，仅含运行核心文件）并解压；需要自行改代码时再下载 `Source code (zip)`
- 用 git：

```bash
git clone https://github.com/oscyfmau/airport-speedtest.git
cd airport-speedtest
pip install -r core/requirements.txt
```

### 运行方式

双击 `run.bat` 进入交互菜单，或命令行直接执行：

| 命令 | 说明 |
|---|---|
| `python core/speed_test.py` | 交互菜单（等价于双击 run.bat） |
| `python core/speed_test.py <URL>` | 直接测速（简单模式：TCP Ping + HTTP 测速） |
| `python core/speed_test.py <URL> --full` | 完整测速（+ 流媒体解锁 + IP 质量 + 网页模拟） |
| `python core/speed_test.py <URL> --fast` | 快速模式（5 秒测速窗口 / 跳过 IP 检测） |
| `python core/speed_test.py <URL> --workers N` | 流媒体/IP/网页并行数（1-8，默认 4；测速恒串行） |
| `python core/speed_test.py -i file.txt` | 从文件读取多个订阅 URL（每行一个） |
| `python core/speed_test.py --report` | 打开上次报告 |
| `python core/speed_test.py --menu` | 强制显示菜单 |
| `python core/speed_test.py -h` | 查看帮助 |

> 提示：`--full` 与 `--fast` 组合时，快速模式优先——测速窗口 5 秒且跳过 IP 质量与网页模拟（流媒体检测仍执行）。

```bash
python core/speed_test.py https://你的订阅链接 --fast   # 5 分钟快速摸底
python core/speed_test.py https://你的订阅链接 --full   # 完整报告
```

订阅 URL 默认从项目根目录的 `代理.txt` 读取（每行一个 URL）。仓库不含该文件：复制 `代理.txt.example` 为 `代理.txt` 后填写（已加入 .gitignore，不会误传）。

### 菜单模式

菜单分三级（v4.29.0 起）：一级测速入口，二级辅助功能，三级维护。

| 一级菜单 | 说明 |
|---|---|
| 1. 标准测试 | 测速 + 8 个常用流媒体 + IP 质量 + 网页模拟 |
| 2. 下载速度 | TCP 检测 + HTTP 测速（最快，最省流量） |
| 3. AI 网站 | 8 个 AI 平台检测 |
| 4. 所有流媒体 | 33 个平台全测 |
| 5. 快速检测 | 并行近似测速 + 4 核心流媒体（YouTube/Netflix/Disney+/ChatGPT），速度只作量级参考（v4.30.0 起可用） |
| 6. 更多 | 进入二级菜单 |
| 0. 退出 | 退出程序 |

| 二级菜单「更多」 | 说明 |
|---|---|
| 1. 节点稳定性 | 节点档案视图：常青树/过山车/新面孔/普通分层，近 N 次出现率/可达率/平均速度与波动（N 在设置页调） |
| 2. 结果对比 | 两次测试横比：速度/延迟/解锁/排名差分，变化>20% 标 ↑↓，晚高峰自动标注（v4.30.0 起可用） |
| 3. 订阅分组对比 | 多订阅横评：节点数/平均速度/最高速度/解锁率/平均延迟/风险均值（解锁率排除跳过与错误；v4.31.0 起可用） |
| 4. 节点筛选测速 | 按节点名关键字（如 `香港 JP`）或前 N 个（`N=10`）筛选后测速，可选简单/标准/快速模式 |
| 5. 查看上次结果 | 打开 output 目录最新的 PNG 报告 |
| 6. 结果管理 | 列出 output 最近 15 份报告（时间/模式），输入编号打开、`D编号` 删除 |
| 7. 订阅管理 | 遮蔽显示 代理.txt 的 URL，可添加（去重）、删除、用记事本打开编辑 |
| 8. 设置 | 测速窗口秒数（3-30，默认 8）、并行数（1-8，默认 4）、自动打开报告、稳定性窗口（5/10/20，默认 10）、大流量确认（>50 节点需回车确认）、保留报告份数（10/30/100，默认 30）、日志保留天数（7-365，默认 30）；保存到 `~/.airport_speedtest.json` 跨会话生效 |
| 9. 维护 | 进入三级维护菜单 |
| 0. 返回 | 返回一级菜单 |

| 三级菜单「维护」 | 说明 |
|---|---|
| 1. 更新内核 | 下载最新 mihomo 内核（显示当前/目标版本，先下载后替换） |
| 2. 环境信息 | 工具/Python/依赖/mihomo 版本、订阅条数、报告与日志文件数 |
| 3. 清理旧报告 | 显示占用与将删数，确认后清理；自动清理在每次测后静默执行（v4.31.0 起可用，保留份数/天数在设置页调） |
| 0. 返回 | 返回二级菜单 |

菜单顶部会显示订阅文件配置状态与上次结果摘要；**代理.txt 有多条订阅时，测试前会列出并让你手动选择**（逗号分隔多选，回车=全部）；测试中按 Ctrl+C 可中断（生成部分报告）；一级菜单按一次 Ctrl+C 返回菜单、连续两次退出，二/三级菜单按一次 Ctrl+C 返回上级。

### 控制台输出示例

（`--fast` 模式节选，数值因网络而异；节点国旗在控制台显示为国家代码；测速阶段的逐节点结果行无时间戳）

```
2026-08-01 21:30:05 INFO  解析订阅: https://example.com/api/***
2026-08-01 21:30:06 INFO  UA curl/8.0 解析到 33 个节点
2026-08-01 21:30:08 INFO  [成功] 解析到 33 个节点
2026-08-01 21:30:09 INFO  [1/2] TCP Ping 延迟测试
2026-08-01 21:30:11 INFO  TCP 检测完成: 直连 26/33 可达
[1/33] [JP] 日本-东京-01                    45ms    21.3MB/s
[2/33] [HK] 香港-荃湾-02                    62ms    15.8MB/s
[3/33] [US] 美国-洛杉矶-03                 168ms     9.2MB/s
2026-08-01 21:33:52 INFO  测速完成: 成功 30/33 | 最快 34.5MB/s ([JP] 日本-东京-01) | 平均 8.1MB/s
2026-08-01 21:33:52 INFO  测试完成! 耗时 227 秒，共 33 个节点
2026-08-01 21:33:52 INFO  报告: output/测速结果_fast_20260801_213352.png
节点名称                          延迟    HTTP    平均       最大
[JP] 日本-东京-01                45ms   118ms   21.3MB/s   34.5MB/s
[HK] 香港-荃湾-02                62ms   151ms   15.8MB/s   28.1MB/s
[US] 美国-洛杉矶-03             168ms   201ms    9.2MB/s   12.6MB/s
... 共 33 个节点，完整结果见报告
```

## 测试流程

```
订阅URL(可多个,捕获subscription-userinfo) → 多UA尝试解析 → TCP检测(直连并发+重试3次丢包率 | mihomo隧道并发探测兜底)
→ HTTP测速(节点串行,每节点4连接多源聚合,8s窗口) → 补测超时节点(直连+隧道重试,恢复则补测速)
→ 流媒体解锁(前3服务预检+死节点跳过) → IP质量(多源回退) → 网页模拟(落地CN换国内站点)
→ 复用四档 → PNG + JSON 导出
```

## 报告术语解释

报告配色遵循直觉色（绿=快/好、红=慢/差），所有文字纯黑直绘、无描边，报告内不印图例；整格底色色块表达快慢好坏，数字只做精确读数。

### 配色含义（v4.32.0）

| 列 | 色块 |
|---|---|
| 延迟RTT / HTTP延迟 / 网页均耗 | 整格色块：≤50ms 绿 `#1E9650` → 500ms+ 深红 `#D2321E`（帧间线性插值）；`超时`/`--`/`UDP`/`代理可达` 为灰色块 |
| 平均/最高速度 | 整格色块：慢=深红 `#B42823` → 快=深绿 `#287341`；全表最大速度 <8MB/s 时色板在 0~最大速度间线性铺满（低端也能拉开色差），否则对数映射（突刺不把慢节点挤成一片红）；无速度时显示失败原因（斑马底黑字） |
| 流媒体 | 解锁/可用=深绿、失败/封锁/连接失败=深红、N/A=深青、未知=中灰、跳过(节点不可达)=灰蓝、未测=无底色 |
| IP类型 | 家宽/移动=绿、商宽/机房=黄、代理/VPN/Tor=红 |
| IP风险 | 低(<20)=绿、中(20-59)=黄、高(60+)=红 |
| 复用 | 完全复用=红、中转复用=黄、落地复用=青 |
| 每秒速度柱 | 柱色=绝对速度（与速度格同一色板）；柱高=行内起伏形状（不代表快慢） |

### 延迟与可达性列

| 显示 | 含义 |
|---|---|
| `32ms` | 本机直连该节点服务器的 TCP 握手延迟 |
| `超时` | 直连 TCP 握手无响应（重试后仍失败） |
| `代理可达` | 直连失败，但经 mihomo 隧道（该节点的真实协议通道）连通成功 |
| `UDP` | 该节点走 UDP/QUIC 传输（hysteria/tuic/wireguard 等），不做直连 TCP 检测，ping 列以 UDP 标注 |
| `HTTP延迟 --` | 延迟探测请求（gstatic）未得到 204 响应，或该节点无此数据 |

### UDP类型列

| 显示 | 含义 |
|---|---|
| `TCP` | 节点基于 TCP 传输（vmess/vless/trojan/ss/ssr/anytls 等） |
| `UDP` | WireGuard（UDP 传输） |
| `QUIC` | hysteria/hysteria2/tuic/juicity 或 vless 的 quic 传输层 |
| `KCP` | vmess/vless 的 kcp 传输层（基于 UDP） |

### 测速列

| 显示 | 含义 |
|---|---|
| `3.1MB/s` | 平均速度（已剥离首秒慢启动） |
| `5.9MB/s` | 峰值速度（8 秒窗口内最快的一秒） |
| `512KB/s` / `<1KB/s` | 速度不足 1MB/s 时改用 KB/s 显示（v4.32.0） |
| `速度过低` | 前 3 秒累计下载不足 64KB，判定为过慢提前终止 |
| `下载失败` | 8 秒窗口内下载总量不足 256KB（连接失败或拦截页） |
| `--` | 无数据（节点未进入测速队列或全部下载源失败） |
| 每秒速度柱状图 | 恒 7 根柱（任意长度采样重采样为 7 点）；柱高=行内 min-max 归一化（只表起伏形状）、柱色=绝对速度（红=慢→绿=快，与速度格同色板、跨行可比）、柱间 1px 白缝、无灰色背景；无每秒数组节点显示 7 根等高矮柱 |

### HTTP 状态码（流媒体列括号内的数字）

| 显示 | 含义 |
|---|---|
| `(400)` | 请求被服务端拒绝（请求格式/参数不被接受） |
| `(403)` | 拒绝访问——通常意味着该地区被封锁或风控拦截 |
| `(404)` | 页面/内容不存在（检测端点已失效） |
| `(429)` | 请求过于频繁，被限流（稍后重试可能成功） |
| `(500)`/`(502)`/`(503)` | 服务端错误或网关故障（多为服务自身问题，非节点问题） |

### 流媒体解锁状态

| 显示 | 含义 |
|---|---|
| `解锁(US)` | 检测到地区代码 US 且内容可播放（括号内为识别的地区） |
| `解锁` | 可播放但未能识别地区 |
| `解锁(港澳台)` | B站港澳台限定内容可播放 |
| `可用` | 平台可正常访问，但非"解锁级"内容判定（如普通网页可开） |
| `可用(CN)` | YouTube 被送中后普通 YouTube 仍可访问 |
| `仅自制剧` | Netflix 仅自制剧可看，非自制剧被限制 |
| `失败(区域限制)` | 内容因地区限制不可观看（节点地区不对） |
| `失败(风控)` | 平台风控/验证码拦截 |
| `失败(无Premium标识)` | YouTube 未检测到 Premium 标识 |
| `送中(CN)` | YouTube 被重定向到中国大陆版（google.cn） |
| `封锁` | 平台明确拒绝访问（403 或拦截页） |
| `错误(连接失败)` | 请求无法建立连接（节点可能不可达或超时） |
| `跳过(节点不可达)` | 该节点前 3 个服务全部连接失败，判定为死节点，其余服务不再实测 |

### IP 质量列（标准测试模式）

| 显示 | 含义 |
|---|---|
| `家宽 IP` | 住宅宽带出口 IP（较好） |
| `商宽/机房 IP` | 数据中心/商业出口 IP（多数机场为此类） |
| `低(0-19)` | IP 风控风险低 |
| `中(20-59)` | IP 风控风险中等（含机房/代理特征） |
| `高(60+)` | IP 风控风险高（Tor/滥用/多重代理特征） |
| `--` | 该列无数据（IP 检测失败或数据源不提供该字段） |
| ASN 列 | 出口 IP 的自治域号与所属组织 |
| `完全复用` | 该节点入口与落地 IP 都和其他节点相同（同一台服务器同一落地） |
| `中转复用` | 入口与其他节点相同、落地 IP 不同（同一台入口服务器中转） |
| `落地复用` | 入口不同、落地 IP 与其他节点相同（多个入口共用同一落地） |
| `网页均耗` | 网页模拟测速：4 个代表性站点首字节耗时的平均值（落地 CN 时换国内站点） |
| `312ms(1丢)` | 延迟 312ms 且 3 次 TCP 握手中失败 1 次（丢包/抖动提示） |

### 页眉与页脚

- 页眉第 1 行：`speed_test.py vX.Y.Z | 模式名`（居中加粗）；第 2 行：`订阅: N 节点 | 测试耗时: Xs`（左）、`排序: 排序名`（右）
- 页脚第 1 行：延迟术语说明（quick 模式为 `快速模式（并行近似测速）`）
- 页脚第 2 行：`节点: 26/33 可达 | 平均延迟: 234ms`（有 UDP 节点时追加 `UDP节点: 4 个(经HTTP实测)`）；`可达` = 直连成功 + 隧道探测成功之和 / 节点总数；`平均延迟` = 直连 TCP 成功节点的平均延迟
- 页脚第 3 行：`测试时间: YYYY-MM-DD HH:MM:SS (时区) | 本次实测下载 X`（左）、`Powered by speed_test.py vX.Y.Z`（右）

## 排序方式

直接回车 = 最大速度降序。可选：最大/平均速度升序或降序、节点名 A→Z / Z→A、订阅原始顺序。

## JSON 数据说明

每次测试同时导出同名 `.json`，包含每个节点的完整结果：

- `name` / `type` / `server` / `port` — 节点基本信息
- `udp_node` / `udp_type` — 是否 UDP 传输及传输层类型
- `tcp_ping_ms` — 直连 TCP 延迟（null=失败）
- `tcp_loss` — 3 次 TCP 握手的失败次数（0=无丢包；UDP 节点为 null）
- `tcp_probe` — 隧道探测结果（true/false/null=未探测）
- `http_latency_ms` / `speed_mbs` / `max_speed_mbs` — 延迟与速度
- `speed_per_sec_mbs` — 每秒速度数组（柱状图数据）
- `streaming` — 各平台检测结果（键为平台 id，值为状态文本）
- `ip_info` — IP 质量信息（含 risk_score/share_level/source/reuse 复用档位）
- `webpage` — 网页模拟测速均耗（毫秒；未检测为 null）
- `error` — 节点级错误（如"速度过低"）

## 常见问题

**为什么节点显示"超时"但实际能用？**
可能原因：本机网络到该节点服务器的直连路径被干扰；或节点是 UDP/QUIC 协议（直连 TCP 本就测不通）。工具会自动用 mihomo 隧道探测兜底并在报告末尾补测一轮，恢复的节点会补跑测速。

**为什么有的节点有速度但没有 HTTP 延迟？**
延迟探测走的是 gstatic 的 204 请求，个别节点对其不通，但下载源（Cloudflare/CacheFly/OVH）正常，此时只有速度数据。

**为什么同一节点两次测速数值不一样？**
测速结果受机场服务器端实时带宽影响（尤其晚高峰），波动 ±30% 属正常。工具已消除本机并发互扰和慢启动偏差，多次测速取稳定值更有参考意义。

**风险分高意味着什么？**
出口 IP 带有数据中心/代理/VPN 特征，访问风控严格的平台（如 Netflix 非自制剧、部分银行）更容易被要求验证或拒绝。换家宽/原生 IP 节点可改善。

**双击 run.bat 一闪而过？**
在 cmd 里运行 `python core/speed_test.py` 查看报错。常见原因：没装 Python、安装时没勾选 "Add to PATH"、依赖没装全（重新执行 `pip install -r core/requirements.txt`）。

**怎么把结果发给别人看？**
直接发 `output/` 文件夹里的 PNG 报告图片即可（可视化报告）。JSON 是结构化数据（进阶用），日志是排查问题时用的，一般不用发给别人。

**报告没有自动打开？**
报告文件都在 `output/` 文件夹里，双击最新的 `测速结果_*.png` 即可；也可以在菜单里选 `更多 → 5` 查看上次结果。

**运行报错了怎么办？**
把 `log/` 文件夹里最新的 `测速日志_*.jsonl` 文件发来即可——里面记录了运行环境（Python 版本/依赖版本）、每一步操作、每个节点的完整明细和报错堆栈，不用截图。

**首次运行提示 mihomo 下载失败？**
mihomo 内核需要从 GitHub 下载（约 47MB），国内网络可能失败。可以：1) 检查网络后重试；2) 手动下载 mihomo 的 Windows zip，把解压出的 `mihomo.exe` 放进 `bin/` 目录；3) 能上 GitHub 后运行菜单 `维护 → 1 更新内核`。

## 已知限制

- IP 质量检测依赖免费 API：ip-api.com 主源（免费版限 http，提供机房 `hosting`/公共代理 `proxy`/移动网络 `mobile` 标志与 ASN/ISP，实测经机场出口可用；限速 45 请求/分钟/出口 IP）；ipapi.is 回退（提供机房/代理/VPN/Tor/滥用标志与 ASN，但实测屏蔽多数机场出口 IP）；ipwho.is / api.ip.sb 为最后回退（免费版仅地理与 ASN，无风控字段，类型/风险显示 `--`）；风险分为工具本地启发式评分（0-100，机房+20/代理+25/VPN+20/Tor+35/滥用+25/爬虫+10），非第三方风控分；IP 类型显示五档：Tor 出口 / 代理/VPN IP / 商宽机房 IP / 移动网络 IP / 家宽 IP
- 本机无 IPv6 网络时，IPv6 节点必然测不通（工具已尽量探测标注，属环境限制）
- 报告最多显示前 300 个节点
- 油管下载源默认隐藏（`core/speed_test.py` 里 `YOUTUBE_SOURCE_ENABLED = False`）；如需启用第 4 个测速源（googlevideo 直链），改为 `True` 并安装 yt-dlp
- 测速会消耗节点流量（每节点约 10-30MB），"勿跑大流量"节点请谨慎全量测试
- 网页模拟测速会在标准/完整测试中为每个节点额外增加约 3-8 秒（4 站点并发、8 秒超时）；`--fast` 模式跳过
- TCP 丢包率为 3 次握手的失败计数，对瞬时抖动敏感，仅作参考
- 平台支持（v4.31.0）：Linux / macOS 未经实测——mihomo 内核自动下载已修复（Windows `.zip` / Linux/macOS `.gz` 格式，x86_64/arm64 架构，下载与解压路径已实测验证）；macOS 手动下载 mihomo 放入 `bin/` 会被 Gatekeeper 拦截（"无法验证开发者"），请用首次运行自动下载或菜单 `6 更新内核`；Linux 无图形界面时报告不会自动打开（`xdg-open` 不存在，不影响测试与手动查看 `output/`），无中文字体时 PNG 报告中文显示为方框（可安装 Noto Sans CJK）

### 隐私说明

- IP 质量检测经节点隧道发起，发送给 ip-api.com / ipapi.is / ipwho.is / api.ip.sb 的是**节点出口 IP**，不是你的真实 IP；你的真实 IP 仅暴露给订阅服务器、GitHub（内核下载）与可选开启的油管直连解析（Google）
- 日志（`log/`）中订阅 URL 的 token/password 等参数会被自动遮蔽；节点密码/UUID 不会写入日志与报告
- 工具无任何遥测或统计上报

## 更新记录与致谢

- 版本变更见 [CHANGELOG](CHANGELOG.md)（按 新增/修改/修复/移除 四栏记录，只陈述事实）
- 测速引擎：[mihomo](https://github.com/MetaCubeX/mihomo)（内核自动下载，无需手动配置）
- 复用检测、网页模拟的思路借鉴 [SSRSpeedN](https://github.com/PauperZ/SSRSpeedN)
- 遇到问题请到 [Issues](https://github.com/oscyfmau/airport-speedtest/issues) 反馈，附上 `log/` 文件夹里最新的 `测速日志_*.jsonl`（订阅链接请勿粘贴，含敏感 token）

## 文件结构

```
机场测速/
├── run.bat              # 启动脚本（唯一入口）
├── 代理.txt.example     # 订阅 URL 模板（复制为 代理.txt 使用）
├── 代理.txt             # 订阅 URL，每行一个（敏感，不入库）
├── core/
│   ├── speed_test.py    # 入口与兼容重导出（v4.10 起逻辑按模块拆分）
│   ├── config.py        # 常量（单一数据源）
│   ├── models.py        # 数据类
│   ├── utils.py         # 通用工具（URL 遮蔽/编码/SSL）
│   ├── logging_setup.py # 日志系统（控制台 + JSONL）
│   ├── procs.py         # mihomo 子进程管理
│   ├── state.py         # 运行时可变全局状态
│   ├── parser.py        # 订阅解析器
│   ├── engine.py        # mihomo 引擎 + TCP 检测
│   ├── tester.py        # HTTP 测速执行器
│   ├── streaming.py     # 流媒体解锁检测
│   ├── ip_quality.py    # IP 质量检测
│   ├── webpage.py       # 网页模拟测速
│   ├── report.py        # PNG 报告 / JSON 导出
│   ├── runner.py        # 测试流程编排
│   ├── cli.py           # 命令行入口与菜单
│   ├── image.py         # 兼容重导出（逻辑在 report.py）
│   └── requirements.txt # Python 依赖
├── bin/                 # mihomo 内核（自动下载，不入库）
├── output/              # PNG 报告 + JSON 数据（不入库）
├── log/                 # JSONL 运行日志（不入库，报错时发这个目录的文件）
├── docs/                # 文档：README×2 / CHANGELOG / LICENSE / 示例报告图 / 社交预览图
└── .gitignore           # 排除敏感文件与运行产物
```

## 许可证

MIT License，详见 [LICENSE](LICENSE)。
