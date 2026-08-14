> Language / 语言: [English](README_EN.md) | [中文](README.md)

# Airport Speed Test

Pull all nodes from an airport subscription, test latency, speed, streaming unlock and IP quality in one go, and get a visual report automatically. No need to understand mihomo config — you'll know which node to use.

[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![Release](https://img.shields.io/github/v/release/oscyfmau/airport-speedtest?style=flat-square)](https://github.com/oscyfmau/airport-speedtest/releases)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Downloads](https://img.shields.io/github/downloads/oscyfmau/airport-speedtest/total?style=flat-square)](https://github.com/oscyfmau/airport-speedtest/releases)

Version: v4.9.0 | Repository: [github.com/oscyfmau/airport-speedtest](https://github.com/oscyfmau/airport-speedtest) | [Changelog](CHANGELOG.md)

> This project was written by AI and developed for personal needs — take it as-is.

## Preview

![Sample speed test report](preview_report.png)

(Sample report; data is for demonstration purposes)

## Quick Start (3 Steps, No Command Line Skills Needed)

1. **Download**: open the [Releases page](https://github.com/oscyfmau/airport-speedtest/releases), download the latest `Source code (zip)` and unzip it (if you know git you can also `git clone`)
2. **Fill in the subscription**: in the unzipped folder, copy `代理.txt.example`, rename it to `代理.txt`, open it with Notepad, paste your subscription link and save
   - What is a subscription link? A URL provided by your airport service provider (usually starts with `https://` and contains all node info); get it from the "Copy subscription" option on the airport website or in the client app
3. **Run**:
   - Install Python 3.9+ ([python.org](https://www.python.org/downloads/), check "Add python.exe to PATH" during installation)
   - In the unzipped folder run `pip install -r core/requirements.txt`
   - Double-click `run.bat` → select `1` Simple speed test in the menu → wait a few minutes → the PNG report opens automatically (report files are in the `output/` folder, logs are in the `log/` folder)

The mihomo core downloads automatically on first run to `bin/` (about 47MB) — no manual download needed.

> [!IMPORTANT]
> Subscription links contain account tokens: `代理.txt` stays local only (already in .gitignore) — never share it publicly. The tool itself also auto-masks subscription tokens in logs and exception records.

> [!NOTE]
> Speed tests consume node traffic (about 10-30MB per node); standard tests also run a web page simulation per node (about 3-8 extra seconds). For nodes marked "no heavy traffic", use `--fast` or avoid full tests.

## Features

- Protocol parsing: 20+ protocols (vmess / vless / trojan / ss / ssr / hysteria2 / tuic / wireguard / anytls etc.), multiple subscription URLs merged and de-duplicated
- TCP latency: local direct handshake + mihomo tunnel probe cross-check; packet loss counted across 3 handshakes (latency column shows `312ms(1lost)`)
- Speed test: nodes tested serially without interference; 4 connections per node across 3 download sources (Cloudflare/CacheFly/OVH); 8s window, first-second slow start stripped
- Streaming unlock: 34 platforms, 11 dedicated detectors (Netflix/Disney/YouTube/Bilibili TW-HK-MO/TikTok/Steam etc.); dead nodes skipped early
- IP quality: type (residential/DC) + ASN + risk score 0-100; ipapi.is primary, ipwho.is / api.ip.sb fallback
- Reuse detection in 4 tiers: full reuse / transit reuse / exit reuse — spot shared airport lines at a glance (inspired by SSRSpeedN)
- Traffic multiplier: subscription metered-traffic delta ÷ actually downloaded bytes — verify whether the airport inflates traffic
- Web page simulation: 4 representative sites loaded concurrently, first-byte latency recorded; CN exits auto-switch to domestic sites (Baidu/Bilibili/Tencent)
- Retest mechanism: timed-out nodes are retested before the report; recovered nodes get a re-run speed test
- Output: PNG visual report (bar charts / risk colors / reuse marks) + JSON data + JSONL structured logs (subscription tokens auto-masked)

## Installation & Running

### Environment Requirements

- Windows / Linux / macOS
- Python 3.9+
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

Double-click `run.bat` for the interactive menu, or run directly from the command line:

| Command | Description |
|---|---|
| `python core/speed_test.py` | Interactive menu (same as double-clicking run.bat) |
| `python core/speed_test.py <URL>` | Direct speed test (simple mode: TCP ping + HTTP speed) |
| `python core/speed_test.py <URL> --full` | Full test (+ streaming unlock + IP quality + web page simulation) |
| `python core/speed_test.py <URL> --fast` | Fast mode (5s speed window / skip IP check) |
| `python core/speed_test.py <URL> --workers N` | Streaming/IP/webpage parallelism (1-8, default 4; speed tests always serial) |
| `python core/speed_test.py --report` | Open the last report |
| `python core/speed_test.py --menu` | Force show the menu |
| `python core/speed_test.py -h` | Show help |

```bash
python core/speed_test.py https://your-subscription --fast   # quick scan in ~5 minutes
python core/speed_test.py https://your-subscription --full   # full report
```

Subscription URLs are read by default from `代理.txt` at the project root (one URL per line). The repo does not include this file: copy `代理.txt.example` to `代理.txt` and fill it in (it is already in .gitignore, so it will not be committed by mistake).

### Menu Mode

| Option | Description |
|---|---|
| 1. Simple speed test | TCP detection + HTTP speed test (fastest) |
| 2. Standard test | Speed test + 9 common streaming platforms + IP quality + web page simulation |
| 3. AI streaming | 8 AI platform checks |
| 4. All streaming | All 34 platforms |
| 5. View last result | Open the latest PNG report in the output folder |
| 6. Update core | Download the latest mihomo core (download first, then replace) |
| 7. Exit | Exit the program |

### Sample Console Output

(Excerpt from a `--fast` run; values vary by network. Node flags display as country codes in the console.)

```
2026-08-01 21:30:05 INFO  Parsed: 33 nodes (vmess 20 / vless 8 / trojan 5)
2026-08-01 21:30:09 INFO  TCP detection done: 26/33 reachable, avg latency 128ms
2026-08-01 21:30:10 INFO  [JP] 日本-东京-01 latency 45ms, starting speed test
2026-08-01 21:30:22 INFO  [JP] 日本-东京-01 avg 21.3MB/s, peak 34.5MB/s
2026-08-01 21:30:23 INFO  [HK] 香港-荃湾-02 latency 62ms, starting speed test
2026-08-01 21:30:36 INFO  [HK] 香港-荃湾-02 avg 15.8MB/s, peak 28.1MB/s
2026-08-01 21:30:37 INFO  [US] 美国-洛杉矶-03 latency 168ms, starting speed test
2026-08-01 21:30:50 INFO  [US] 美国-洛杉矶-03 avg 9.2MB/s, peak 12.6MB/s
2026-08-01 21:33:52 INFO  Test finished in 3m 47s
2026-08-01 21:33:52 INFO  Report saved: output/测速结果_fast_20260801_213352.png
2026-08-01 21:33:52 INFO  JSON saved: output/测速结果_fast_20260801_213352.json
```

## Test Flow

```
Subscription URL(s) (captures subscription-userinfo) → parse with multiple UA attempts → TCP detection (direct concurrent + 3 retries for loss | mihomo tunnel concurrent probe)
→ HTTP speed test (nodes serial, 4 connections per node, multi-source aggregation, 8s window) → retest timed-out nodes (direct + tunnel retry, recovered nodes re-tested)
→ streaming unlock (pre-check first 3 services, skip dead nodes) → IP quality (multi-source fallback) → web page simulation (CN exit switches to domestic sites)
→ reuse tiers + traffic multiplier (re-fetch subscription header) → PNG + JSON export
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
| `Full reuse` | Both entry and egress IP are shared with other nodes (same server, same exit) |
| `Transit reuse` | Entry shared with other nodes but different egress IP (same entry server) |
| `Exit reuse` | Different entry but egress IP shared with other nodes (one exit for many entries) |
| `Web Avg` | Web page simulation: average first-byte latency of 4 representative sites (CN exit uses domestic sites) |
| `312ms(1lost)` | 312ms latency with 1 failed TCP handshake out of 3 (packet loss hint) |

### Footer Statistics

- `Nodes: 26/33 reachable` — direct-connect successes + tunnel-probe successes / total nodes
- `Average latency` — average latency of nodes with successful direct TCP
- `UDP nodes: 4 (verified via HTTP)` — number of UDP-type nodes (their reachability is determined by tunnel probing)
- `Traffic multiplier: 1.02` — subscription-server metered traffic delta ÷ actually downloaded bytes (≈1 means no inflation; requires the server to return the `subscription-userinfo` header)
- `Test duration` — total time of the whole test round

## Sorting

Pressing Enter directly = maximum speed descending. Options: maximum/average speed ascending or descending, node name A→Z / Z→A, original subscription order.

## JSON Data

Each test also exports a same-named `.json` containing the complete result for every node:

- `name` / `type` / `server` / `port` — node basic info
- `udp_node` / `udp_type` — whether it uses UDP transport and the transport layer type
- `tcp_ping_ms` — direct TCP latency (null = failed)
- `tcp_loss` — failed handshakes out of 3 (0 = no loss; null for UDP nodes)
- `tcp_probe` — tunnel probe result (true/false/null = not probed)
- `http_latency_ms` / `speed_mbs` / `max_speed_mbs` — latency and speed
- `speed_per_sec_mbs` — per-second speed array (bar chart data)
- `streaming` — detection result per platform (key = platform id, value = status text)
- `ip_info` — IP quality info (incl. risk_score/share_level/source/reuse tier)
- `webpage` — web page simulation average latency (ms; null if not tested)
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

**What should I do if it errors out?**
Send the latest `测速日志_*.jsonl` from the `log/` folder; it records the runtime environment (Python version / dependency versions), every step, per-node details and the full traceback — no screenshots needed.

**First run says mihomo download failed?**
The mihomo core is downloaded from GitHub (~47MB) and may fail on some networks. You can: 1) check your network and retry; 2) manually download the mihomo Windows zip and put the extracted `mihomo.exe` into the `bin/` folder; 3) once GitHub is reachable, run menu option `6 Update core`.

## Known Limitations

- IP quality detection depends on free APIs: ipapi.is is the primary source (provides datacenter/proxy/VPN/Tor/abuser flags and ASN; the free API has no mobile-network flag, so residential includes mobile); ipwho.is / api.ip.sb are fallbacks (free tier provides only geo and ASN — no risk-control fields, type/risk shown as `--`); the risk score is a local heuristic (0-100: datacenter+20/proxy+25/VPN+20/Tor+35/abuser+25/crawler+10), not a third-party fraud score
- Without IPv6 on the local machine, IPv6 nodes will inevitably fail to test (the tool probes and marks them as much as possible; this is an environment limitation)
- The report shows at most the first 300 nodes
- The YouTube download source is hidden by default (`YOUTUBE_SOURCE_ENABLED = False` in `core/speed_test.py`); set it to `True` and install yt-dlp to enable the 4th speed-test source (googlevideo direct link)
- Speed tests consume node traffic (about 10-30MB per node); be cautious about running full tests on "no heavy traffic" nodes
- Traffic multiplier requires the subscription server to return the `subscription-userinfo` header (most mainstream airport panels do) and metered traffic updates may lag — treat it as a reference only
- Web page simulation adds about 3-8 seconds per node in standard/full tests (4 sites concurrently, 8s timeout); skipped in `--fast` mode
- TCP packet loss counts failures across 3 handshakes and is sensitive to transient jitter — reference only

## Changelog & Credits

- Version history in [CHANGELOG](CHANGELOG.md) (Added/Changed/Fixed/Removed columns, facts only)
- Speed test engine: [mihomo](https://github.com/MetaCubeX/mihomo) (core auto-downloaded, no manual config)
- Reuse detection, web page simulation and traffic multiplier inspired by [SSRSpeedN](https://github.com/PauperZ/SSRSpeedN)
- Report issues at [Issues](https://github.com/oscyfmau/airport-speedtest/issues) with the latest `测速日志_*.jsonl` from the `log/` folder (never paste subscription links — they contain sensitive tokens)

## File Structure

```
机场测速/
├── run.bat              # launch script (single entry point)
├── 代理.txt.example     # subscription URL template (copy to 代理.txt to use)
├── 代理.txt             # subscription URLs, one per line (sensitive, not committed)
├── .github/
│   └── ISSUE_TEMPLATE/  # bug report and feature request forms
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
├── output/              # PNG reports + JSON data (not committed)
├── log/                 # JSONL runtime logs (not committed; send files here when reporting errors)
├── docs/                # docs: README×2 / CHANGELOG / LICENSE / sample report image / social preview image
└── .gitignore           # excludes sensitive files and runtime artifacts
```

## License

MIT License, see [LICENSE](LICENSE).
