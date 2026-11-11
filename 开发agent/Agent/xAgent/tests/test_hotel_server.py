# -*- coding: utf-8 -*-
"""
hotel_server 的单元测试。

覆盖三类风险：
  1. 数据确定性 —— 同一天反复调用结果必须一致，否则日报前后数字会打架
  2. 输出可用性 —— 每个工具都得返回非空文本、不能是 isError
  3. 落盘安全 —— 文件名清洗要拦住路径穿越，内容为空要拒绝
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from xAgent.mcp_servers import hotel_server as hs  # noqa: E402


def _body(result: dict) -> str:
    return result["content"][0]["text"]


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 11, 10)

    def test_metrics_text_contains_core_fields(self):
        text = _body(hs.call_tool("get_daily_metrics", {"date": self.day.isoformat()}))
        for token in ("入住率", "ADR", "RevPAR", "收入拆解", "分房型"):
            self.assertIn(token, text)

    def test_metrics_is_deterministic(self):
        args = {"date": self.day.isoformat()}
        first = _body(hs.call_tool("get_daily_metrics", args))
        second = _body(hs.call_tool("get_daily_metrics", args))
        self.assertEqual(first, second)

    def test_different_days_differ(self):
        a = _body(hs.call_tool("get_daily_metrics", {"date": "2026-11-10"}))
        b = _body(hs.call_tool("get_daily_metrics", {"date": "2026-11-11"}))
        self.assertNotEqual(a, b)

    def test_weekend_lower_than_weekday(self):
        """周内节律：周三入住率应高于周六。"""
        wed = hs._build_metrics(date(2026, 11, 11))
        sat = hs._build_metrics(date(2026, 11, 14))
        self.assertGreater(wed["occupancy"], sat["occupancy"])

    def test_room_nights_never_exceed_capacity(self):
        for offset in range(14):
            day = self.day + timedelta(days=offset)
            m = hs._build_metrics(day)
            self.assertLessEqual(m["rooms_sold"], m["room_total"])
            for item in m["by_room_type"]:
                self.assertLessEqual(item["sold"], item["total"])
                self.assertGreaterEqual(item["sold"], 0)

    def test_default_date_is_yesterday(self):
        text = _body(hs.call_tool("get_daily_metrics", {}))
        expected = (date.today() - timedelta(days=1)).isoformat()
        self.assertIn(expected, text)

    def test_bad_date_reports_error(self):
        result = hs.call_tool("get_daily_metrics", {"date": "2026/11/10"})
        self.assertTrue(result.get("isError"))
        self.assertIn("YYYY-MM-DD", _body(result))


class TestChannels(unittest.TestCase):
    def test_shares_sum_to_one(self):
        day = date(2026, 11, 10)
        rows = hs._build_channels(day)
        total = sum(item["share"] for item in rows)
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_room_nights_match_metrics(self):
        day = date(2026, 11, 10)
        rows = hs._build_channels(day)
        metrics = hs._build_metrics(day)
        self.assertEqual(sum(item["room_nights"] for item in rows), metrics["rooms_sold"])

    def test_direct_channels_have_no_commission(self):
        rows = hs._build_channels(date(2026, 11, 10))
        for item in rows:
            if item["channel"] in ("官网直订", "协议客户"):
                self.assertEqual(item["commission"], 0)


class TestRoomStatus(unittest.TestCase):
    def test_status_internally_consistent(self):
        """房态各项必须自洽：预抵不能超过可周转房，可售余量不能为负。"""
        for offset in range(30):
            s = hs._build_room_status(date(2026, 11, 10) + timedelta(days=offset))
            self.assertGreaterEqual(s["sellable_rooms"], 0)
            self.assertGreaterEqual(s["available_rooms"], 0)
            self.assertGreaterEqual(s["maintenance"], 0)
            self.assertLessEqual(s["arrivals"], s["available_rooms"])
            self.assertLessEqual(s["departures"], s["occupied"])
            self.assertLessEqual(s["occupied"] + s["arrivals"], s["room_total"])
            self.assertEqual(
                s["available_rooms"] - s["arrivals"], s["sellable_rooms"]
            )

    def test_sellable_is_not_just_vacant(self):
        """可售余量要算上今日预离腾出的房，不能等于「总房 - 在住」。"""
        s = hs._build_room_status(date(2026, 11, 10))
        naive_vacant = s["room_total"] - s["occupied"]
        self.assertGreaterEqual(s["available_rooms"], naive_vacant - s["maintenance"] - s["out_of_order"])

    def test_text_lists_all_rows(self):
        text = _body(hs.call_tool("get_room_status", {"date": "2026-11-10"}))
        for token in ("在住", "预抵", "预离", "可周转房", "可售余量", "维修房", "VIP"):
            self.assertIn(token, text)


class TestReviews(unittest.TestCase):
    def test_days_clamped(self):
        text = _body(hs.call_tool("get_ota_reviews", {"date": "2026-11-10", "days": 999}))
        self.assertIn("近 30 天", text)

    def test_days_invalid_falls_back(self):
        text = _body(hs.call_tool("get_ota_reviews", {"date": "2026-11-10", "days": "abc"}))
        self.assertIn("客评", text)

    def test_negative_reviews_present(self):
        """十天里至少要能抓到差评，否则日报的口碑段无从写起。"""
        reviews = hs._build_reviews(date(2026, 11, 10), 10)
        self.assertTrue(any(item["score"] <= 3.5 for item in reviews))


class TestCompetitors(unittest.TestCase):
    def test_our_adr_matches_metrics(self):
        day = date(2026, 11, 10)
        comp = hs._build_competitors(day)
        metrics = hs._build_metrics(day)
        self.assertAlmostEqual(comp["our_adr"], metrics["adr"], places=2)

    def test_gap_sign_matches_prices(self):
        comp = hs._build_competitors(date(2026, 11, 10))
        if comp["our_adr"] > comp["peer_avg"]:
            self.assertGreater(comp["gap_pct"], 0)
        else:
            self.assertLessEqual(comp["gap_pct"], 0)


class TestSaveReport(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_writes_file_and_adds_suffix(self):
        result = hs.call_tool(
            "save_report", {"filename": "2026-11-10-运营日报", "content": "# 日报\n内容"}
        )
        self.assertFalse(result.get("isError"))
        target = Path(self._tmp.name) / "reports" / "2026-11-10-运营日报.md"
        self.assertTrue(target.is_file())
        self.assertIn("内容", target.read_text(encoding="utf-8"))

    def test_path_separators_are_stripped(self):
        hs.call_tool(
            "save_report",
            {"filename": "../../evil/../../report", "content": "x"},
        )
        reports = Path(self._tmp.name) / "reports"
        written = [p.name for p in reports.iterdir()]
        self.assertEqual(len(written), 1)
        self.assertNotIn("/", written[0])
        self.assertNotIn("..", written[0])
        self.assertFalse((Path(self._tmp.name).parent / "evil").exists())

    def test_empty_content_rejected(self):
        result = hs.call_tool("save_report", {"filename": "a", "content": "   "})
        self.assertTrue(result.get("isError"))

    def test_empty_filename_gets_fallback(self):
        hs.call_tool("save_report", {"filename": "///", "content": "x"})
        written = list((Path(self._tmp.name) / "reports").iterdir())
        self.assertEqual(len(written), 1)
        self.assertTrue(written[0].name.startswith("report-"))


class TestProtocol(unittest.TestCase):
    def test_initialize(self):
        resp = hs.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(resp["result"]["serverInfo"]["name"], "xagent-hotel")

    def test_tools_list_has_six(self):
        resp = hs.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {tool["name"] for tool in resp["result"]["tools"]}
        self.assertEqual(
            names,
            {
                "get_daily_metrics",
                "get_channel_breakdown",
                "get_room_status",
                "get_ota_reviews",
                "get_competitor_rates",
                "save_report",
            },
        )

    def test_every_tool_has_schema(self):
        for tool in hs.TOOLS:
            self.assertIn("inputSchema", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertTrue(tool["description"])

    def test_notification_gets_no_reply(self):
        self.assertIsNone(
            hs.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

    def test_unknown_method_returns_error(self):
        resp = hs.handle({"jsonrpc": "2.0", "id": 9, "method": "nope"})
        self.assertEqual(resp["error"]["code"], -32601)

    def test_call_tool_via_protocol(self):
        resp = hs.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_room_status", "arguments": {"date": "2026-11-10"}},
            }
        )
        self.assertNotIn("isError", resp["result"])
        self.assertIn("房态", resp["result"]["content"][0]["text"])


class TestExternalData(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "data.json"
        payload = {
            "2026-12-01": {
                "date": "2026-12-01",
                "weekday": "二",
                "room_total": 100,
                "rooms_sold": 80,
                "occupancy": 0.8,
                "adr": 500.0,
                "revpar": 400.0,
                "revenue": {"room": 40000, "fnb": 4000, "meeting": 1000,
                            "misc": 500, "total": 45500},
                "by_room_type": [],
                "compare": {
                    "prev_day": {"date": "2026-11-30", "occupancy": 0.75, "adr": 480,
                                 "revpar": 360, "revenue_total": 43000},
                    "prev_week": {"date": "2026-11-24", "occupancy": 0.78, "adr": 490,
                                  "revpar": 382, "revenue_total": 44000},
                },
            }
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_external_json_overrides_mock(self):
        old = os.environ.get("HOTEL_DATA_JSON")
        os.environ["HOTEL_DATA_JSON"] = str(self.path)
        try:
            m = hs._build_metrics(date(2026, 12, 1))
            self.assertEqual(m["room_total"], 100)
            self.assertEqual(m["adr"], 500.0)
        finally:
            if old is None:
                os.environ.pop("HOTEL_DATA_JSON", None)
            else:
                os.environ["HOTEL_DATA_JSON"] = old

    def test_missing_file_falls_back_to_mock(self):
        old = os.environ.get("HOTEL_DATA_JSON")
        os.environ["HOTEL_DATA_JSON"] = str(Path(self._tmp.name) / "nope.json")
        try:
            m = hs._build_metrics(date(2026, 12, 1))
            self.assertEqual(m["room_total"], sum(c for _n, c, _p in hs.ROOM_TYPES))
        finally:
            if old is None:
                os.environ.pop("HOTEL_DATA_JSON", None)
            else:
                os.environ["HOTEL_DATA_JSON"] = old


if __name__ == "__main__":
    unittest.main()
