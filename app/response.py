"""响应组装：把求解结果转换为 API 响应模型。"""

from __future__ import annotations

from app.schemas import ChoiceOut, RecoverResponse
from app.solver import Solution


def build_response(solution: Solution) -> RecoverResponse:
    """按位置顺序组装编码、总分和逐位选择。"""
    return RecoverResponse(
        code=solution.code,
        total_score=solution.total_score,
        choices=[
            ChoiceOut(
                position=choice.position,
                char=choice.char,
                confidence=choice.confidence,
            )
            for choice in solution.choices
        ],
    )
