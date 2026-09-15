"""FastAPI 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI

from app.alignment import align_fragments
from app.errors import NoValidCombinationError, register_exception_handlers
from app.response import build_aligned_response, build_response
from app.schemas import (
    RecoverAlignedRequest,
    RecoverAlignedResponse,
    RecoverRequest,
    RecoverResponse,
)
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
    return build_response(
        best, alternatives, include_alternatives=request.alternative_limit > 0
    )


@app.post("/recover-aligned", response_model=RecoverAlignedResponse)
def recover_aligned_label(request: RecoverAlignedRequest) -> RecoverAlignedResponse:
    alignment = align_fragments(request.fragments)
    if alignment is None:
        raise NoValidCombinationError(
            "no alignment within two edits satisfies the code format and checksum"
        )
    return build_aligned_response(alignment, request.fragments)
