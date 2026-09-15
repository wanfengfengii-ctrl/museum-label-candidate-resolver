"""一次性验收脚本：对运行中的 API 执行关键场景检查。

由 docker compose 的 verify 服务调用，也可独立运行：

    API_BASE_URL=http://localhost:8000 python verify.py

全部检查通过时退出码为 0，否则为 1。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable

BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000").rstrip("/")

EXPECTED_CODE = "AC13567899"
EXPECTED_TOTAL_SCORE = 694


def valid_payload() -> dict[str, Any]:
    """与 tests/conftest.py 相同的手工核算样例：AC13567899，总分 694。"""
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


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def wait_for_api(timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            status, _ = request("GET", "/health")
            if status == 200:
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise RuntimeError(f"API at {BASE_URL} did not become healthy in time")


def check_health() -> None:
    status, body = request("GET", "/health")
    assert status == 200, f"expected 200, got {status}"
    assert body == {"status": "ok"}, f"unexpected body: {body}"


def check_happy_path() -> None:
    status, body = request("POST", "/recover", valid_payload())
    assert status == 200, f"expected 200, got {status}: {body}"
    assert body["code"] == EXPECTED_CODE, f"unexpected code: {body['code']}"
    assert body["total_score"] == EXPECTED_TOTAL_SCORE, (
        f"unexpected total_score: {body['total_score']}"
    )
    assert [c["position"] for c in body["choices"]] == list(range(10))
    assert sum(c["confidence"] for c in body["choices"]) == body["total_score"]


def check_candidate_order_invariance() -> None:
    payload = valid_payload()
    for position in payload["positions"]:
        position["candidates"].reverse()
    status, body = request("POST", "/recover", payload)
    assert status == 200, f"expected 200, got {status}: {body}"
    assert body["code"] == EXPECTED_CODE, (
        f"candidate order changed the result: {body['code']}"
    )
    assert body["total_score"] == EXPECTED_TOTAL_SCORE


def check_tie_break() -> None:
    payload = valid_payload()
    payload["positions"][0]["candidates"] = [
        {"char": "B", "confidence": 90},
        {"char": "A", "confidence": 90},
    ]
    status, body = request("POST", "/recover", payload)
    assert status == 200, f"expected 200, got {status}: {body}"
    assert body["code"] == EXPECTED_CODE, (
        f"tie should pick lexicographically smallest code, got {body['code']}"
    )


def check_no_valid_combination() -> None:
    payload = valid_payload()
    payload["positions"][9]["candidates"] = [{"char": "0", "confidence": 10}]
    status, body = request("POST", "/recover", payload)
    assert status == 422, f"expected 422, got {status}: {body}"
    assert body["detail"][0]["reason"], "missing reason in error detail"


def check_too_few_positions() -> None:
    payload = valid_payload()
    payload["positions"] = payload["positions"][:9]
    status, body = request("POST", "/recover", payload)
    assert status == 422, f"expected 422, got {status}: {body}"


def check_wrong_character_class() -> None:
    payload = valid_payload()
    payload["positions"][0]["candidates"] = [{"char": "7", "confidence": 50}]
    status, body = request("POST", "/recover", payload)
    assert status == 422, f"expected 422, got {status}: {body}"
    detail = body["detail"][0]
    assert detail["position"] == 0, f"error should point at position 0: {detail}"
    assert detail["reason"], "missing reason in error detail"


def check_duplicate_candidate_chars() -> None:
    payload = valid_payload()
    payload["positions"][0]["candidates"] = [
        {"char": "A", "confidence": 90},
        {"char": "A", "confidence": 10},
    ]
    status, body = request("POST", "/recover", payload)
    assert status == 422, f"expected 422, got {status}: {body}"
    assert body["detail"][0]["position"] == 0


def check_confidence_out_of_range() -> None:
    payload = valid_payload()
    payload["positions"][3]["candidates"][0]["confidence"] = 101
    status, body = request("POST", "/recover", payload)
    assert status == 422, f"expected 422, got {status}: {body}"
    assert body["detail"][0]["position"] == 3


CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("health endpoint", check_health),
    ("happy path recovers expected label", check_happy_path),
    ("candidate order does not change the label", check_candidate_order_invariance),
    ("ties break to lexicographically smallest code", check_tie_break),
    ("no valid combination returns 422", check_no_valid_combination),
    ("fewer than ten positions rejected", check_too_few_positions),
    ("wrong character class rejected with position", check_wrong_character_class),
    ("duplicate candidate chars rejected with position", check_duplicate_candidate_chars),
    ("confidence out of range rejected with position", check_confidence_out_of_range),
]


def main() -> int:
    wait_for_api()
    failures = 0
    for name, check in CHECKS:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - 验收脚本需汇总所有失败
            failures += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"PASS {name}")
    total = len(CHECKS)
    print(f"\n{total - failures}/{total} checks passed against {BASE_URL}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
