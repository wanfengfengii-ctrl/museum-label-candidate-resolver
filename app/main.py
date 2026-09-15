"""FastAPI 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI

from app.errors import NoValidCombinationError, register_exception_handlers
from app.response import build_response
from app.schemas import RecoverRequest, RecoverResponse
from app.solver import find_ranked_solutions

app = FastAPI(title="Museum Label Recovery API", version="1.0.0")
register_exception_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/recover", response_model=RecoverResponse, response_model_exclude_none=True)
def recover_label(request: RecoverRequest) -> RecoverResponse:
    ranked = find_ranked_solutions(request.positions, request.alternative_limit + 1)
    if not ranked:
        raise NoValidCombinationError(
            "no candidate combination satisfies the code format and checksum"
        )
    best, alternatives = ranked[0], ranked[1:]
    return build_response(best, alternatives)
