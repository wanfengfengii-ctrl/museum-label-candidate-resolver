"""请求约束与响应模型。

请求固定包含十个位置；每处含一至三个不重复候选；置信度为 0 至 100
的整数；前两位候选只能是大写 A-Z，其余位只能是数字 0-9。任何一项
不满足即整体拒绝（422），错误信息指出位置与原因。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.checksum import CODE_LENGTH, LETTER_POSITIONS

MIN_CONFIDENCE = 0
MAX_CONFIDENCE = 100
MIN_CANDIDATES = 1
MAX_CANDIDATES = 3

Confidence = Annotated[
    int, Field(strict=True, ge=MIN_CONFIDENCE, le=MAX_CONFIDENCE)
]
Char = Annotated[str, Field(strict=True, min_length=1, max_length=1)]


class Candidate(BaseModel):
    """单个 OCR 候选字符及其置信度。"""

    model_config = ConfigDict(extra="forbid")

    char: Char
    confidence: Confidence


class Position(BaseModel):
    """一个位置上的候选集合，字符不得重复。"""

    model_config = ConfigDict(extra="forbid")

    candidates: list[Candidate] = Field(
        min_length=MIN_CANDIDATES, max_length=MAX_CANDIDATES
    )

    @field_validator("candidates")
    @classmethod
    def _unique_chars(cls, candidates: list[Candidate]) -> list[Candidate]:
        chars = [c.char for c in candidates]
        if len(set(chars)) != len(chars):
            raise ValueError("duplicate candidate characters in the same position")
        return candidates


class RecoverRequest(BaseModel):
    """恢复请求：固定十个位置。"""

    model_config = ConfigDict(extra="forbid")

    positions: list[Position] = Field(min_length=CODE_LENGTH, max_length=CODE_LENGTH)

    @model_validator(mode="after")
    def _check_character_classes(self) -> RecoverRequest:
        for index, position in enumerate(self.positions):
            for candidate in position.candidates:
                char = candidate.char
                if index in LETTER_POSITIONS:
                    if not "A" <= char <= "Z":
                        raise ValueError(
                            f"position {index}: character {char!r} is not an "
                            "uppercase letter A-Z"
                        )
                elif not "0" <= char <= "9":
                    raise ValueError(
                        f"position {index}: character {char!r} is not a digit 0-9"
                    )
        return self


class ChoiceOut(BaseModel):
    """逐位选择结果。"""

    position: int
    char: str
    confidence: int


class RecoverResponse(BaseModel):
    """恢复结果：编码、总分和逐位选择。"""

    code: str
    total_score: int
    choices: list[ChoiceOut]
