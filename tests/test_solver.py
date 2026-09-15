"""搜索模块的单元测试。"""

from __future__ import annotations

import copy

from app.schemas import RecoverRequest
from app.solver import Solution, find_best_solution
from tests.conftest import EXPECTED_CODE, EXPECTED_TOTAL_SCORE


def _solve(payload: dict) -> Solution | None:
    request = RecoverRequest.model_validate(payload)
    return find_best_solution(request.positions)


def test_finds_highest_scoring_valid_combination(payload: dict) -> None:
    solution = _solve(payload)
    assert solution is not None
    assert solution.code == EXPECTED_CODE
    assert solution.total_score == EXPECTED_TOTAL_SCORE
    assert [c.position for c in solution.choices] == list(range(10))
    assert solution.choices[9].char == "9"
    assert solution.choices[9].confidence == 44
    assert sum(c.confidence for c in solution.choices) == solution.total_score


def test_candidate_order_does_not_change_result(payload: dict) -> None:
    shuffled = copy.deepcopy(payload)
    for position in shuffled["positions"]:
        position["candidates"].reverse()
    assert _solve(shuffled) == _solve(payload)


def test_tie_breaks_by_lexicographically_smallest_code(payload: dict) -> None:
    tied = copy.deepcopy(payload)
    # A 与 B 同分且输入顺序为 B 在前，字典序更小的 AC... 必须胜出。
    tied["positions"][0]["candidates"] = [
        {"char": "B", "confidence": 90},
        {"char": "A", "confidence": 90},
    ]
    solution = _solve(tied)
    assert solution is not None
    assert solution.code == EXPECTED_CODE
    assert solution.total_score == EXPECTED_TOTAL_SCORE


def test_checksum_digit_must_be_offered_by_last_position(payload: dict) -> None:
    # 前九位所有组合的校验位只可能是 9、2、5，第 9 位只给 "0" 时无解。
    broken = copy.deepcopy(payload)
    broken["positions"][9]["candidates"] = [{"char": "0", "confidence": 10}]
    assert _solve(broken) is None


def test_high_confidence_decoy_check_digit_is_ignored(payload: dict) -> None:
    # 第 9 位的 "0" 置信度 100 高于 "9" 的 44，但没有组合算得出 0，
    # 最优解不得被诱饵带偏。
    solution = _solve(payload)
    assert solution is not None
    assert solution.choices[9].char == "9"
