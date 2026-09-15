"""响应组装：把求解结果转换为 API 响应模型。"""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas import AlternativeOut, ChoiceOut, RecoverResponse
from app.solver import Solution


def _build_choices(solution: Solution) -> list[ChoiceOut]:
    return [
        ChoiceOut(
            position=choice.position,
            char=choice.char,
            confidence=choice.confidence,
        )
        for choice in solution.choices
    ]


def build_response(
    solution: Solution, alternatives: Sequence[Solution] = (), *, include_alternatives: bool = False
) -> RecoverResponse:
    """按位置顺序组装编码、总分和逐位选择。

    ``include_alternatives`` 为真时输出 ``alternatives``（每项附相对首选
    的分差），没有后续合法结果时为空列表；为假（未请求备选）时不输出
    该字段，响应与旧版完全一致。
    """
    return RecoverResponse(
        code=solution.code,
        total_score=solution.total_score,
        choices=_build_choices(solution),
        alternatives=(
            [
                AlternativeOut(
                    code=alt.code,
                    total_score=alt.total_score,
                    score_gap=solution.total_score - alt.total_score,
                    choices=_build_choices(alt),
                )
                for alt in alternatives
            ]
            if include_alternatives
            else None
        ),
    )
