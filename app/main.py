"""FastAPI 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI

from app.errors import NoValidCombinationError, register_exception_handlers
from app.response import build_response
from app.schemas import RecoverRequest, RecoverResponse
from app.solver import find_best_solution

app = FastAPI(title="Museum Label Recovery API", version="1.0.0")
register_exception_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/recover", response_model=RecoverResponse)
def recover_label(request: RecoverRequest) -> RecoverResponse:
    solution = find_best_solution(request.positions)
    if solution is None:
        raise NoValidCombinationError(
            "no candidate combination satisfies the code format and checksum"
        )
    return build_response(solution)
