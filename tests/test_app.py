"""Basic smoke tests for the efficiency app."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models
import feishu_api
import lark_reader
from app import app, _build_dashboard_rows


def test_db_init():
    models.init_db()
    snapshots = models.list_snapshots()
    assert isinstance(snapshots, list), "list_snapshots should return a list"


def test_find_column():
    rows = [["评估链接", "一轮-领取人", "一轮是否评估完成", "二轮-领取人", "二轮是否评估完成"]]
    assert lark_reader._find_column(rows, ["一轮-领取人"]) == 1
    assert lark_reader._find_column(rows, ["二轮是否评估完成"]) == 4
    assert lark_reader._find_column(rows, ["不存在"]) is None


def test_parse_sheet_counts_completed_tasks_by_round():
    rows = [
        ["评估链接", "一轮-领取人", "一轮是否评估完成", "二轮-领取人", "二轮是否评估完成"],
        ["任务1", "张三", "是", "李四", "否"],
        ["", "", "", "", ""],
        ["", "", "", "", ""],
        ["任务2", "张三", "否", "李四", "是"],
        ["", "", "", "", ""],
        ["", "", "", "", ""],
    ]
    merges = [
        {"start_row_index": 1, "end_row_index": 3, "start_column_index": 1, "end_column_index": 1},
        {"start_row_index": 1, "end_row_index": 3, "start_column_index": 2, "end_column_index": 2},
        {"start_row_index": 1, "end_row_index": 3, "start_column_index": 3, "end_column_index": 3},
        {"start_row_index": 1, "end_row_index": 3, "start_column_index": 4, "end_column_index": 4},
        {"start_row_index": 4, "end_row_index": 6, "start_column_index": 1, "end_column_index": 1},
        {"start_row_index": 4, "end_row_index": 6, "start_column_index": 2, "end_column_index": 2},
        {"start_row_index": 4, "end_row_index": 6, "start_column_index": 3, "end_column_index": 3},
        {"start_row_index": 4, "end_row_index": 6, "start_column_index": 4, "end_column_index": 4},
    ]

    result = sorted(lark_reader.parse_sheet(rows, merges))

    assert result == [
        ("张三", "一轮", 1, 2),
        ("李四", "二轮", 1, 2),
    ]


def test_parse_progress_workers_stops_at_total():
    rows = [
        ["作业进度"],
        ["张三"],
        ["李四"],
        ["总计"],
        ["不应计入"],
    ]

    assert lark_reader.parse_progress_workers(rows) == ["张三", "李四"]


def test_select_sheets_scans_all_assignment_sheets_and_progress():
    sheets = [
        {"sheet_id": "day1", "title": "5.17评估数据"},
        {"sheet_id": "day2", "title": "评估数据"},
        {"sheet_id": "practice", "title": "练习题"},
        {"sheet_id": "special", "title": "专项作业A"},
        {"sheet_id": "progress", "title": "作业进度"},
        {"sheet_id": "trash", "title": "抛弃"},
        {"sheet_id": "template", "title": "作业模版（勿）"},
    ]

    assignment, progress = lark_reader._select_sheets(sheets)

    assert [s["sheet_id"] for s in assignment] == ["day1", "day2", "practice", "special"]
    assert [s["sheet_id"] for s in progress] == ["progress"]


def test_create_sheet_accepts_camel_case_sheet_id():
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "code": 0,
                "data": {
                    "replies": [{
                        "addSheet": {
                            "properties": {
                                "sheetId": "abc123",
                            }
                        }
                    }]
                },
            }

    original_headers = feishu_api._headers
    original_post = feishu_api.requests.post
    try:
        feishu_api._headers = lambda: {}
        feishu_api.requests.post = lambda *args, **kwargs: FakeResponse()
        assert feishu_api.create_sheet("spreadsheet_token", "导出") == "abc123"
    finally:
        feishu_api._headers = original_headers
        feishu_api.requests.post = original_post


def test_dashboard_export_requires_destination_url():
    models.init_db()
    client = app.test_client()
    response = client.post("/dashboard/export", data={"from_id": "1", "to_id": "2", "dest_url": ""})
    assert response.status_code == 302


def test_dashboard_rows_only_include_worker_list():
    original_agg = models.get_snapshot_worker_agg
    original_info = models.get_worker_info_map
    try:
        models.get_snapshot_worker_agg = lambda snapshot_id: [
            {"worker_name": "名单内", "completed": 5},
            {"worker_name": "名单外", "completed": 7},
        ]
        models.get_worker_info_map = lambda: {
            "名单内": {"company": "CL", "hours": 8.0},
        }

        rows = _build_dashboard_rows(1, 2)

        assert [r["worker_name"] for r in rows] == ["名单内"]
    finally:
        models.get_snapshot_worker_agg = original_agg
        models.get_worker_info_map = original_info


if __name__ == "__main__":
    test_db_init()
    test_find_column()
    test_parse_sheet_counts_completed_tasks_by_round()
    test_parse_progress_workers_stops_at_total()
    test_select_sheets_scans_all_assignment_sheets_and_progress()
    test_create_sheet_accepts_camel_case_sheet_id()
    test_dashboard_export_requires_destination_url()
    test_dashboard_rows_only_include_worker_list()
    print("All tests passed")
