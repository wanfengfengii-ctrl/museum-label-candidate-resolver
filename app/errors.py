"""领域错误与异常处理：错误响应须指出位置与原因。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_POSITION_RE = re.compile(r"position (\d+)")


class NoValidCombinationError(Exception):
    """所有候选组合均不满足格式或校验式。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _position_from_loc(loc: Sequence[Any]) -> int | None:
    for index, part in enumerate(loc):
        if part in ("positions", "fragments") and index + 1 < len(loc):
            following = loc[index + 1]
            if isinstance(following, int):
                return following
    return None


def _sort_details(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 无源位置项在前，其余按源位置升序；同位置保持原有相对顺序。
    details.sort(
        key=lambda detail: (
            1 if detail["position"] is not None else 0,
            detail["position"] if detail["position"] is not None else 0,
        )
    )
    return details


def _format_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        message = str(error.get("msg", "invalid request"))
        position = _position_from_loc(error.get("loc", ()))
        if position is None:
            match = _POSITION_RE.search(message)
            if match:
                position = int(match.group(1))
        reason = message.removeprefix("Value error, ")
        details.append({"position": position, "reason": reason})
    return details


async def _handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = _format_validation_errors(exc)
    # /recover-aligned 的 422 约定：无源位置项在前，其余按源位置升序；
    # /recover 保持原有错误顺序不变。
    if request.url.path == "/recover-aligned":
        _sort_details(details)
    return JSONResponse(
        status_code=422, content={"detail": details}
    )


async def _handle_no_valid_combination(
    request: Request, exc: NoValidCombinationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": [{"position": None, "reason": exc.reason}]},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(NoValidCombinationError, _handle_no_valid_combination)
