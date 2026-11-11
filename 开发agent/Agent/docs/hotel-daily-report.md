# 酒店运营日报

用 xAgent 生成酒店日度经营简报。**不改 core 一行代码** —— 数据走 MCP，
口径走 Skill，两个都是 xAgent 已经设计好的扩展点。

## 三个部件

| 文件 | 作用 |
|---|---|
| `xAgent/mcp_servers/hotel_server.py` | 数据源，6 个只读工具，stdio MCP |
| `.agents/skills/hotel-daily-report/SKILL.md` | 日报口径：八段结构、判断阈值、文风、禁止事项 |
| `xAgent/tests/test_hotel_server.py` | 30 个用例，覆盖确定性、房态自洽、文件名清洗、协议层 |

## 启用

在**项目根**（跑 xAgent 的目录）的 `config.ini` 里加两段：

```ini
[mcp]
enabled = true
servers = hotel

[mcp:hotel]
transport = stdio
command = python
args = -m xAgent.mcp_servers.hotel_server
enabled = true
timeout = 20
```

重启 xAgent，侧栏「MCP 服务器」里应出现 `hotel`，工具名为
`mcp__hotel__get_daily_metrics` 等 6 个。

## 使用

在 TUI 里直接说人话：

```
帮我生成昨天的运营日报
```

模型会先 `loadSkill("hotel-daily-report")` 读口径，再依次调 5 个取数工具，
按八段结构写完后调 `save_report` 落盘到 `<cwd>/reports/{日期}-运营日报.md`。

也可以指定日期或缩短周期：

```
生成 11 月 8 号的日报
出一下上周的经营简报
只看客评，最近 7 天
```

## 六个工具

| 工具 | 返回 |
|---|---|
| `get_daily_metrics` | 入住率 / ADR / RevPAR / 收入拆解 / 分房型，含昨日与上周同日对比 |
| `get_channel_breakdown` | 各渠道间夜、占比、收入、佣金，OTA 与直销占比 |
| `get_room_status` | 在住 / 预抵 / 预离 / 可周转房 / 可售余量 / 维修 / VIP |
| `get_ota_reviews` | 近 N 天客评明细，标出紧急与未回复 |
| `get_competitor_rates` | 本店与商圈均价价差、各竞对最低价与满房状态 |
| `save_report` | 写进 `<cwd>/reports/`，文件名自动清洗 |

房态口径（最容易搞错，别混）：

- **可周转房** = 总房 − 在住 + 预离 − 维修 − 停用
- **可售余量** = 可周转房 − 预抵 ← 报告里应该用这个

## 换成真实数据

默认是 mock：以日期为种子生成，**同一天反复调用结果完全一致**，
方便对账，也不会让模型看到前后矛盾的数字。

接真实数据只需设置一个环境变量，指向按日期索引的 JSON：

```bash
set HOTEL_DATA_JSON=D:\hotel\daily.json
```

```json
{
  "2026-11-10": {
    "date": "2026-11-10",
    "weekday": "二",
    "room_total": 128,
    "rooms_sold": 112,
    "occupancy": 0.875,
    "adr": 397.4,
    "revpar": 347.7,
    "revenue": {"room": 44511, "fnb": 4969, "meeting": 2983, "misc": 938, "total": 53401},
    "by_room_type": [],
    "channels": [],
    "room_status": {},
    "reviews": [],
    "competitors": {},
    "compare": {
      "prev_day":  {"date": "2026-11-09", "occupancy": 0.828, "adr": 390, "revpar": 323, "revenue_total": 48308},
      "prev_week": {"date": "2026-11-03", "occupancy": 0.883, "adr": 401, "revpar": 354, "revenue_total": 52800}
    }
  }
}
```

字段缺失时该工具会回落到 mock，不会整体崩掉。文件不存在会在 stderr 打一行警告然后继续用 mock。

真正接入 PMS 时，建议不要改这个 server，而是**另写一个 MCP server 包住 PMS 的 API**，
把这个当成接口契约的参考实现 —— 模型看到的文本格式保持一致，Skill 就不用动。

## 已知限制

- **只读。** 六个工具都不写业务库，这是刻意设计：日报出错最坏是被骂两句，不会把预订搞没。
- 房态按「当天已售间夜」拆在住与预抵，不区分实际入住时刻，对日报够用，做实时房态看板不够。
- 竞对价格是 mock，真实场景要靠爬虫或第三方数据源，注意合规。
- 没有定时调度。xAgent 目前只有 TUI 交互模式，要做「每天早上 7 点自动跑」得另外加。

## 验证

```bash
cd Agent
python -m unittest xAgent.tests.test_hotel_server -v
```

样例产出见 `Agent/reports/2026-11-10-运营日报.md`（mock 数据生成）。
