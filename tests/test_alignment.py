"""全局对齐求解器测试：编辑优先级、确定性映射、候选排列不变性。"""

from __future__ import annotations

import copy

import pytest

from app.alignment import FILL_MARKER, TargetMatch, align_fragments
from app.checksum import is_valid_code
from app.schemas import Position


def fragment(candidates: list[tuple[str, int]]) -> Position:
    return Position.model_validate(
        {"candidates": [{"char": ch, "confidence": cf} for ch, cf in candidates]}
    )


def fragments_from_chars(chars: str, confidence: int = 50) -> list[Position]:
    return [fragment([(ch, confidence)]) for ch in chars]


def aligned_map(alignment) -> tuple[int | None, ...]:
    return tuple(match.source_index for match in alignment.matches)


def test_exact_ten_fragments_align_with_zero_edits() -> None:
    alignment = align_fragments(fragments_from_chars("AC13567899"))
    assert alignment is not None
    assert alignment.code == "AC13567899"
    assert alignment.edits == 0
    assert alignment.fill_count == 0
    assert alignment.ignored_sources == ()
    assert aligned_map(alignment) == tuple(range(10))
    assert all(not match.is_fill for match in alignment.matches)


def test_middle_gap_uses_one_zero_confidence_fill() -> None:
    # AC00339070 去掉第 5 位字符 '3'：唯一一编辑对齐是在目标位 5 补位。
    alignment = align_fragments(fragments_from_chars("AC0039070"))
    assert alignment is not None
    assert alignment.code == "AC00339070"
    assert is_valid_code(alignment.code)
    assert alignment.edits == 1
    assert alignment.ignored_sources == ()
    fill = [match for match in alignment.matches if match.is_fill]
    assert len(fill) == 1
    assert fill[0] == TargetMatch(position=5, source_index=None, char="3", confidence=0)
    # 源片段在补位之后整体右移一位。
    assert aligned_map(alignment) == (0, 1, 2, 3, 4, None, 5, 6, 7, 8)
    matched = [m for m in alignment.matches if not m.is_fill]
    assert sum(m.confidence for m in matched) == alignment.total_score


def test_extra_high_confidence_smudge_is_ignored() -> None:
    chars = list("AC13567899")
    fragments = fragments_from_chars("".join(chars))
    fragments.insert(4, fragment([("0", 100)]))  # 高分污点
    alignment = align_fragments(fragments)
    assert alignment is not None
    assert alignment.code == "AC13567899"
    assert alignment.edits == 1
    assert alignment.fill_count == 0
    assert alignment.ignored_sources == (4,)
    # 污点置信度不计入总分。
    assert alignment.total_score == 500
    assert aligned_map(alignment) == (0, 1, 2, 3, 5, 6, 7, 8, 9, 10)


def test_two_smudges_require_two_ignores() -> None:
    fragments = fragments_from_chars("AC13567899")
    fragments.insert(0, fragment([("Q", 3)]))
    fragments.insert(6, fragment([("0", 100)]))
    alignment = align_fragments(fragments)
    assert alignment is not None
    assert len(fragments) == 12
    assert alignment.code == "AC13567899"
    assert alignment.edits == 2
    assert alignment.ignored_sources == (0, 6)


def test_two_missing_fragments_use_two_fills() -> None:
    # A C + 六个数据位 + 校验位 0 共八个片段：缺少两个目标位，
    # 补位字符须满足类别与校验式。
    alignment = align_fragments(fragments_from_chars("AC000000"))
    assert alignment is not None
    assert alignment.code == "AC00000000"
    assert is_valid_code(alignment.code)
    assert alignment.edits == 2
    assert alignment.ignored_sources == ()
    fills = [match for match in alignment.matches if match.is_fill]
    assert len(fills) == 2
    assert all(fill.confidence == 0 for fill in fills)


def test_ten_fragments_misalignment_repairs_with_ignore_and_fill() -> None:
    # 第 8 个源片段是字母污点 X，校验位漏读：忽略 X 并补位校验数字。
    fragments = fragments_from_chars("AC0000000")[:8]
    fragments.append(fragment([("X", 95)]))
    fragments.append(fragment([("0", 44)]))
    alignment = align_fragments(fragments)
    assert alignment is not None
    assert alignment.code == "AC00000000"
    assert is_valid_code(alignment.code)
    assert alignment.edits == 2
    assert alignment.ignored_sources == (8,)
    fill = [match for match in alignment.matches if match.is_fill]
    assert [match.position for match in fill] == [9]
    assert fill[0].char == "0"
    assert aligned_map(alignment) == (0, 1, 2, 3, 4, 5, 6, 7, 9, None)


def test_zero_edits_preferred_over_higher_scoring_edited_alignment() -> None:
    # 十个片段可直接对齐；片段 2 的另一个高分数字候选无法通过校验，
    # 求解器不得改用“忽略 + 补位”去追逐更高置信度。
    fragments = fragments_from_chars("AC13567899")
    fragments[2] = fragment([("1", 5), ("2", 95)])
    alignment = align_fragments(fragments)
    assert alignment is not None
    assert alignment.edits == 0
    assert alignment.code == "AC13567899"


def test_score_then_code_then_mapping_are_deterministic() -> None:
    # AC + 九个 '0' 共十一个源片段且彼此等价：映射字典序决定忽略最后一个。
    fragments = fragments_from_chars("AC" + "0" * 9)
    alignment = align_fragments(fragments)
    assert alignment is not None
    assert alignment.code == "AC00000000"
    assert alignment.edits == 1
    assert alignment.ignored_sources == (10,)


def test_fill_tie_prefers_mapping_with_latest_fill() -> None:
    # 九个 '0'（AC 后七个）缺一位：多个补位位置等价；补位排在源索引之后，
    # 即映射字典序最小对应“补位尽量靠后”。
    alignment = align_fragments(fragments_from_chars("AC" + "0" * 7))
    assert alignment is not None
    fill_positions = [match.position for match in alignment.matches if match.is_fill]
    assert fill_positions == [9]


def test_result_is_insensitive_to_candidate_permutation() -> None:
    payload = [
        [("A", 90), ("B", 80)],
        [("C", 95), ("D", 70)],
    ] + [[(ch, 50)] for ch in "0039070"]
    first = [fragment(candidates) for candidates in payload]
    second_payload = copy.deepcopy(payload)
    for candidates in second_payload:
        candidates.reverse()
    second = [fragment(candidates) for candidates in second_payload]

    left = align_fragments(first)
    right = align_fragments(second)
    assert left is not None and right is not None
    assert (
        left.code,
        left.total_score,
        left.edits,
        tuple((m.position, m.source_index, m.char, m.confidence) for m in left.matches),
        left.ignored_sources,
    ) == (
        right.code,
        right.total_score,
        right.edits,
        tuple((m.position, m.source_index, m.char, m.confidence) for m in right.matches),
        right.ignored_sources,
    )


@pytest.mark.parametrize("chars", ["11111111", "1111111111", "ABCDEFGHIJ"])
def test_no_alignment_returns_none(chars: str) -> None:
    assert align_fragments(fragments_from_chars(chars)) is None


def test_fill_marker_is_larger_than_any_source_index() -> None:
    # 补位在映射比较中必须排在所有源索引之后。
    assert FILL_MARKER > 12
