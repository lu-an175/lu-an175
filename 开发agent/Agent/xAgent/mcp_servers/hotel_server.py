# -*- coding: utf-8 -*-
"""
xAgent.mcp_servers.hotel_server —— 酒店运营日报的数据源（MCP over stdio）。

定位
    只读数据源。酒店运营日报 agent 需要的一切数字都从这里取，
    永远不写业务库、不改房态、不动房价 —— 因此出错最坏情况是
    「报告里某个数不准」，而不是「把客人预订搞没了」。

六个工具
    get_daily_metrics        经营指标（入住率 / ADR / RevPAR / 收入拆解）
    get_channel_breakdown    渠道间夜、占比、佣金
    get_room_status          当日房态（预抵 / 预离 / 在住 / 空房 / 维修）
    get_ota_reviews          近期 OTA 客评（含待回复标记）
    get_competitor_rates     同商圈竞对价格
    save_report              把日报落盘到 <项目根>/reports/

数据来源
    1. 默认：按日期为种子生成的确定性 mock 数据（同一日期每次调用结果一致，
       方便回归对比，也不让模型看到前后矛盾的数字）
    2. 真实接入：设置环境变量 HOTEL_DATA_JSON 指向一个 JSON 文件，
       结构见 data_schema() 的说明，即可无缝替换掉 mock

传输
    stdio：stdin 一行一个 JSON-RPC，stdout 一行一个响应。日志一律走 stderr。

启动
    python -m xAgent.mcp_servers.hotel_server
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SERVER_INFO = {"name": "xagent-hotel", "version": "1.0.0"}
PROTOCOL_VERSION = "2025-06-18"

#: 酒店基础画像（客房数、房型、基准价）
#: 换酒店只改这一块：元组为 (房型名, 房间数, 基准房价)
ROOM_TYPES: Tuple[Tuple[str, int, int], ...] = (
    ("大床房", 56, 348),
    ("双床房", 42, 368),
    ("高级大床房", 18, 428),
    ("商务套房", 12, 588),
)

#: 渠道画像：(渠道名, 间夜占比, 佣金率)
CHANNELS: Tuple[Tuple[str, float, float], ...] = (
    ("携程", 0.28, 0.15),
    ("美团", 0.18, 0.12),
    ("飞猪", 0.12, 0.10),
    ("Booking", 0.06, 0.18),
    ("官网直订", 0.20, 0.00),
    ("协议客户", 0.12, 0.00),
    ("散客上门", 0.04, 0.00),
)

COMPETITORS: Tuple[str, ...] = ("锦江之星·人民路店", "如家精选·火车站店", "亚朵·广场店")

NEGATIVE_KEYWORDS = ("隔音", "卫生", "异味", "空调", "前台态度", "早餐", "热水", "停车")


# ============================================================
# 数据生成
# ============================================================

def _resolve_date(value: Optional[str]) -> date:
    """解析 YYYY-MM-DD；缺省为昨天（日报默认看昨天）。"""
    if not value:
        return date.today() - timedelta(days=1)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"date 需为 YYYY-MM-DD 格式，收到：{value}") from exc


def _rng(day: date, tag: str) -> random.Random:
    """按「日期 + 用途」派生独立随机源，保证同一天数据稳定可复现。"""
    return random.Random(f"{day.isoformat()}|{tag}")


def _weekday_factor(day: date) -> float:
    """出差城市的周内节律：周一至周四高，周五略降，周六最低，周日回升。"""
    return {0: 1.04, 1: 1.06, 2: 1.05, 3: 1.02, 4: 0.96, 5: 0.83, 6: 0.88}[day.weekday()]


def _external_data(day: date) -> Optional[Dict[str, Any]]:
    """真实数据接入点：HOTEL_DATA_JSON 里按日期查，命中就整段替换 mock。"""
    raw = os.environ.get("HOTEL_DATA_JSON", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_file():
        print(f"hotel_server: HOTEL_DATA_JSON 不存在：{path}", file=sys.stderr, flush=True)
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"hotel_server: 读取数据文件失败：{exc}", file=sys.stderr, flush=True)
        return None
    payload = blob.get(day.isoformat()) if isinstance(blob, dict) else None
    return payload if isinstance(payload, dict) else None


def _build_metrics(day: date) -> Dict[str, Any]:
    """生成某一天的经营指标（含昨日、上周同日的对比基线）。"""
    external = _external_data(day)
    if external:
        return external

    rng = _rng(day, "metrics")
    factor = _weekday_factor(day)
    base_occ = 0.795 * factor + rng.uniform(-0.035, 0.035)

    rooms: List[Dict[str, Any]] = []
    sold_total = 0
    room_total = 0
    revenue_room = 0

    for index, (name, count, ref_price) in enumerate(ROOM_TYPES):
        # 高房型（高级/套房）入住率通常更高，价格也更坚挺
        premium = 1.0 + index * 0.035
        occ = min(0.99, max(0.30, base_occ * premium + rng.uniform(-0.04, 0.04)))
        sold = int(round(count * occ))
        # 价格随入住率轻微上浮，但不会偏离基准太多
        price = ref_price * (0.94 + (occ - 0.7) * 0.45) + rng.uniform(-8, 8)
        price = round(price, 2)
        rooms.append(
            {
                "room_type": name,
                "total": count,
                "sold": sold,
                "occupancy": round(sold / count, 4),
                "adr": price,
                "revenue": round(sold * price, 2),
            }
        )
        sold_total += sold
        room_total += count
        revenue_room += sold * price

    # 非房收入：餐饮 + 会议 + 其他，通常占房收的 12%~22%
    fnb = revenue_room * rng.uniform(0.09, 0.14)
    meeting = revenue_room * rng.uniform(0.03, 0.08)
    misc = revenue_room * rng.uniform(0.01, 0.03)

    adr = revenue_room / sold_total if sold_total else 0.0
    occupancy = sold_total / room_total
    revpar = revenue_room / room_total

    return {
        "date": day.isoformat(),
        "weekday": "一二三四五六日"[day.weekday()],
        "room_total": room_total,
        "rooms_sold": sold_total,
        "occupancy": round(occupancy, 4),
        "adr": round(adr, 2),
        "revpar": round(revpar, 2),
        "revenue": {
            "room": round(revenue_room, 2),
            "fnb": round(fnb, 2),
            "meeting": round(meeting, 2),
            "misc": round(misc, 2),
            "total": round(revenue_room + fnb + meeting + misc, 2),
        },
        "by_room_type": rooms,
        # 对比基线由同一定价逻辑反算，保证前后一致
        "compare": {
            "prev_day": _compare_snapshot(day - timedelta(days=1)),
            "prev_week": _compare_snapshot(day - timedelta(days=7)),
        },
    }


def _compare_snapshot(day: date) -> Dict[str, Any]:
    """只算指标不递归，避免 prev_day 又去算 prev_day。"""
    external = _external_data(day)
    if external:
        return {
            "date": day.isoformat(),
            "occupancy": external.get("occupancy", 0.0),
            "adr": external.get("adr", 0.0),
            "revpar": external.get("revpar", 0.0),
            "revenue_total": (external.get("revenue") or {}).get("total", 0.0),
        }

    rng = _rng(day, "metrics")
    factor = _weekday_factor(day)
    base_occ = 0.795 * factor + rng.uniform(-0.035, 0.035)

    sold_total = 0
    room_total = 0
    revenue_room = 0.0
    for index, (_name, count, ref_price) in enumerate(ROOM_TYPES):
        premium = 1.0 + index * 0.035
        occ = min(0.99, max(0.30, base_occ * premium + rng.uniform(-0.04, 0.04)))
        sold = int(round(count * occ))
        price = ref_price * (0.94 + (occ - 0.7) * 0.45) + rng.uniform(-8, 8)
        sold_total += sold
        room_total += count
        revenue_room += sold * price

    fnb_rate = rng.uniform(0.09, 0.14) + rng.uniform(0.03, 0.08) + rng.uniform(0.01, 0.03)
    return {
        "date": day.isoformat(),
        "occupancy": round(sold_total / room_total, 4),
        "adr": round(revenue_room / sold_total, 2) if sold_total else 0.0,
        "revpar": round(revenue_room / room_total, 2),
        "revenue_total": round(revenue_room * (1 + fnb_rate), 2),
    }


def _build_channels(day: date) -> List[Dict[str, Any]]:
    """渠道拆解：间夜 / 占比 / 收入 / 佣金。占比会做微扰但总和归一到 1。"""
    external = _external_data(day)
    if external and isinstance(external.get("channels"), list):
        return external["channels"]

    metrics = _build_metrics(day)
    rooms_sold = metrics["rooms_sold"]
    adr = metrics["adr"]

    rng = _rng(day, "channels")
    raw = [max(0.005, share * (1 + rng.uniform(-0.18, 0.18))) for _n, share, _c in CHANNELS]
    scale = sum(raw)
    weights = [value / scale for value in raw]

    result: List[Dict[str, Any]] = []
    nights_left = rooms_sold
    for index, (name, _share, commission) in enumerate(CHANNELS):
        if index == len(CHANNELS) - 1:
            nights = max(0, nights_left)
        else:
            nights = int(round(rooms_sold * weights[index]))
            nights = min(nights, max(0, nights_left))
        nights_left -= nights
        revenue = round(nights * adr, 2)
        result.append(
            {
                "channel": name,
                "room_nights": nights,
                "share": round(nights / rooms_sold, 4) if rooms_sold else 0.0,
                "revenue": revenue,
                "commission_rate": commission,
                "commission": round(revenue * commission, 2),
            }
        )
    return result


def _build_room_status(day: date) -> Dict[str, Any]:
    """
    当日房态。

    口径（这一块最容易出错，改之前先读）：
        在住房 occupied  = 此刻已入住的房
        预抵 arrivals    = 今天还会来的房（尚未计入在住）
        当日售出          = occupied + arrivals
        今日可周转 available_rooms = 总房 - 在住 + 预离 - 维修 - 停用
        可售余量 sellable_rooms    = 今日可周转 - 预抵

    把「当前空房」直接当成「可售余量」是常见错误：预离的房今天会空出来，
    漏算这部分会让店长误判去化压力，做出过头的降价决策。
    """
    external = _external_data(day)
    if external and isinstance(external.get("room_status"), dict):
        return external["room_status"]

    metrics = _build_metrics(day)
    total = metrics["room_total"]
    sold = metrics["rooms_sold"]

    rng = _rng(day, "status")

    # 当日售出拆成「已在住」与「待抵店」
    arrivals = int(round(sold * rng.uniform(0.22, 0.32)))
    arrivals = min(arrivals, sold)
    occupied = sold - arrivals

    # 预离只能是当前在住的一部分
    departures = int(round(occupied * rng.uniform(0.18, 0.28)))
    departures = min(departures, occupied)

    maintenance = rng.choice([0, 0, 1, 1, 2, 3])
    out_of_order = rng.choice([0, 0, 0, 1])

    available = max(0, total - occupied + departures - maintenance - out_of_order)
    # 预抵不得超过今日可周转房，否则就是无法交付的超售
    arrivals = min(arrivals, available)
    sellable = max(0, available - arrivals)

    return {
        "date": day.isoformat(),
        "room_total": total,
        "occupied": occupied,
        "arrivals": arrivals,
        "departures": departures,
        "rooms_sold": occupied + arrivals,
        "available_rooms": available,
        "sellable_rooms": sellable,
        "maintenance": maintenance,
        "out_of_order": out_of_order,
        "long_stay": int(round(occupied * rng.uniform(0.08, 0.14))),
        "vip_arrivals": rng.choice([0, 1, 1, 2, 3]),
    }


POSITIVE_SNIPPETS = (
    "位置很好找，出门就是地铁，前台小姑娘很热情",
    "房间干净，床品很舒服，出差住了一周没换地方",
    "早餐种类比想象中多，有现煮面条",
    "隔音比同价位好很多，晚上睡得很安稳",
    "办理入住很快，还把行李送到了房间",
    "空调制冷快，热水出水也快",
)

NEGATIVE_SNIPPETS = (
    "房间隔音一般，走廊说话声能听见",
    "卫生间有返味，打扫得不够仔细",
    "空调噪音有点大，半夜被吵醒了",
    "前台办理入住排了很久队，态度也一般",
    "早餐九点半去基本没东西了，补餐太慢",
    "热水要放很久才热",
    "楼下停车位太少，绕了两圈才停进去",
)


def _build_reviews(day: date, days: int = 3) -> List[Dict[str, Any]]:
    """近 N 天的 OTA 客评。差评必须给出具体房号与渠道，便于门店定位。"""
    externals: List[Dict[str, Any]] = []
    external = _external_data(day)
    if external and isinstance(external.get("reviews"), list):
        return external["reviews"]

    reviews: List[Dict[str, Any]] = []
    seq = 0
    for offset in range(days):
        current = day - timedelta(days=offset)
        rng = _rng(current, "reviews")
        count = rng.choices([0, 1, 2, 3, 4, 5], weights=[12, 22, 26, 22, 13, 5])[0]
        for _ in range(count):
            seq += 1
            positive = rng.random() < 0.72
            if positive:
                content = rng.choice(POSITIVE_SNIPPETS)
                score = rng.choice([4.5, 5.0, 5.0, 4.8])
            else:
                keyword = rng.choice(NEGATIVE_KEYWORDS)
                content = next(
                    (item for item in NEGATIVE_SNIPPETS if keyword in item),
                    rng.choice(NEGATIVE_SNIPPETS),
                )
                score = rng.choice([2.0, 2.5, 3.0, 3.5])
            channel = rng.choices(
                ["携程", "美团", "飞猪", "Booking"], weights=[42, 26, 20, 12]
            )[0]
            reviews.append(
                {
                    "id": f"R{current.strftime('%m%d')}{seq:02d}",
                    "date": current.isoformat(),
                    "channel": channel,
                    "score": score,
                    "content": content,
                    "room_type": rng.choice([name for name, _c, _p in ROOM_TYPES]),
                    "replied": bool(offset > 0 and rng.random() < 0.75),
                    "urgent": (not positive) and score <= 3.0,
                }
            )
    return reviews


def _build_competitors(day: date) -> Dict[str, Any]:
    """同商圈竞对价格；本店价格直接沿用当天 ADR，保证与指标不打架。"""
    external = _external_data(day)
    if external and isinstance(external.get("competitors"), dict):
        return external["competitors"]

    metrics = _build_metrics(day)
    our_adr = metrics["adr"]
    rng = _rng(day, "competitors")

    peers = []
    for name in COMPETITORS:
        # 竞对围绕本店 ±18% 波动
        price = our_adr * (1 + rng.uniform(-0.18, 0.14))
        peers.append(
            {
                "name": name,
                "lowest_price": round(price * 0.88, 2),
                "avg_price": round(price, 2),
                "sold_out": rng.random() < 0.18,
            }
        )

    peer_avg = sum(item["avg_price"] for item in peers) / len(peers)
    return {
        "date": day.isoformat(),
        "our_adr": round(our_adr, 2),
        "peer_avg": round(peer_avg, 2),
        "gap_pct": round((our_adr - peer_avg) / peer_avg * 100, 2) if peer_avg else 0.0,
        "peers": peers,
    }


# ============================================================
# 输出格式化（给模型看的文本，不是原始 JSON）
# ============================================================

def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _money(value: float) -> str:
    return f"{value:,.0f}"


def _fmt_metrics(day: date) -> str:
    m = _build_metrics(day)
    prev = m["compare"]["prev_day"]
    week = m["compare"]["prev_week"]

    def delta(current: float, base: float, suffix: str = "") -> str:
        if not base:
            return "—"
        diff = current - base
        rate = diff / base * 100
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
        if suffix == "%":
            return f"{arrow} {abs(diff) * 100:.1f}pct"
        return f"{arrow} {abs(rate):.1f}%"

    lines = [
        f"【{m['date']} 周{m['weekday']} 经营指标】",
        f"客房总数 {m['room_total']} 间 / 售出 {m['rooms_sold']} 间夜",
        "",
        "指标        当日        昨日    环比        上周同日  同比",
        f"入住率      {_pct(m['occupancy'])}    {_pct(prev['occupancy'])}   "
        f"{delta(m['occupancy'], prev['occupancy'], '%')}    "
        f"{_pct(week['occupancy'])}   {delta(m['occupancy'], week['occupancy'], '%')}",
        f"ADR        {m['adr']:.0f}          {prev['adr']:.0f}      "
        f"{delta(m['adr'], prev['adr'])}      {week['adr']:.0f}       "
        f"{delta(m['adr'], week['adr'])}",
        f"RevPAR     {m['revpar']:.0f}          {prev['revpar']:.0f}      "
        f"{delta(m['revpar'], prev['revpar'])}      {week['revpar']:.0f}       "
        f"{delta(m['revpar'], week['revpar'])}",
        "",
        "收入拆解：",
        f"  客房  {_money(m['revenue']['room'])}",
        f"  餐饮  {_money(m['revenue']['fnb'])}",
        f"  会议  {_money(m['revenue']['meeting'])}",
        f"  其他  {_money(m['revenue']['misc'])}",
        f"  合计  {_money(m['revenue']['total'])}  "
        f"(昨日 {_money(prev['revenue_total'])}, "
        f"{delta(m['revenue']['total'], prev['revenue_total'])})",
        "",
        "分房型：",
    ]
    for item in m["by_room_type"]:
        lines.append(
            f"  {item['room_type']:<8} {item['sold']:>3}/{item['total']:<3} "
            f"入住率 {_pct(item['occupancy'])}  ADR {item['adr']:.0f}  "
            f"房收 {_money(item['revenue'])}"
        )
    return "\n".join(lines)


def _fmt_channels(day: date) -> str:
    rows = _build_channels(day)
    total_nights = sum(item["room_nights"] for item in rows) or 1
    total_commission = sum(item["commission"] for item in rows)

    lines = [f"【{day.isoformat()} 渠道拆解】", ""]
    lines.append("渠道        间夜   占比     收入        佣金")
    for item in rows:
        lines.append(
            f"{item['channel']:<10} {item['room_nights']:>4}   "
            f"{_pct(item['share']):>6}   {_money(item['revenue']):>10}   "
            f"{_money(item['commission']):>8}"
        )
    lines.append("")
    lines.append(f"合计间夜 {total_nights}，佣金支出 {_money(total_commission)}")
    ota_share = sum(
        item["share"] for item in rows if item["commission_rate"] > 0
    )
    direct_share = sum(
        item["share"] for item in rows if item["channel"] in ("官网直订", "协议客户")
    )
    lines.append(f"OTA 占比 {_pct(ota_share)}，直销占比 {_pct(direct_share)}")
    return "\n".join(lines)


def _fmt_room_status(day: date) -> str:
    s = _build_room_status(day)
    return "\n".join(
        [
            f"【{s['date']} 房态】",
            f"总房量 {s['room_total']}",
            f"在住 {s['occupied']}",
            f"今日预抵 {s['arrivals']}",
            f"今日预离 {s['departures']}",
            f"今日售出合计 {s['rooms_sold']}",
            f"今日可周转房 {s['available_rooms']}"
            f"（总房 - 在住 + 预离 - 维修 - 停用）",
            f"可售余量 {s['sellable_rooms']}（可周转房扣掉预抵后，今天还能卖的）",
            f"维修房 {s['maintenance']}",
            f"停用房 {s['out_of_order']}",
            f"长住客 {s['long_stay']}",
            f"VIP 预抵 {s['vip_arrivals']}",
        ]
    )


def _fmt_reviews(day: date, days: int) -> str:
    reviews = _build_reviews(day, days)
    if not reviews:
        return f"【{days} 天内无新客评】"

    scores = [item["score"] for item in reviews]
    negative = [item for item in reviews if item["score"] <= 3.5]
    pending = [item for item in reviews if not item["replied"]]

    lines = [
        f"【近 {days} 天 OTA 客评】",
        f"新增 {len(reviews)} 条，均分 {sum(scores) / len(scores):.2f}，"
        f"差评 {len(negative)} 条，未回复 {len(pending)} 条",
        "",
    ]
    for item in reviews:
        flag = "⚠" if item["urgent"] else ("·" if not item["replied"] else " ")
        lines.append(
            f"{flag} {item['date']} {item['channel']} {item['score']:.1f}分 "
            f"{item['room_type']}：{item['content']}"
        )
    return "\n".join(lines)


def _fmt_competitors(day: date) -> str:
    c = _build_competitors(day)
    lines = [
        f"【{c['date']} 竞对价格】",
        f"本店 ADR {c['our_adr']:.0f}，商圈均价 {c['peer_avg']:.0f}，"
        f"价差 {c['gap_pct']:+.1f}%",
        "",
    ]
    for peer in c["peers"]:
        status = "（已满房）" if peer["sold_out"] else ""
        lines.append(
            f"  {peer['name']:<18} 最低 {peer['lowest_price']:.0f}  "
            f"均价 {peer['avg_price']:.0f}{status}"
        )
    return "\n".join(lines)


# ============================================================
# 工具定义
# ============================================================

_DATE_PROP = {
    "type": "string",
    "description": "统计日期，YYYY-MM-DD；不传默认昨天",
}

TOOLS = [
    {
        "name": "get_daily_metrics",
        "description": (
            "取某天的经营指标：客房总数、售出间夜、入住率、ADR、RevPAR、"
            "收入拆解（客房/餐饮/会议/其他）、分房型表现，"
            "以及相对昨日和上周同日的对比。生成运营日报时第一个调用它。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"date": _DATE_PROP},
        },
    },
    {
        "name": "get_channel_breakdown",
        "description": (
            "取某天的渠道拆解：各渠道间夜、占比、收入、佣金率与佣金支出，"
            "并给出 OTA 占比与直销占比。用于分析渠道结构和佣金成本。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"date": _DATE_PROP},
        },
    },
    {
        "name": "get_room_status",
        "description": (
            "取某天的房态：在住、预抵、预离、可售空房、维修房、停用房、"
            "长住客、VIP 预抵。用于判断当日接待压力与可售余量。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"date": _DATE_PROP},
        },
    },
    {
        "name": "get_ota_reviews",
        "description": (
            "取近 N 天 OTA 客评明细：渠道、评分、内容、房型、是否已回复、"
            "是否需紧急处理（3 分及以下）。返回汇总均分与差评数。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": _DATE_PROP,
                "days": {
                    "type": "integer",
                    "description": "往回看几天，默认 3，最大 30",
                    "minimum": 1,
                    "maximum": 30,
                },
            },
        },
    },
    {
        "name": "get_competitor_rates",
        "description": (
            "取某天同商圈竞对价格：各竞对最低价、均价、是否满房，"
            "以及本店 ADR 与商圈均价的价差百分比。用于判断定价空间。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"date": _DATE_PROP},
        },
    },
    {
        "name": "save_report",
        "description": (
            "把日报正文写入 <项目根>/reports/ 目录。filename 只允许字母数字、"
            "中文、下划线和连字符，自动补 .md 后缀。已存在时覆盖。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "文件名，如 2026-11-10-运营日报",
                },
                "content": {
                    "type": "string",
                    "description": "日报 Markdown 正文",
                },
            },
            "required": ["filename", "content"],
        },
    },
]


def _text(value: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": value}]}


def _error(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


_SAFE_NAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


def _safe_filename(name: str) -> str:
    """只留字母数字、下划线、连字符和中文；其余替换成下划线。"""
    cleaned = "".join(
        ch if (ch in _SAFE_NAME_CHARS or "\u4e00" <= ch <= "\u9fff") else "_"
        for ch in name.strip()
    ).strip("_")
    if not cleaned:
        cleaned = f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if not cleaned.lower().endswith(".md"):
        cleaned += ".md"
    return cleaned


def _reports_dir() -> Path:
    # 项目根 = 运行时 cwd（与 Skill / 会话目录同一套约定）
    target = Path.cwd() / "reports"
    target.mkdir(parents=True, exist_ok=True)
    return target


def call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if name == "get_daily_metrics":
            return _text(_fmt_metrics(_resolve_date(arguments.get("date"))))

        if name == "get_channel_breakdown":
            return _text(_fmt_channels(_resolve_date(arguments.get("date"))))

        if name == "get_room_status":
            return _text(_fmt_room_status(_resolve_date(arguments.get("date"))))

        if name == "get_ota_reviews":
            day = _resolve_date(arguments.get("date"))
            days = arguments.get("days", 3)
            try:
                days = int(days)
            except (TypeError, ValueError):
                days = 3
            days = max(1, min(30, days))
            return _text(_fmt_reviews(day, days))

        if name == "get_competitor_rates":
            return _text(_fmt_competitors(_resolve_date(arguments.get("date"))))

        if name == "save_report":
            filename = arguments.get("filename", "")
            content = arguments.get("content", "")
            if not isinstance(content, str) or not content.strip():
                return _error("content 不能为空")
            target = _reports_dir() / _safe_filename(str(filename))
            target.write_text(content, encoding="utf-8")
            return _text(f"已保存：{target}（{len(content)} 字符）")

    except ValueError as exc:
        return _error(str(exc))
    except OSError as exc:
        return _error(f"读写失败：{exc}")

    return _error(f"未知工具：{name}")


# ============================================================
# JSON-RPC 循环
# ============================================================

def handle(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": message.get("params", {}).get(
                "protocolVersion", PROTOCOL_VERSION
            ),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        result = call_tool(params.get("name", ""), params.get("arguments") or {})
    elif method == "ping":
        result = {}
    elif method and method.startswith("notifications/"):
        return None
    else:
        if request_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print(f"bad json: {line[:80]}", file=sys.stderr, flush=True)
            continue

        response = handle(message)
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
