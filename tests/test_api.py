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
