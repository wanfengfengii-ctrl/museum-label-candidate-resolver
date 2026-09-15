"""API 端到端测试：合法流程、排序规则与各类整体拒绝。"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.checksum import is_valid_code
from tests.conftest import EXPECTED_CODE, EXPECTED_TOTAL_SCORE


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recover_returns_code_score_and_choices(client: TestClient, payload: dict) -> None:
    response = client.post("/recover", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == EXPECTED_CODE
    assert body["total_score"] == EXPECTED_TOTAL_SCORE
    assert is_valid_code(body["code"])
    assert [c["position"] for c in body["choices"]] == list(range(10))
    assert body["choices"][0] == {"position": 0, "char": "A", "confidence": 90}
    assert body["choices"][9] == {"position": 9, "char": "9", "confidence": 44}
    assert sum(c["confidence"] for c in body["choices"]) == body["total_score"]


def test_recover_is_insensitive_to_candidate_order(client: TestClient, payload: dict) -> None:
    shuffled = copy.deepcopy(payload)
    for position in shuffled["positions"]:
        position["candidates"].reverse()
    first = client.post("/recover", json=payload)
    second = client.post("/recover", json=shuffled)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_default_response_omits_alternatives(client: TestClient, payload: dict) -> None:
    response = client.post("/recover", json=payload)
    assert response.status_code == 200
    assert "alternatives" not in response.json()
    explicit_zero = client.post("/recover", json={**payload, "alternative_limit": 0})
    assert explicit_zero.json() == response.json()


def test_alternatives_ranked_by_score_and_lexicographic_order(
    client: TestClient, payload: dict
) -> None:
    response = client.post("/recover", json={**payload, "alternative_limit": 4})
    assert response.status_code == 200
    body = response.json()
    alternatives = body["alternatives"]
    assert len(alternatives) == 3
    assert [a["code"] for a in alternatives] == [
        "BC13567899",
        "AD13567899",
        "BD13567899",
    ]
    previous = body["total_score"]
    for alternative in alternatives:
        assert alternative["total_score"] < previous
        assert alternative["score_gap"] == body["total_score"] - alternative["total_score"]
        assert [c["position"] for c in alternative["choices"]] == list(range(10))
        assert sum(c["confidence"] for c in alternative["choices"]) == alternative[
            "total_score"
        ]
        assert is_valid_code(alternative["code"])
        previous = alternative["total_score"]


def test_alternatives_tie_breaks_by_code(client: TestClient, payload: dict) -> None:
    tied = copy.deepcopy(payload)
    tied["positions"][0]["candidates"] = [
        {"char": "B", "confidence": 90},
        {"char": "A", "confidence": 90},
    ]
    body = client.post("/recover", json={**tied, "alternative_limit": 1}).json()
    assert body["code"] == EXPECTED_CODE
    alternative = body["alternatives"][0]
    assert alternative["code"] == "BC13567899"
    assert alternative["score_gap"] == 0
    assert alternative["total_score"] == EXPECTED_TOTAL_SCORE


def test_alternatives_stable_when_candidate_order_changes(
    client: TestClient, payload: dict
) -> None:
    shuffled = copy.deepcopy(payload)
    for position in shuffled["positions"]:
        position["candidates"].reverse()
    first = client.post("/recover", json={**payload, "alternative_limit": 4})
    second = client.post("/recover", json={**shuffled, "alternative_limit": 4})
    assert first.json() == second.json()


def test_alternatives_truncated_to_available_results(
    client: TestClient, payload: dict
) -> None:
    reduced = copy.deepcopy(payload)
    # 固定第 0 位后只剩两个合法编码（AC...、AD...）。
    reduced["positions"][0]["candidates"] = [{"char": "A", "confidence": 90}]
    body = client.post("/recover", json={**reduced, "alternative_limit": 4}).json()
    assert [a["code"] for a in body["alternatives"]] == ["AD13567899"]
    only_one = copy.deepcopy(reduced)
    only_one["positions"][1]["candidates"] = [{"char": "C", "confidence": 95}]
    body = client.post("/recover", json={**only_one, "alternative_limit": 3}).json()
    assert body["alternatives"] == []


@pytest.mark.parametrize("limit", [-1, 5, 1.5, "2", True, None, "x"])
def test_invalid_alternative_limit_rejected_without_solving(
    client: TestClient, payload: dict, limit: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import main

    def boom(positions: object, limit: int) -> list:
        raise AssertionError("solver must not run for an invalid alternative_limit")

    monkeypatch.setattr(main, "find_ranked_solutions", boom)
    response = client.post("/recover", json={**payload, "alternative_limit": limit})
    assert response.status_code == 422
    assert response.json()["detail"][0]["reason"]


def test_no_valid_combination_with_alternatives_keeps_422(
    client: TestClient, payload: dict
) -> None:
    payload["positions"][9]["candidates"] = [{"char": "0", "confidence": 10}]
    response = client.post("/recover", json={**payload, "alternative_limit": 4})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["position"] is None
    assert detail[0]["reason"]


def test_no_valid_combination_returns_422(client: TestClient, payload: dict) -> None:
    payload["positions"][9]["candidates"] = [{"char": "0", "confidence": 10}]
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["reason"]


def test_too_few_positions_rejected(client: TestClient, payload: dict) -> None:
    payload["positions"] = payload["positions"][:9]
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    assert "10" in response.json()["detail"][0]["reason"]


def test_too_many_positions_rejected(client: TestClient, payload: dict) -> None:
    payload["positions"].append({"candidates": [{"char": "0", "confidence": 1}]})
    assert client.post("/recover", json=payload).status_code == 422


def test_letter_position_rejects_digit(client: TestClient, payload: dict) -> None:
    payload["positions"][0]["candidates"] = [{"char": "7", "confidence": 50}]
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["position"] == 0
    assert "A-Z" in detail["reason"]


def test_digit_position_rejects_letter(client: TestClient, payload: dict) -> None:
    payload["positions"][5]["candidates"] = [{"char": "x", "confidence": 50}]
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["position"] == 5
    assert "digit" in detail["reason"]


def test_lowercase_letter_rejected(client: TestClient, payload: dict) -> None:
    payload["positions"][1]["candidates"] = [{"char": "a", "confidence": 50}]
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["position"] == 1


def test_duplicate_chars_in_same_position_rejected(client: TestClient, payload: dict) -> None:
    payload["positions"][0]["candidates"] = [
        {"char": "A", "confidence": 90},
        {"char": "A", "confidence": 10},
    ]
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["position"] == 0
    assert "duplicate" in detail["reason"]


@pytest.mark.parametrize("confidence", [-1, 101, 1.5, "high", True, None])
def test_confidence_out_of_range_rejected(
    client: TestClient, payload: dict, confidence: object
) -> None:
    payload["positions"][3]["candidates"][0]["confidence"] = confidence
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["position"] == 3


def test_empty_candidate_list_rejected(client: TestClient, payload: dict) -> None:
    payload["positions"][0]["candidates"] = []
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["position"] == 0


def test_more_than_three_candidates_rejected(client: TestClient, payload: dict) -> None:
    payload["positions"][3]["candidates"] = [
        {"char": str(digit), "confidence": 10} for digit in "0123"
    ]
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["position"] == 3


def test_multi_char_candidate_rejected(client: TestClient, payload: dict) -> None:
    payload["positions"][0]["candidates"][0]["char"] = "AB"
    response = client.post("/recover", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["position"] == 0


def test_missing_positions_field_rejected(client: TestClient) -> None:
    response = client.post("/recover", json={})
    assert response.status_code == 422
    assert response.json()["detail"][0]["reason"]


def test_unexpected_field_rejected(client: TestClient, payload: dict) -> None:
    payload["label_hint"] = "AC13567899"
    assert client.post("/recover", json=payload).status_code == 422
