"""校验与排序规则的单元测试。"""

from __future__ import annotations

import pytest

from app.checksum import checksum_digit, is_valid_code, rank_key


def test_checksum_matches_spec() -> None:
    # 1*3 + 3*1 + 5*7 + 6*3 + 7*1 + 8*7 + 9*3 = 149 -> 9
    assert checksum_digit([1, 3, 5, 6, 7, 8, 9]) == 9


def test_checksum_all_zeros() -> None:
    assert checksum_digit([0, 0, 0, 0, 0, 0, 0]) == 0


def test_checksum_wraps_modulo_ten() -> None:
    # 9*3 + 9*1 + 9*7 + 9*3 + 9*1 + 9*7 + 9*3 = 225 -> 5
    assert checksum_digit([9, 9, 9, 9, 9, 9, 9]) == 5


def test_checksum_rejects_wrong_length() -> None:
    with pytest.raises(ValueError):
        checksum_digit([1, 2, 3])


def test_is_valid_code_accepts_valid() -> None:
    assert is_valid_code("AC13567899")


def test_is_valid_code_rejects_bad_checksum() -> None:
    assert not is_valid_code("AC13567890")


@pytest.mark.parametrize(
    "code",
    [
        "",
        "AC1356789",      # 长度不足
        "AC135678999",    # 长度超出
        "ac13567899",     # 小写字母
        "A113567899",     # 字母位出现数字
        "1C13567899",     # 字母位出现数字
        "AC1356789A",     # 校验位不是数字
        "AC1 567899",     # 非法字符
    ],
)
def test_is_valid_code_rejects_malformed(code: str) -> None:
    assert not is_valid_code(code)


def test_rank_key_prefers_higher_score() -> None:
    assert rank_key(10, "ZZ99999999") < rank_key(9, "AA00000000")


def test_rank_key_breaks_ties_by_lexicographic_code() -> None:
    assert rank_key(10, "AA00000000") < rank_key(10, "AB00000000")
