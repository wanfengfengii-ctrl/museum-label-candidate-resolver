"""POST /recover-aligned 端到端测试：全局对齐、编辑优先级、确定性与校验。"""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from app.checksum import is_valid_code


def single_candidate_fragments(chars: str, confidence: int = 50) -> dict:
    return {
        "fragments": [
            {"candidates": [{"char": ch, "confidence": confidence}]} for ch in chars
        ]
    }


def test_aligned_health_still_ok(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_exact_ten_fragments_zero_edits(client: TestClient) -> None:
    response = client.post(
        "/recover-aligned", json=single_candidate_fragments("AC13567899")
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "AC13567899"
    assert is_valid_code(body["code"])
    assert body["edits"] == 0
    assert body["total_score"] == 500
    assert [m["position"] for m in body["matches"]] == list(range(10))
    assert [m["source_index"] for m in body["matches"]] == list(range(10))
    assert all(m["confidence"] == 50 for m in body["matches"])
    assert body["ignored_fragments"] == []


def test_middle_gap_returns_zero_confidence_fill(client: TestClient) -> None:
    response = client.post(
        "/recover-aligned", json=single_candidate_fragments("AC0039070")
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "AC00339070"
    assert is_valid_code(body["code"])
    assert body["edits"] == 1
    fill = body["matches"][5]
    assert fill == {"position": 5, "char": "3", "confidence": 0, "source_index": None}
    assert body["matches"][6]["source_index"] == 5
    assert body["ignored_fragments"] == []
    # 得分只累加真实匹配片段的置信度。
    assert body["total_score"] == 9 * 50
    assert sum(m["confidence"] for m in body["matches"]) == body["total_score"]


def test_extra_high_confidence_smudge_is_listed_as_ignored(client: TestClient) -> None:
    payload = single_candidate_fragments("AC13567899")
    payload["fragments"].insert(4, {"candidates": [{"char": "0", "confidence": 100}]})
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "AC13567899"
    assert body["edits"] == 1
    assert body["ignored_fragments"] == [
        {"source_index": 4, "candidates": [{"char": "0", "confidence": 100}]}
    ]
    # 污点高分不影响总分，也不挤占真实标签。
    assert body["total_score"] == 500
    assert [m["source_index"] for m in body["matches"][4:6]] == [5, 6]


def test_ten_fragment_shift_repaired_with_ignore_and_fill(
    client: TestClient,
) -> None:
    chars = list("AC000000")
    chars.insert(8, "X")
    chars.append("0")
    assert len(chars) == 10
    response = client.post(
        "/recover-aligned",
        json=single_candidate_fragments("".join(chars)),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "AC00000000"
    assert body["edits"] == 2
    assert body["ignored_fragments"] == [
        {"source_index": 8, "candidates": [{"char": "X", "confidence": 50}]}
    ]
    fill = body["matches"][9]
    assert fill["source_index"] is None
    assert fill["char"] == "0"
    assert fill["confidence"] == 0
    assert body["matches"][8]["source_index"] == 9


def test_zero_edits_wins_even_when_edited_alignment_scores_higher(
    client: TestClient,
) -> None:
    payload = single_candidate_fragments("AC13567899")
    payload["fragments"][2] = {
        "candidates": [
            {"char": "1", "confidence": 5},
            {"char": "2", "confidence": 95},
        ]
    }
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "AC13567899"
    assert body["edits"] == 0
    assert body["matches"][2]["char"] == "1"
    assert body["ignored_fragments"] == []


def test_candidate_permutation_does_not_change_result(client: TestClient) -> None:
    payload = {
        "fragments": [
            {"candidates": [{"char": "A", "confidence": 90}, {"char": "B", "confidence": 80}]},
            {"candidates": [{"char": "C", "confidence": 95}, {"char": "D", "confidence": 70}]},
        ]
        + [{"candidates": [{"char": ch, "confidence": 50}]} for ch in "0039070"]
    }
    shuffled = copy.deepcopy(payload)
    for fragment in shuffled["fragments"]:
        fragment["candidates"].reverse()
    first = client.post("/recover-aligned", json=payload)
    second = client.post("/recover-aligned", json=shuffled)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_no_alignment_returns_422_with_reason(client: TestClient) -> None:
    response = client.post(
        "/recover-aligned", json=single_candidate_fragments("11111111")
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert len(detail) == 1
    assert detail[0]["position"] is None
    assert detail[0]["reason"]


def test_ten_fragments_without_direct_solution_use_ignore_fill(client: TestClient) -> None:
    # 十个片段直连不合法（校验不过），但允许一次忽略加一次补位后合法。
    response = client.post(
        "/recover-aligned", json=single_candidate_fragments("AC00000001")
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["edits"] == 2
    assert is_valid_code(body["code"])
    assert len(body["ignored_fragments"]) == 1
    assert any(m["source_index"] is None for m in body["matches"])


def test_fragment_count_boundaries(client: TestClient) -> None:
    # 越界（少于 8 或多于 12）在进入求解前即 422；
    # 恰好 8/12 个但无字母片段时在求解阶段同样 422（附无结果原因）。
    for count in (7, 8, 12, 13):
        response = client.post(
            "/recover-aligned", json=single_candidate_fragments("1" * count)
        )
        assert response.status_code == 422, count

    response = client.post(
        "/recover-aligned", json=single_candidate_fragments("AC000000")
    )
    assert response.status_code == 200, response.text
    assert response.json()["edits"] == 2

    twelve = single_candidate_fragments("AC13567899")
    twelve["fragments"].insert(0, {"candidates": [{"char": "Q", "confidence": 3}]})
    twelve["fragments"].insert(6, {"candidates": [{"char": "0", "confidence": 100}]})
    response = client.post("/recover-aligned", json=twelve)
    assert response.status_code == 200, response.text
    assert response.json()["edits"] == 2


def test_non_alphanumeric_candidate_rejected_with_position(client: TestClient) -> None:
    payload = single_candidate_fragments("AC0039070")
    payload["fragments"][3]["candidates"][0]["char"] = "a"
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["position"] == 3
    assert "A-Z" in detail[0]["reason"] and "0-9" in detail[0]["reason"]


def test_multiple_invalid_fragments_reported_and_sorted_by_source(
    client: TestClient,
) -> None:
    payload = single_candidate_fragments("AC0039070")
    payload["fragments"][6]["candidates"][0]["char"] = "x"
    payload["fragments"][2]["candidates"][0]["char"] = "y"
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 422
    assert [detail["position"] for detail in response.json()["detail"]] == [2, 6]


def test_errors_sort_null_position_first(client: TestClient) -> None:
    payload = single_candidate_fragments("AC0039070")
    payload["fragments"][6]["candidates"][0]["char"] = "x"
    payload["fragments"][2]["candidates"][0]["char"] = "y"
    payload["alternative_limit"] = 2
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 422
    assert [detail["position"] for detail in response.json()["detail"]] == [None, 2, 6]


def test_underfull_count_and_illegal_candidate_are_reported_together(
    client: TestClient,
) -> None:
    payload = single_candidate_fragments("AC00390")
    payload["fragments"][3]["candidates"][0]["char"] = "a"
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 422
    positions = [detail["position"] for detail in response.json()["detail"]]
    # 数量不足（无源位置）与候选非法一次报全，无需先修字符再被告知数量。
    assert positions == [None, 3]


def test_overlong_count_and_illegal_candidates_are_reported_together(
    client: TestClient,
) -> None:
    payload = single_candidate_fragments("A" + "0" * 12)
    payload["fragments"][3]["candidates"][0]["char"] = "a"
    payload["fragments"][11]["candidates"][0]["char"] = "b"
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 422
    positions = [detail["position"] for detail in response.json()["detail"]]
    assert positions == [None, 3, 11]


def test_count_error_is_not_duplicated(client: TestClient) -> None:
    for count in (7, 13):
        response = client.post(
            "/recover-aligned", json=single_candidate_fragments("1" * count)
        )
        assert response.status_code == 422
        assert len(response.json()["detail"]) == 1
        assert response.json()["detail"][0]["position"] is None


def test_ignored_fragment_candidates_are_candidate_order_invariant(
    client: TestClient,
) -> None:
    def payload(order: list[tuple[str, int]]) -> dict:
        fragments = single_candidate_fragments("AC13567899")["fragments"]
        fragments.insert(
            4, {"candidates": [{"char": ch, "confidence": cf} for ch, cf in order]}
        )
        return {"fragments": fragments}

    first = client.post(
        "/recover-aligned", json=payload([("X", 90), ("0", 10)])
    ).json()
    second = client.post(
        "/recover-aligned", json=payload([("0", 10), ("X", 90)])
    ).json()
    assert first == second
    assert first["ignored_fragments"][0]["candidates"] == [
        {"char": "0", "confidence": 10},
        {"char": "X", "confidence": 90},
    ]


def test_alternative_limit_is_not_accepted(client: TestClient) -> None:
    payload = single_candidate_fragments("AC0039070")
    payload["alternative_limit"] = 2
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["position"] is None


def test_invalid_confidence_and_duplicate_and_candidate_count_rejected(
    client: TestClient,
) -> None:
    payload = single_candidate_fragments("AC0039070")
    payload["fragments"][1]["candidates"][0]["confidence"] = 101
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["position"] == 1

    payload = single_candidate_fragments("AC0039070")
    payload["fragments"][0]["candidates"].append(
        {"char": "A", "confidence": 10}
    )
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["position"] == 0

    payload = single_candidate_fragments("AC0039070")
    payload["fragments"][0]["candidates"] = []
    response = client.post("/recover-aligned", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["position"] == 0


def test_original_recover_contract_unchanged(client: TestClient, payload: dict) -> None:
    response = client.post("/recover", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "AC13567899"
    assert body["total_score"] == 694
    assert "alternatives" not in body
