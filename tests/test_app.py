"""Basic smoke tests for the efficiency app."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models
import lark_reader


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


if __name__ == "__main__":
    test_db_init()
    test_find_column()
    test_parse_sheet_counts_completed_tasks_by_round()
    print("All tests passed")
