"""片段到十位编码的全局对齐动态规划。

采集设备偶尔漏读一位（收到少于十个 OCR 片段）或把污点识别成多余片段
（收到多于十个）。求解器在保持片段原始次序的前提下，把片段匹配到十个
目标位，允许两类编辑操作：

- 忽略一个源片段（污点）；
- 对一个目标位零置信度补位（漏读）。

状态为 ``(源片段下标 i, 已对齐目标位数 j, 已用编辑数 e, 校验余数 r)``，
三种转移：

1. 匹配：源片段 i 的某个候选字符类别符合目标位 j，字符进入编码，余数
   累加（目标位 9 仅接受与余数相等的数字）；
2. 忽略源片段 i（计一次编辑）；
3. 补位目标位 j（计一次编辑）：补位字符参与字符类别与校验计算。

最多允许两次编辑；十个源片段时只有在零编辑无解后才允许“一次忽略加
一次补位”，从而优先原样对齐、不为错位片段凭空补漏。

排名（编辑数相同的对齐之间）：匹配置信度总和最高者优先；再相同则按
完整编码字典序；仍相同则按“目标位 -> 源下标”映射的字典序，补位在
映射比较中排在所有源索引之后，确保候选排列变化时结果唯一。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.checksum import (
    CHECK_POSITION,
    CODE_LENGTH,
    DATA_DIGIT_SLICE,
    LETTER_POSITIONS,
    WEIGHTS,
    checksum_digit,
)
from app.schemas import Position

MAX_EDITS = 2

# 补位在源映射比较中排在所有源索引之后。
FILL_MARKER: int = 1 << 30

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_DIGITS = "0123456789"


@dataclass(frozen=True)
class TargetMatch:
    """一个目标位的对齐结果：源片段下标，或 None 表示零置信度补位。"""

    position: int
    source_index: int | None
    char: str
    confidence: int

    @property
    def is_fill(self) -> bool:
        return self.source_index is None


@dataclass(frozen=True)
class Alignment:
    """一次完整对齐：编码、得分、编辑次数、逐目标位映射与被忽略源片段。"""

    code: str
    total_score: int
    edits: int
    matches: tuple[TargetMatch, ...]
    ignored_sources: tuple[int, ...]

    @property
    def fill_count(self) -> int:
        return sum(1 for match in self.matches if match.is_fill)


@dataclass
class _Node:
    """DP 部分对齐。同一 DP 状态同一步数下只保留排名最靠前的节点。"""

    score: int
    chars: list[str] = field(default_factory=list)
    mapping: list[int] = field(default_factory=list)

    def rank_key(self) -> tuple:
        # 置信度总和降序、编码字典序、源映射字典序（补位排在源索引之后）。
        return (-self.score, tuple(self.chars), tuple(self.mapping))


def _confidence_map(position: Position) -> dict[str, int]:
    return {candidate.char: candidate.confidence for candidate in position.candidates}


def _is_class_ok(position_index: int, char: str) -> bool:
    if position_index in LETTER_POSITIONS:
        return "A" <= char <= "Z"
    return "0" <= char <= "9"


def _data_weight(position_index: int) -> int:
    """数据位（2..8）的校验权重；字母位不参与加权和，记 0。"""
    if DATA_DIGIT_SLICE.start <= position_index <= DATA_DIGIT_SLICE.stop - 1:
        return WEIGHTS[position_index - DATA_DIGIT_SLICE.start]
    return 0


def align_fragments(fragments: Sequence[Position]) -> Alignment | None:
    """在最多两次编辑内求最优全局对齐；无合法对齐返回 None。

    第一轮只接受零编辑或单侧编辑（仅忽略或仅补位）。源片段恰为十个时，
    单调对齐下“忽略数”恒等于“补位数”，故该轮实际只会得到零编辑结果；
    零编辑无解时，第二轮才放开“一次忽略 + 一次补位”的错位修复。
    """
    result = _run_dp(fragments, allow_shuffle=False)
    if result is None and len(fragments) == CODE_LENGTH:
        result = _run_dp(fragments, allow_shuffle=True)
    return result


def _run_dp(fragments: Sequence[Position], *, allow_shuffle: bool) -> Alignment | None:
    """执行对齐 DP。

    ``allow_shuffle=False`` 时只接受零编辑，或忽略与补位中恰有一类出现
    （各至多两次）的对齐；为真时额外允许一次忽略加一次补位。
    """
    n = len(fragments)
    confidences = [_confidence_map(p) for p in fragments]
    # 字符升序遍历，使 DP 中间剪枝次序与结果完全确定（最终排名本就唯一，
    # 这里同时消除集合哈希序带来的偶然性）。
    candidate_chars = [sorted(confidences[i]) for i in range(n)]

    # state = (源下标 i, 目标位 j, 已用编辑数 e, 数据位加权余数 r)
    layer: dict[tuple[int, int, int, int], _Node] = {(0, 0, 0, 0): _Node(score=0)}

    def push(
        state: tuple[int, int, int, int],
        node: _Node,
        bucket: dict[tuple[int, int, int, int], _Node],
    ) -> None:
        current = bucket.get(state)
        if current is None or node.rank_key() < current.rank_key():
            bucket[state] = node

    # 任一路径至多 n + CODE_LENGTH 次转移；提前到达终点的路径无转移可走。
    for _ in range(n + CODE_LENGTH):
        next_layer: dict[tuple[int, int, int, int], _Node] = {}
        for (i, j, edits, remainder), node in layer.items():
            if i == n and j == CODE_LENGTH:
                push((i, j, edits, remainder), node, next_layer)
                continue

            fills = sum(1 for mark in node.mapping if mark == FILL_MARKER)
            # 单调对齐下，忽略集合由已匹配源下标与 i 唯一确定。
            ignores = i - (j - fills)

            # 转移一：源片段 i 匹配目标位 j
            if i < n and j < CODE_LENGTH:
                for char in candidate_chars[i]:
                    if not _is_class_ok(j, char):
                        continue
                    new_remainder = remainder
                    if j == CHECK_POSITION:
                        if int(char) != remainder:
                            continue
                        # 校验位与余数相等即闭合，余数归零。
                        new_remainder = 0
                    else:
                        weight = _data_weight(j)
                        if weight:
                            new_remainder = (remainder + weight * int(char)) % 10
                    child = _Node(
                        score=node.score + confidences[i][char],
                        chars=node.chars + [char],
                        mapping=node.mapping + [i],
                    )
                    push((i + 1, j + 1, edits, new_remainder), child, next_layer)

            if allow_shuffle:
                can_ignore = i < n and edits < MAX_EDITS and ignores < 1
                can_fill = j < CODE_LENGTH and edits < MAX_EDITS and fills < 1
            else:
                # 零编辑优先轮：忽略与补位不得同时出现，单侧至多两次。
                can_ignore = i < n and fills == 0 and edits < MAX_EDITS
                can_fill = j < CODE_LENGTH and ignores == 0 and edits < MAX_EDITS

            # 转移二：忽略源片段 i（污点）
            if can_ignore:
                child = _Node(
                    score=node.score,
                    chars=list(node.chars),
                    mapping=list(node.mapping),
                )
                push((i + 1, j, edits + 1, remainder), child, next_layer)

            # 转移三：补位目标位 j（漏读），补位字符参与类别与校验计算
            if can_fill:
                if j == CHECK_POSITION:
                    # 校验位由数据位余数唯一确定，匹配后余数闭合为零。
                    fill_options = ((str(remainder), 0),)
                else:
                    alphabet = _LETTERS if j in LETTER_POSITIONS else _DIGITS
                    weight = _data_weight(j)
                    fill_options = tuple(
                        (
                            char,
                            (remainder + weight * int(char)) % 10 if weight else remainder,
                        )
                        for char in alphabet
                    )
                for char, new_remainder in fill_options:
                    child = _Node(
                        score=node.score,
                        chars=node.chars + [char],
                        mapping=node.mapping + [FILL_MARKER],
                    )
                    push((i, j + 1, edits + 1, new_remainder), child, next_layer)
        layer = next_layer

    candidates: list[tuple[tuple, Alignment]] = []
    for (i, j, _edits, _remainder), node in layer.items():
        if i != n or j != CODE_LENGTH:
            continue
        fills = sum(1 for mark in node.mapping if mark == FILL_MARKER)
        matched_sources = [mark for mark in node.mapping if mark != FILL_MARKER]
        ignored_sources = sorted(set(range(n)) - set(matched_sources))
        edits = fills + len(ignored_sources)
        if edits > MAX_EDITS:
            continue
        if not allow_shuffle and fills and ignored_sources:
            continue
        alignment = _build_alignment(node, confidences, ignored_sources, edits)
        if alignment is None:
            continue
        # 排名：编辑最少 -> 置信度总和最高 -> 编码 -> 源映射（补位最后）。
        candidates.append(((edits,) + node.rank_key(), alignment))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _build_alignment(
    node: _Node,
    confidences: Sequence[dict[str, int]],
    ignored_sources: Sequence[int],
    edits: int,
) -> Alignment | None:
    """由 DP 节点还原逐目标位映射，并复核格式与校验式。"""
    if len(node.chars) != CODE_LENGTH or len(node.mapping) != CODE_LENGTH:
        return None
    code = "".join(node.chars)
    if not _code_matches_checksum(code):
        return None
    matches: list[TargetMatch] = []
    for position, (char, mark) in enumerate(zip(code, node.mapping, strict=True)):
        if mark == FILL_MARKER:
            matches.append(
                TargetMatch(position=position, source_index=None, char=char, confidence=0)
            )
        else:
            matches.append(
                TargetMatch(
                    position=position,
                    source_index=mark,
                    char=char,
                    confidence=confidences[mark][char],
                )
            )
    return Alignment(
        code=code,
        total_score=node.score,
        edits=edits,
        matches=tuple(matches),
        ignored_sources=tuple(ignored_sources),
    )


def _code_matches_checksum(code: str) -> bool:
    if len(code) != CODE_LENGTH:
        return False
    if not all("A" <= ch <= "Z" for ch in code[:2]):
        return False
    if not all("0" <= ch <= "9" for ch in code[2:]):
        return False
    digits = [int(ch) for ch in code[DATA_DIGIT_SLICE]]
    return checksum_digit(digits) == int(code[CHECK_POSITION])
