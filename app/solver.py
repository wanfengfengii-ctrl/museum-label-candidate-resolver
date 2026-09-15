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


def find_best_solution(positions: Sequence[Position]) -> Solution | None:
    """搜索所有符合格式与校验式的组合，返回最优解；无合法组合返回 None。

    结果只取决于候选集合本身：按所选候选置信度之和降序取胜，同分
    取完整编码字典序最小者，与候选在请求中的排列次序无关。
    """
    check_confidence = {c.char: c.confidence for c in positions[CHECK_POSITION].candidates}
    pools = [tuple(position.candidates) for position in positions[:CHECK_POSITION]]

    best: Solution | None = None
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
        solution = Solution(code=code, total_score=total, choices=choices)
        if best is None or rank_key(total, code) < rank_key(best.total_score, best.code):
            best = solution
    return best
