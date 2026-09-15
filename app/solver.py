"""候选组合的穷举搜索。

第 0 至 8 位在各自候选中穷举，末位由校验式唯一确定；只有校验位
落在第 9 位候选集合中的组合才是合法标签。每处至多三个候选，搜索
空间最大为 3^9 = 19683，可以完整枚举。
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from app.checksum import CHECK_POSITION, DATA_DIGIT_SLICE, checksum_digit, rank_key
from app.schemas import Position


@dataclass(frozen=True)
class Choice:
    position: int
    char: str
    confidence: int


@dataclass(frozen=True)
class Solution:
    code: str
    total_score: int
    choices: tuple[Choice, ...]


def _iter_solutions(positions: Sequence[Position]) -> list[Solution]:
    """枚举所有合法组合并按既有排名规则排序（总分降序、编码字典序）。

    排序只依赖总分与编码，因此候选在请求中的排列次序不影响结果。
    """
    check_confidence = {c.char: c.confidence for c in positions[CHECK_POSITION].candidates}
    pools = [tuple(position.candidates) for position in positions[:CHECK_POSITION]]

    solutions: list[Solution] = []
    for combo in itertools.product(*pools):
        chars = tuple(candidate.char for candidate in combo)
        digits = [int(ch) for ch in chars[DATA_DIGIT_SLICE]]
        check_char = str(checksum_digit(digits))
        confidence = check_confidence.get(check_char)
        if confidence is None:
            continue
        total = sum(candidate.confidence for candidate in combo) + confidence
        code = "".join(chars) + check_char
        choices = tuple(
            Choice(position=index, char=candidate.char, confidence=candidate.confidence)
            for index, candidate in enumerate(combo)
        ) + (Choice(position=CHECK_POSITION, char=check_char, confidence=confidence),)
        solutions.append(Solution(code=code, total_score=total, choices=choices))
    solutions.sort(key=lambda solution: rank_key(solution.total_score, solution.code))
    return solutions


def find_ranked_solutions(
    positions: Sequence[Position], limit: int
) -> list[Solution]:
    """返回至多 ``limit`` 个按排名规则排好序的合法结果；无合法组合返回空列表。"""
    return _iter_solutions(positions)[:limit]


def find_best_solution(positions: Sequence[Position]) -> Solution | None:
    """搜索所有符合格式与校验式的组合，返回最优解；无合法组合返回 None。

    结果只取决于候选集合本身：按所选候选置信度之和降序取胜，同分
    取完整编码字典序最小者，与候选在请求中的排列次序无关。
    """
    solutions = find_ranked_solutions(positions, 1)
    return solutions[0] if solutions else None
