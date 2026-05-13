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


if __name__ == "__main__":
    test_db_init()
    test_find_column()
    print("All tests passed")
