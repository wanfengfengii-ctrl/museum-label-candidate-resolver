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


def check_default_response_has_no_alternatives() -> None:
    # 未传 alternative_limit 时响应须与旧版完全一致：不含 alternatives 字段。
    status, body = request("POST", "/recover", valid_payload())
    assert status == 200, f"expected 200, got {status}: {body}"
    assert "alternatives" not in body, f"unexpected alternatives: {body}"
    status_zero, body_zero = request(
        "POST", "/recover", {**valid_payload(), "alternative_limit": 0}
    )
    assert status_zero == 200
    assert body_zero == body, "alternative_limit=0 must match the default response"


def check_alternatives_ranked_by_score_then_code() -> None:
    status, body = request(
        "POST", "/recover", {**valid_payload(), "alternative_limit": 4}
    )
    assert status == 200, f"expected 200, got {status}: {body}"
    alternatives = body["alternatives"]
    assert [a["code"] for a in alternatives] == [
        "BC13567899",
        "AD13567899",
        "BD13567899",
    ], alternatives
    previous = body["total_score"]
    for alternative in alternatives:
        assert alternative["total_score"] < previous
        assert alternative["score_gap"] == body["total_score"] - alternative[
            "total_score"
        ]
        assert [c["position"] for c in alternative["choices"]] == list(range(10))
        previous = alternative["total_score"]


def check_alternatives_order_invariant() -> None:
    payload = valid_payload()
    shuffled = valid_payload()
    for position in shuffled["positions"]:
        position["candidates"].reverse()
    _, first = request("POST", "/recover", {**payload, "alternative_limit": 4})
    status, second = request("POST", "/recover", {**shuffled, "alternative_limit": 4})
    assert status == 200
    assert first == second, "candidate order changed the ranked alternatives"


def check_alternatives_truncated_to_available() -> None:
    payload = valid_payload()
    # 固定第 0 位后合法编码只有两个，limit=4 只返回一个备选。
    payload["positions"][0]["candidates"] = [{"char": "A", "confidence": 90}]
    status, body = request("POST", "/recover", {**payload, "alternative_limit": 4})
    assert status == 200, f"expected 200, got {status}: {body}"
    assert [a["code"] for a in body["alternatives"]] == ["AD13567899"]
    # 再固定第 1 位后只剩一个合法编码，请求备选时返回空列表而非缺省字段。
    payload["positions"][1]["candidates"] = [{"char": "C", "confidence": 95}]
    status, body = request("POST", "/recover", {**payload, "alternative_limit": 3})
    assert status == 200, f"expected 200, got {status}: {body}"
    assert body["alternatives"] == [], f"expected empty alternatives, got {body}"


def check_invalid_alternative_limit_rejected() -> None:
    for limit in (-1, 5, 1.5, "2"):
        status, body = request(
            "POST", "/recover", {**valid_payload(), "alternative_limit": limit}
        )
        assert status == 422, f"limit {limit!r}: expected 422, got {status}: {body}"
        assert body["detail"][0]["reason"], f"limit {limit!r}: missing reason"



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


def aligned_fragments(chars: str, confidence: int = 50) -> dict[str, Any]:
    return {
        "fragments": [
            {"candidates": [{"char": ch, "confidence": confidence}]} for ch in chars
        ]
    }


def check_aligned_middle_gap() -> None:
    # AC00339070 漏掉第 5 位的 '3'：九个片段须在目标位 5 零置信度补位。
    status, body = request("POST", "/recover-aligned", aligned_fragments("AC0039070"))
    assert status == 200, f"expected 200, got {status}: {body}"
    assert body["code"] == "AC00339070", body
    assert body["edits"] == 1
    assert body["ignored_fragments"] == []
    fill = body["matches"][5]
    assert fill == {"position": 5, "char": "3", "confidence": 0, "source_index": None}
    assert body["matches"][6]["source_index"] == 5
    assert sum(m["confidence"] for m in body["matches"]) == body["total_score"]


def check_aligned_extra_high_confidence_smudge() -> None:
    payload = aligned_fragments("AC13567899")
    payload["fragments"].insert(4, {"candidates": [{"char": "0", "confidence": 100}]})
    status, body = request("POST", "/recover-aligned", payload)
    assert status == 200, f"expected 200, got {status}: {body}"
    assert body["code"] == "AC13567899", body
    assert body["edits"] == 1
    assert body["ignored_fragments"] == [
        {"source_index": 4, "candidates": [{"char": "0", "confidence": 100}]}
    ]
    # 高分污点被忽略：得分不含它的 100，且不改变标签。
    assert body["total_score"] == 500
    assert body["matches"][4]["source_index"] == 5


def check_aligned_ten_fragment_shift_repair() -> None:
    # 十个片段：第 8 个是字母污点 X、校验位漏读，须“一次忽略 + 一次补位”。
    chars = list("AC000000")
    chars.insert(8, "X")
    chars.append("0")
    status, body = request(
        "POST", "/recover-aligned", aligned_fragments("".join(chars))
    )
    assert status == 200, f"expected 200, got {status}: {body}"
    assert body["code"] == "AC00000000", body
    assert body["edits"] == 2
    assert [i["source_index"] for i in body["ignored_fragments"]] == [8]
    fill = body["matches"][9]
    assert fill["source_index"] is None and fill["char"] == "0"


