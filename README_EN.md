> Language / 语言: [English](README_EN.md) | [中文](README.md)

# Airport Speed Test Tool

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/oscyfmau/airport-speedtest)](https://github.com/oscyfmau/airport-speedtest/releases)

Airport subscription speed-test tool: pull all nodes from a subscription URL, test TCP latency, HTTP download speed, streaming unlock and IP risk per node, then generate a visual PNG report + JSON data.

Version: v4.7 | Repository: https://github.com/oscyfmau/airport-speedtest

## Preview

![Sample speed test report](assets/preview_report.png)

(Sample report; data is for demonstration purposes)

## Quick Start (3 Steps, No Command Line Skills Needed)

1. **Download**: open the [Releases page](https://github.com/oscyfmau/airport-speedtest/releases), download the latest `Source code (zip)` and unzip it (if you know git you can also `git clone`)
2. **Fill in the subscription**: in the unzipped folder, copy `代理.txt.example`, rename it to `代理.txt`, open it with Notepad, paste your subscription link and save
   - What is a subscription link? A URL provided by your airport service provider (usually starts with `https://` and contains all node info); get it from the "Copy subscription" option on the airport website or in the client app
3. **Run**:
   - Install Python 3.8+ ([python.org](https://www.python.org/downloads/), check "Add python.exe to PATH" during installation)
   - In the unzipped folder run `pip install -r core/requirements.txt`
   - Double-click `run.bat` → select `1` Simple speed test in the menu → wait a few minutes → the PNG report opens automatically (report files are in the `output/` folder)

The mihomo core downloads automatically on first run to `bin/` (about 47MB) — no manual download needed.

## Features

- Supports parsing 20 protocol types: vmess / vless / trojan / ss / ssr / hysteria2 / hysteria / tuic / anytls / wireguard / naive / shadowtls / juicity / ssh / socks / http etc.
- Supports merging multiple subscription URLs into one speed test (代理.txt one per line; the -i file also supports multiple lines)
- TCP detection with dual sources: local direct handshake + mihomo tunnel probe cross-check, reducing misjudgment
- Nodes are tested serially; each node uses 4 concurrent connections with 4 download sources aggregated (Cloudflare/CacheFly/OVH + YouTube googlevideo direct link, stable and reliable values)
- Streaming unlock detection: 34 platforms, 11 with dedicated detectors (incl. Bilibili TW/HK/MO, TikTok, Steam etc.)
- IP risk: ipapi.is primary source with automatic fallback to ipwho.is / api.ip.sb
- Automatically retests timed-out nodes before report generation; recovered nodes get a re-run speed test
- Full logging: console INFO + file DEBUG (output/测速日志_*.log), subscription tokens auto-masked
- Console progress bar refreshes every second; node flags show as country codes (e.g. [JP]) in the console, while the PNG report still shows the flags
- Output: PNG visual report + JSON structured data

## Installation & Running

### Environment Requirements

- Windows / Linux / macOS
- Python 3.8+
- Dependencies: `pip install -r core/requirements.txt`
- The mihomo core downloads automatically on first run to `bin/` (about 47MB), no manual download needed

### Getting the Code

Either of the two ways:

- No git: go to the [Releases page](https://github.com/oscyfmau/airport-speedtest/releases), download the latest `Source code (zip)` and unzip it
- With git:

```bash
git clone https://github.com/oscyfmau/airport-speedtest.git
cd airport-speedtest
pip install -r core/requirements.txt
```

### How to Run

Double-click `run.bat` (or use the command line):

```bash
cd 机场测速 && python core/speed_test.py              # interactive menu
cd 机场测速 && python core/speed_test.py <URL>         # direct speed test (simple mode)
cd 机场测速 && python core/speed_test.py <URL> --full  # full speed test
cd 机场测速 && python core/speed_test.py <URL> --fast  # fast mode (5s window / skip IP check)
cd 机场测速 && python core/speed_test.py <URL> --workers N  # streaming/IP parallelism (1-8, default 4)
cd 机场测速 && python core/speed_test.py --report      # open last report
cd 机场测速 && python core/speed_test.py --menu        # force show menu
cd 机场测速 && python core/speed_test.py -h            # help
```

Subscription URLs are read by default from `代理.txt` at the project root (one URL per line). The repo does not include this file: copy `代理.txt.example` to `代理.txt` and fill it in (it is already in .gitignore, so it will not be committed by mistake).

### Menu Mode

| Option | Description |
|---|---|
| 1. Simple speed test | TCP detection + HTTP speed test (fastest) |
| 2. Standard test | Speed test + 9 common streaming platforms + IP quality |
| 3. AI streaming | 8 AI platform checks |
| 4. All streaming | All 34 platforms |

## Test Flow

```
Subscription URL → parse with multiple UA attempts → TCP detection (direct concurrent + retry | mihomo tunnel concurrent probe)
→ HTTP speed test (nodes serial, 4 connections per node, multi-source aggregation, 8s window)
→ retest timed-out nodes (direct + tunnel retry, recovered nodes get a re-test)
→ streaming unlock (pre-check first 3 services, skip dead nodes) → IP quality (multi-source fallback)
→ PNG + JSON export
```

## Report Terminology

### Latency & Reachability Column

| Display | Meaning |
|---|---|
| `32ms` | TCP handshake latency of the local machine directly connecting to the node's server |
| `Timeout` | Direct TCP handshake got no response (still fails after retry) |
| `Proxy reachable` | Direct connection failed, but connected successfully via the mihomo tunnel (the node's real protocol channel) |
| `UDP` | The node uses UDP/QUIC transport (hysteria/tuic/wireguard etc.), no direct TCP check; the ping column is marked UDP |
| `HTTP latency --` | The latency probe request (gstatic) did not return a 204 response, or this node has no such data |

### UDP Type Column

| Display | Meaning |
|---|---|
| `TCP` | Node based on TCP transport (vmess/vless/trojan/ss/ssr/anytls etc.) |
| `UDP` | WireGuard (UDP transport) |
| `QUIC` | hysteria/hysteria2/tuic/juicity, or vless with QUIC transport |
| `KCP` | vmess/vless with KCP transport (UDP-based) |

### Speed Test Column

| Display | Meaning |
|---|---|
| `3.1MB/s` | Average speed (first-second slow start excluded) |
| `5.9MB/s` | Peak speed (fastest second within the 8s window) |
| `Speed too low` | Cumulative download in the first 3 seconds below 64KB; judged too slow and terminated early |
| `Download failed` | Total download in the 8s window below 256KB (connection failure or block page) |
| `--` | No data (node never entered the speed test queue, or all download sources failed) |
| Per-second speed bar chart | Height = relative ratio of the node's own per-second speeds (shows in-row variation); color = absolute speed grading, the faster the greener, the slower the redder |

### HTTP Status Codes (numbers in parentheses in the streaming column)

| Display | Meaning |
|---|---|
| `(400)` | Request rejected by the server (request format/parameters not accepted) |
| `(403)` | Access denied — usually means the region is blocked or intercepted by risk control |
| `(404)` | Page/content does not exist (the check endpoint is obsolete) |
| `(429)` | Too many requests, rate limited (a later retry may succeed) |
| `(500)`/`(502)`/`(503)` | Server error or gateway failure (mostly the service's own problem, not the node's) |

### Streaming Unlock Status

| Display | Meaning |
|---|---|
| `解锁(US)` — Unlocked (region US) | Region code US detected and content playable (value in parentheses is the detected region) |
| `解锁` — Unlocked | Playable but region not identified |
| `解锁(港澳台)` — Unlocked (region TW/HK/MO) | Bilibili TW/HK/MO exclusive content playable |
| `可用` — Available | Platform accessible normally, but not judged as "unlock-level" content (e.g. a regular web page opens) |
| `可用(CN)` — Available (CN) | Regular YouTube still accessible after YouTube is CN-redirected |
| `仅自制剧` — Originals only | Netflix originals only; non-originals are restricted |
| `失败(区域限制)` — Failed (region restricted) | Content not watchable due to region restriction (node region mismatch) |
| `失败(风控)` — Failed (risk control) | Platform risk control / captcha blocking |
| `失败(无Premium标识)` — Failed (no Premium badge) | YouTube Premium badge not detected |
| `送中(CN)` — CN redirect (region CN) | YouTube redirected to the mainland China version (google.cn) |
| `封锁` — Blocked | Platform explicitly refuses access (403 or block page) |
| `错误(连接失败)` — Error (connection failed) | Request could not establish a connection (node may be unreachable or timed out) |
| `跳过(节点不可达)` — Skipped (node unreachable) | First 3 services all failed to connect for this node; judged as a dead node, remaining services not actually tested |

### IP Quality Column (standard test mode)

| Display | Meaning |
|---|---|
| `Residential IP` | Residential broadband egress IP (better) |
| `Business/DC IP` | Datacenter/commercial egress IP (most airports are this type) |
| `Low (0-19)` | Low IP risk |
| `Medium (20-59)` | Medium IP risk (datacenter/proxy characteristics) |
| `High (60+)` | High IP risk (Tor/abuse/multi-proxy characteristics) |
| `--` | No data for this column (IP check failed or the data source does not provide this field) |
| ASN column | Autonomous system number and organization of the egress IP |

### Footer Statistics

- `Nodes: 26/33 reachable` — direct-connect successes + tunnel-probe successes / total nodes
- `Average latency` — average latency of nodes with successful direct TCP
- `UDP nodes: 4 (verified via HTTP)` — number of UDP-type nodes (their reachability is determined by tunnel probing)
- `Test duration` — total time of the whole test round

## Sorting

Pressing Enter directly = maximum speed descending. Options: maximum/average speed ascending or descending, node name A→Z / Z→A, original subscription order.

## JSON Data

Each test also exports a same-named `.json` containing the complete result for every node:

- `name` / `type` / `server` / `port` — node basic info
- `udp_node` / `udp_type` — whether it uses UDP transport and the transport layer type
- `tcp_ping_ms` — direct TCP latency (null = failed)
- `tcp_probe` — tunnel probe result (true/false/null = not probed)
- `http_latency_ms` / `speed_mbs` / `max_speed_mbs` — latency and speed
- `speed_per_sec_mbs` — per-second speed array (bar chart data)
- `streaming` — detection result per platform (key = platform id, value = status text)
- `ip_info` — IP quality info (incl. risk_score/share_level/source)
- `error` — node-level error (e.g. "speed too low")

## FAQ

**Why does a node show "Timeout" but actually works?**
Possible reasons: the direct path from your local network to the node's server is interfered with; or the node uses a UDP/QUIC protocol (direct TCP cannot be tested anyway). The tool automatically falls back to mihomo tunnel probing and runs an extra retest round at the end of the report; recovered nodes get a re-run speed test.

**Why do some nodes have speed but no HTTP latency?**
The latency probe uses a 204 request to gstatic; some nodes do not respond to it, but the download sources (Cloudflare/CacheFly/OVH) work normally — in that case only speed data exists.

**Why do two speed tests on the same node give different values?**
Results are affected by real-time bandwidth on the airport server side (especially during evening peak); a ±30% fluctuation is normal. The tool removes local concurrent interference and slow-start bias, so taking the stable value from multiple tests is more meaningful.

**What does a high risk score mean?**
The egress IP carries datacenter/proxy/VPN characteristics, so platforms with strict risk control (e.g. Netflix non-originals, some banks) are more likely to demand verification or deny access. Switching to residential/native IP nodes can help.

**Double-clicking run.bat closes immediately?**
Run `python core/speed_test.py` in cmd to see the error message. Common causes: Python not installed, "Add to PATH" not checked during installation, dependencies not fully installed (re-run `pip install -r core/requirements.txt`).

**How do I share the results with others?**
Just send the PNG report image in the `output/` folder (the visual report). JSON is structured data (for advanced use), and logs are for troubleshooting — normally you don't need to send them.

**The report didn't open automatically?**
All report files are in the `output/` folder: double-click the latest `测速结果_*.png`, or select `5` in the menu to view the last result.

## Known Limitations

- IP quality detection depends on free APIs (ipapi.is primary, ipwho.is / api.ip.sb fallback); sources without risk-control fields do not fabricate risk values (shown as `--`)
- Without IPv6 on the local machine, IPv6 nodes will inevitably fail to test (the tool probes and marks them as much as possible; this is an environment limitation)
- The report shows at most the first 300 nodes
- Speed tests consume node traffic (about 10-30MB per node); be cautious about running full tests on "no heavy traffic" nodes

## File Structure

```
机场测速/
├── run.bat              # launch script (single entry point)
├── 代理.txt.example     # subscription URL template (copy to 代理.txt to use)
├── 代理.txt             # subscription URLs, one per line (sensitive, not committed)
├── README.md            # Chinese README
├── README_EN.md         # English README (this file)
├── assets/
│   └── preview_report.png # sample report image (demo data)
├── CHANGELOG.md         # version change log
├── LICENSE              # MIT license
├── .gitignore           # excludes sensitive files and runtime artifacts
├── core/
│   ├── speed_test.py    # all core logic (single source of truth)
│   ├── config.py        # constants re-export
│   ├── models.py        # dataclasses re-export
│   ├── parser.py        # parser re-export
│   ├── engine.py        # engine re-export
│   ├── tester.py        # tester re-export
│   ├── image.py         # image generation re-export
│   └── requirements.txt # Python dependencies
├── bin/                 # mihomo core (auto-downloaded, not committed)
└── output/              # PNG reports + JSON data + speed test logs (not committed)
```

## License

MIT License, see [LICENSE](LICENSE).
