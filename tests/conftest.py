"""共享测试夹具。

valid_payload 的最优解已手工核算：
- 第 0-8 位最高分组合为 A C 1 3 5 6 7 8 9；
- 数据数字 1,3,5,6,7,8,9 乘权重 3,1,7,3,1,7,3 得
  3+3+35+18+7+56+27 = 149，149 % 10 = 9；
- 第 9 位候选含 "9"（置信度 44），故合法编码为 AC13567899，
  总分 90+95+60+99+20+77+88+66+55+44 = 694。
- 第 9 位的 "0"（置信度 100）是诱饵：没有任何前九位组合的
  校验位为 0，服务不得被高置信度误导。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

EXPECTED_CODE = "AC13567899"
EXPECTED_TOTAL_SCORE = 694


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def valid_payload() -> dict:
    return {
        "positions": [
            {"candidates": [{"char": "A", "confidence": 90}, {"char": "B", "confidence": 80}]},
            {"candidates": [{"char": "C", "confidence": 95}, {"char": "D", "confidence": 70}]},
            {"candidates": [{"char": "1", "confidence": 60}, {"char": "2", "confidence": 50}]},
            {"candidates": [{"char": "3", "confidence": 99}]},
            {"candidates": [{"char": "4", "confidence": 10}, {"char": "5", "confidence": 20}]},
            {"candidates": [{"char": "6", "confidence": 77}]},
            {"candidates": [{"char": "7", "confidence": 88}]},
            {"candidates": [{"char": "8", "confidence": 66}]},
            {"candidates": [{"char": "9", "confidence": 55}]},
            {"candidates": [{"char": "9", "confidence": 44}, {"char": "0", "confidence": 100}]},
        ]
    }


@pytest.fixture()
def payload() -> dict:
    return valid_payload()