def check_aligned_zero_edits_preferred_over_score() -> None:
    # 直连合法时，即使忽略+补位能凑出更高分，也必须保持零编辑。
    payload = aligned_fragments("AC13567899")
    payload["fragments"][2] = {
        "candidates": [
            {"char": "1", "confidence": 5},
            {"char": "2", "confidence": 95},
        ]
    }
    status, body = request("POST", "/recover-aligned", payload)
    assert status == 200, f"expected 200, got {status}: {body}"
    assert body["edits"] == 0
    assert body["code"] == "AC13567899"


def check_aligned_deterministic_mapping() -> None:
    payload = {
        "fragments": [
            {"candidates": [{"char": "A", "confidence": 90}, {"char": "B", "confidence": 80}]},
            {"candidates": [{"char": "C", "confidence": 95}, {"char": "D", "confidence": 70}]},
        ]
        + [{"candidates": [{"char": ch, "confidence": 50}]} for ch in "0039070"]
    }
    shuffled = json.loads(json.dumps(payload))
    for fragment in shuffled["fragments"]:
        fragment["candidates"].reverse()
    _, first = request("POST", "/recover-aligned", payload)
    status, second = request("POST", "/recover-aligned", shuffled)
    assert status == 200
    assert first == second, "candidate permutation changed the alignment"


def check_aligned_no_solution_returns_reason() -> None:
    status, body = request("POST", "/recover-aligned", aligned_fragments("11111111"))
    assert status == 422, f"expected 422, got {status}: {body}"
    detail = body["detail"][0]
    assert detail["position"] is None
    assert detail["reason"], "missing no-result reason"


def check_aligned_validation_422() -> None:
    # 片段数越界。
    for count in (7, 13):
        status, body = request(
            "POST", "/recover-aligned", aligned_fragments("1" * count)
        )
        assert status == 422, f"{count} fragments: expected 422, got {status}: {body}"
    # 候选字符非法（小写字母）。
    payload = aligned_fragments("AC0039070")
    payload["fragments"][3]["candidates"][0]["char"] = "a"
    status, body = request("POST", "/recover-aligned", payload)
    assert status == 422, f"expected 422, got {status}: {body}"
    assert body["detail"][0]["position"] == 3
    # 新入口不接受备选上限。
    payload = aligned_fragments("AC0039070")
    payload["alternative_limit"] = 2
    status, body = request("POST", "/recover-aligned", payload)
    assert status == 422, f"expected 422, got {status}: {body}"
    assert body["detail"][0]["position"] is None


def check_recover_contract_still_compatible() -> None:
    status, body = request("POST", "/recover", valid_payload())
    assert status == 200
    assert body["code"] == EXPECTED_CODE
    assert body["total_score"] == EXPECTED_TOTAL_SCORE
    assert "alternatives" not in body


def check_aligned_count_and_character_errors_reported_together() -> None:
    # 七个片段且含小写候选：数量不足与字符非法必须一次报全（null 在前）。
    payload = aligned_fragments("AC00390")
    payload["fragments"][3]["candidates"][0]["char"] = "a"
    status, body = request("POST", "/recover-aligned", payload)
    assert status == 422, f"expected 422, got {status}: {body}"
    assert [detail["position"] for detail in body["detail"]] == [None, 3], body


def check_aligned_ignored_fragment_order_invariant() -> None:
    def payload(order: list[tuple[str, int]]) -> dict[str, Any]:
        data = aligned_fragments("AC13567899")
        data["fragments"].insert(
            4, {"candidates": [{"char": ch, "confidence": cf} for ch, cf in order]}
        )
        return data

    _, first = request(
        "POST", "/recover-aligned", payload([("X", 90), ("0", 10)])
    )
    status, second = request(
        "POST", "/recover-aligned", payload([("0", 10), ("X", 90)])
    )
    assert status == 200
    assert first == second, "ignored fragment order must be candidate-order invariant"


CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("health endpoint", check_health),
    ("happy path recovers expected label", check_happy_path),
    ("candidate order does not change the label", check_candidate_order_invariance),
    ("ties break to lexicographically smallest code", check_tie_break),
    ("no valid combination returns 422", check_no_valid_combination),
    ("default response omits alternatives", check_default_response_has_no_alternatives),
    ("alternatives ranked by total score then code", check_alternatives_ranked_by_score_then_code),
    ("alternatives are candidate-order invariant", check_alternatives_order_invariant),
    ("alternatives truncated when legal results are few", check_alternatives_truncated_to_available),
    ("invalid alternative_limit rejected with 422", check_invalid_alternative_limit_rejected),
    ("fewer than ten positions rejected", check_too_few_positions),
    ("wrong character class rejected with position", check_wrong_character_class),
    ("duplicate candidate chars rejected with position", check_duplicate_candidate_chars),
    ("confidence out of range rejected with position", check_confidence_out_of_range),
    ("aligned: middle gap recovered with zero-confidence fill", check_aligned_middle_gap),
    ("aligned: extra high-confidence smudge ignored", check_aligned_extra_high_confidence_smudge),
    ("aligned: ten-fragment shift repaired with ignore plus fill", check_aligned_ten_fragment_shift_repair),
    ("aligned: zero edits preferred over higher edited score", check_aligned_zero_edits_preferred_over_score),
    ("aligned: mapping is candidate-order deterministic", check_aligned_deterministic_mapping),
    ("aligned: no legal alignment returns reason", check_aligned_no_solution_returns_reason),
    ("aligned: invalid fragment count or candidate rejected", check_aligned_validation_422),
    ("aligned: count and character errors reported together", check_aligned_count_and_character_errors_reported_together),
    ("aligned: ignored fragment order is invariant", check_aligned_ignored_fragment_order_invariant),
    ("original /recover contract stays compatible", check_recover_contract_still_compatible),
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
