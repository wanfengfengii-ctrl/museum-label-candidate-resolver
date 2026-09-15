"""请求约束与响应模型。

``POST /recover`` 请求固定包含十个位置；每处含一至三个不重复候选；
置信度为 0 至 100 的整数；前两位候选只能是大写 A-Z，其余位只能是
数字 0-9。

``POST /recover-aligned`` 接收 8 至 12 个 OCR 片段，复用同一候选
结构；片段不预设目标位，故候选字符允许大写 A-Z 或数字 0-9。任何
一项不满足即整体拒绝（422），错误信息指出位置与原因。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails

from app.checksum import CODE_LENGTH, LETTER_POSITIONS

MIN_CONFIDENCE = 0
MAX_CONFIDENCE = 100
MIN_CANDIDATES = 1
MAX_CANDIDATES = 3
MIN_ALTERNATIVE_LIMIT = 0
MAX_ALTERNATIVE_LIMIT = 4
MIN_FRAGMENTS = 8
MAX_FRAGMENTS = 12

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
    """恢复请求：固定十个位置，可选备选数量上限。"""

    model_config = ConfigDict(extra="forbid")

    positions: list[Position] = Field(min_length=CODE_LENGTH, max_length=CODE_LENGTH)
    alternative_limit: Annotated[
        int,
        Field(
            default=MIN_ALTERNATIVE_LIMIT,
            ge=MIN_ALTERNATIVE_LIMIT,
            le=MAX_ALTERNATIVE_LIMIT,
            strict=True,
        ),
    ] = MIN_ALTERNATIVE_LIMIT

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


class AlternativeOut(BaseModel):
    """备选恢复结果：编码、总分、逐位选择及相对首选的分差。"""

    code: str
    total_score: int
    score_gap: int
    choices: list[ChoiceOut]


class RecoverResponse(BaseModel):
    """恢复结果：编码、总分和逐位选择；请求备选时附加 alternatives。"""

    code: str
    total_score: int
    choices: list[ChoiceOut]
    alternatives: list[AlternativeOut] | None = None


class Fragment(Position):
    """对齐入口的源片段：复用候选结构，字符允许 A-Z 或 0-9。

    类别校验放在片段模型上（而非请求模型），这样多个非法片段的错误会
    被 Pydantic 一并收集，并由 loc 指出各自的源下标。
    """

    @model_validator(mode="after")
    def _check_alphanumeric(self) -> Fragment:
        for candidate in self.candidates:
            char = candidate.char
            if not ("A" <= char <= "Z" or "0" <= char <= "9"):
                raise ValueError(
                    f"character {char!r} is not an uppercase letter A-Z or digit 0-9"
                )
        return self


class RecoverAlignedRequest(BaseModel):
    """全局对齐请求：8 至 12 个 OCR 片段，不接受备选上限。"""

    model_config = ConfigDict(extra="forbid")

    fragments: list[Fragment] = Field(min_length=MIN_FRAGMENTS, max_length=MAX_FRAGMENTS)

    @model_validator(mode="wrap")
    @classmethod
    def _merge_count_and_item_errors(
        cls, data: object, handler: object
    ) -> RecoverAlignedRequest:
        # Pydantic 在列表长度越界时会吞掉片段内的候选错误（超长时尤甚，
        # 且原生长度错误还会重复两次），这里合并长度错误与每个片段的候选
        # 错误，去重后一次报全。
        raw = data.get("fragments") if isinstance(data, dict) else None
        count = len(raw) if isinstance(raw, list) else None
        try:
            return handler(data)  # type: ignore[misc]
        except ValidationError as exc:
            if count is None or MIN_FRAGMENTS <= count <= MAX_FRAGMENTS:
                raise
            line_errors: list[InitErrorDetails] = []
            seen: set[tuple[str, tuple[object, ...]]] = set()

            def add(
                error_type: str,
                loc: tuple[object, ...],
                *,
                input_value: object = None,
                ctx: dict[str, object] | None = None,
                include_input: bool = False,
            ) -> None:
                key = (error_type, loc)
                if key in seen:
                    return
                seen.add(key)
                detail: InitErrorDetails = {"type": error_type, "loc": loc}  # type: ignore[typeddict-item]
                if include_input:
                    detail["input"] = input_value
                if ctx:
                    detail["ctx"] = ctx  # type: ignore[typeddict-item]
                line_errors.append(detail)

            # 1) 保留原生的顶层错误（如多余字段 alternative_limit）；片段
            #    条目级错误全部由下一步逐片段校验重新产出，避免重复。
            for error in exc.errors():
                loc = tuple(error["loc"])
                if loc[:1] == ("fragments",):
                    continue
                add(
                    error["type"],
                    loc,
                    input_value=error.get("input"),
                    ctx=error.get("ctx"),
                    include_input="input" in error,
                )

            # 2) 逐个片段自行校验：超长列表时原生校验会跳过条目。
            for index, item in enumerate(raw):  # type: ignore[union-attr]
                try:
                    Fragment.model_validate(item)
                except ValidationError as item_exc:
                    for error in item_exc.errors():
                        add(
                            error["type"],
                            ("fragments", index, *error["loc"]),
                            input_value=error.get("input"),
                            ctx=error.get("ctx"),
                            include_input="input" in error,
                        )

            # 3) 恰好一条长度错误（position 为 null）。
            add(
                "too_short" if count < MIN_FRAGMENTS else "too_long",
                ("fragments",),
                input_value=raw,
                ctx={
                    "field_type": "List",
                    "min_length": MIN_FRAGMENTS,
                    "max_length": MAX_FRAGMENTS,
                    "actual_length": count,
                },
                include_input=True,
            )
            raise ValidationError.from_exception_data(
                cls.__name__, line_errors
            ) from exc


class AlignedMatchOut(BaseModel):
    """一个目标位的对齐来源：源片段下标，或补位（source_index 为 null）。"""

    position: int
    char: str
    confidence: int
    source_index: int | None


class IgnoredFragmentOut(BaseModel):
    """被忽略的源片段：原始下标及其候选（供馆藏员复核污点）。"""

    source_index: int
    candidates: list[Candidate]


class RecoverAlignedResponse(BaseModel):
    """对齐结果：编码、得分、编辑次数、逐目标位来源与被忽略源片段。"""

    code: str
    total_score: int
    edits: int
    matches: list[AlignedMatchOut]
    ignored_fragments: list[IgnoredFragmentOut]
