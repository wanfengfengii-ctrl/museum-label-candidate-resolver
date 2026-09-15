"""校验与排序规则。

馆藏标签编码共 10 位：第 0、1 位为大写字母 A-Z，第 2 至 8 位为七个
数据数字，第 9 位（末位）为校验数字。七个数据数字从左到右分别乘
3、1、7、3、1、7、3，乘积之和对 10 取余即为末位。
"""

from __future__ import annotations

from collections.abc import Sequence

WEIGHTS: tuple[int, ...] = (3, 1, 7, 3, 1, 7, 3)
CODE_LENGTH = 10
LETTER_POSITIONS: frozenset[int] = frozenset({0, 1})
DATA_DIGIT_SLICE = slice(2, 9)
CHECK_POSITION = 9


def checksum_digit(digits: Sequence[int]) -> int:
    """按权重 3、1、7、3、1、7、3 计算七个数据数字的校验位。"""
    if len(digits) != len(WEIGHTS):
        raise ValueError(f"expected {len(WEIGHTS)} data digits, got {len(digits)}")
    return sum(d * w for d, w in zip(digits, WEIGHTS, strict=True)) % 10


def is_valid_code(code: str) -> bool:
    """检查完整编码是否同时满足格式与校验式。"""
    if len(code) != CODE_LENGTH:
        return False
    if not all("A" <= ch <= "Z" for ch in code[:2]):
        return False
    if not all("0" <= ch <= "9" for ch in code[2:]):
        return False
    digits = [int(ch) for ch in code[DATA_DIGIT_SLICE]]
    return checksum_digit(digits) == int(code[CHECK_POSITION])


def rank_key(score: int, code: str) -> tuple[int, str]:
    """排序键：总分降序优先，同分取完整编码字典序最小者。"""
    return (-score, code)
