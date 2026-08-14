> 语言 / Language: [中文](README.md) | [English](README_EN.md)

# 机场测速工具

把机场订阅 URL 里的所有节点拉下来，逐节点测试 TCP 延迟、HTTP 下载速度、流媒体解锁和 IP 风控，最后生成可视化 PNG 报告 + JSON 数据。

Airport subscription speed-test tool: pull all nodes from a subscription URL, test TCP latency, HTTP download speed, streaming unlock and IP risk per node, then generate a visual PNG report + JSON data.

版本：v4.7

仓库：https://github.com/oscyfmau/airport-speedtest

## 特性

- 支持 20 种协议解析：vmess / vless / trojan / ss / ssr / hysteria2 / hysteria / tuic / anytls / wireguard / naive / shadowtls / juicity / ssh / socks / http 等
- 支持多个订阅 URL 合并测速（代理.txt 每行一个，-i 文件同样支持多行）
- TCP 检测双来源：本机直连握手 + 经 mihomo 隧道探测互验，减少误判
- 测速节点串行、单节点 4 路并发连接 + 4 个下载源聚合（Cloudflare/CacheFly/OVH + 油管 googlevideo 直链，数值稳定可靠）
- 流媒体解锁检测：34 个平台，11 个平台有专用检测器（含 B站港澳台、TikTok、Steam 等）
- IP 风控：ipapi.is 主源 + ipwho.is / api.ip.sb 自动回退
- 报告前自动补测超时节点，恢复的节点补跑测速
- 全程日志：控制台 INFO + 文件 DEBUG（output/测速日志_*.log），订阅 token 自动遮蔽
- 控制台进度条每秒刷新一次；节点国旗在控制台显示为国家代码（如 [JP]），PNG 报告仍显示国旗
- 输出：PNG 可视化报告 + JSON 结构化数据

## 安装与运行

### 环境要求

- Windows / Linux / macOS
- Python 3.8+
- 依赖：`pip install -r core/requirements.txt`
- mihomo 内核无需手动下载，首次运行时自动下载到 `bin/`（约 47MB）

### 获取代码

```bash
git clone https://github.com/oscyfmau/airport-speedtest.git
cd airport-speedtest
pip install -r core/requirements.txt
```

### 运行方式

双击 `run.bat`（或命令行）：

```bash
cd 机场测速 && python core/speed_test.py              # 交互菜单
cd 机场测速 && python core/speed_test.py <URL>         # 直接测速（简单模式）
cd 机场测速 && python core/speed_test.py <URL> --full  # 完整测速
cd 机场测速 && python core/speed_test.py <URL> --fast  # 快速模式(5s窗口/跳过IP检测)
cd 机场测速 && python core/speed_test.py <URL> --workers N  # 流媒体/IP并行数(1-8,默认4)
cd 机场测速 && python core/speed_test.py --report      # 打开上次报告
cd 机场测速 && python core/speed_test.py --menu        # 强制显示菜单
cd 机场测速 && python core/speed_test.py -h            # 帮助
```

订阅 URL 默认从项目根目录的 `代理.txt` 读取（每行一个 URL）。仓库不含该文件：复制 `代理.txt.example` 为 `代理.txt` 后填写（已加入 .gitignore，不会误传）。

### 菜单模式

| 选项 | 说明 |
|---|---|
| 1. 简单测速 | TCP 检测 + HTTP 测速（最快） |
| 2. 标准测试 | 测速 + 9 个常用流媒体 + IP 质量 |
| 3. AI 流媒体 | 8 个 AI 平台检测 |
| 4. 全部流媒体 | 34 个平台全测 |

## 测试流程

```
订阅URL → 多UA尝试解析 → TCP检测(直连并发+重试 | mihomo隧道并发探测) 
→ HTTP测速(节点串行,每节点4连接多源聚合,8秒窗口) 
→ 补测超时节点(直连+隧道重试,恢复则补测速) 
→ 流媒体解锁(前3服务预检,死节点跳过) → IP质量(多源回退) 
→ PNG + JSON 导出
```

## 报告术语解释

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
| `速度过低` | 前 3 秒累计下载不足 64KB，判定为过慢提前终止 |
| `下载失败` | 8 秒窗口内下载总量不足 256KB（连接失败或拦截页） |
| `--` | 无数据（节点未进入测速队列或全部下载源失败） |
| 每秒速度柱状图 | 高度=该节点自身秒速的相对比例（看行内起伏）；颜色=绝对速度分级，越快越绿、越慢越红 |

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

### 页脚统计

- `节点: 26/33 可达` — 直连成功 + 隧道探测成功之和 / 节点总数
- `平均延迟` — 直连 TCP 成功节点的平均延迟
- `UDP节点: 4 个(经HTTP实测)` — UDP 系节点数（其可达性由隧道探测判定）
- `测试耗时` — 整轮测试用时

## 排序方式

直接回车 = 最大速度降序。可选：最大/平均速度升序或降序、节点名 A→Z / Z→A、订阅原始顺序。

## JSON 数据说明

每次测试同时导出同名 `.json`，包含每个节点的完整结果：

- `name` / `type` / `server` / `port` — 节点基本信息
- `udp_node` / `udp_type` — 是否 UDP 传输及传输层类型
- `tcp_ping_ms` — 直连 TCP 延迟（null=失败）
- `tcp_probe` — 隧道探测结果（true/false/null=未探测）
- `http_latency_ms` / `speed_mbs` / `max_speed_mbs` — 延迟与速度
- `speed_per_sec_mbs` — 每秒速度数组（柱状图数据）
- `streaming` — 各平台检测结果（键为平台 id，值为状态文本）
- `ip_info` — IP 质量信息（含 risk_score/share_level/source）
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

## 已知限制

- IP 质量检测依赖免费 API（ipapi.is 主源，ipwho.is / api.ip.sb 回退），无风控字段的源不编造风险值（显示 `--`）
- 本机无 IPv6 网络时，IPv6 节点必然测不通（工具已尽量探测标注，属环境限制）
- 报告最多显示前 300 个节点
- 测速会消耗节点流量（每节点约 10-30MB），"勿跑大流量"节点请谨慎全量测试

## 文件结构

```
机场测速/
├── run.bat              # 启动脚本（唯一入口）
├── 代理.txt.example     # 订阅 URL 模板（复制为 代理.txt 使用）
├── 代理.txt             # 订阅 URL，每行一个（敏感，不入库）
├── README.md            # 中文使用说明（本文件）
├── README_EN.md         # English README
├── CHANGELOG.md         # 版本变更记录
├── LICENSE              # MIT 协议
├── .gitignore           # 排除敏感文件与运行产物
├── core/
│   ├── speed_test.py    # 全部核心逻辑（单一数据源）
│   ├── config.py        # 常量重导出
│   ├── models.py        # 数据类重导出
│   ├── parser.py        # 解析器重导出
│   ├── engine.py        # 引擎重导出
│   ├── tester.py        # 测试器重导出
│   ├── image.py         # 图片生成重导出
│   └── requirements.txt # Python 依赖
├── bin/                 # mihomo 内核（自动下载，不入库）
└── output/              # PNG 报告 + JSON 数据 + 测速日志（不入库）
```

## 许可证

MIT License，详见 [LICENSE](LICENSE)。
