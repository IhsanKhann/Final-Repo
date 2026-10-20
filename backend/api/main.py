"""The ASGI entry point. Loads .env, mounts the twelve endpoints, contains every error.

This is an entry point, which in this repo means exactly one thing: it is allowed -- and
required -- to call `config.load_env()`. No library module may. The failure that rule
prevents is silent and expensive: a valid key sits in a .env file that nothing reads, and
every agent reports no-key while the Health page still looks plausible.
`tests/test_env_is_loaded.py` asserts this by reading source, not by importing and hoping.

What this module refuses to do:
  * It refuses to need a credential to start. With nothing configured the app boots, every
    route answers, and /api/health says `degraded` with the reason (README section 7).
  * It refuses to leak a traceback. Three handlers turn anything that reaches the outer
    seam into a typed `Problem` body, so the frontend's ApiError always has something to
    show and a stack trace never becomes a response.
  * It refuses to do work. No route logic, no pipeline, no storage decisions -- those are
    `routes_*.py` and the `PipelineService` behind them.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api import routes_batches, routes_documents, routes_mappings, routes_meta
from backend.api.deps import ApiProblem, Problem
from backend.engine.config import load_env

__all__ = ["app", "create_app", "load_environment"]

#: The dev origins the Vite server runs on. Not "*", because a wildcard with credentials
#: is a browser error rather than a permissive default, and this list is what the frontend
#: actually uses (README section 7).
DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]


def load_environment() -> list[str]:
    """Call `load_env()` for every place a .env legitimately lives. Entry points only.

    Two paths, because the repo has both: `load_env()` with no argument looks for the file
    beside the repo root, and this project's .env sits in `backend/`. Loading is
    override=False, so the first file wins and a second call cannot clobber a real value.
    Returns the paths that were actually read, for the startup line and for the test.
    """
    root = Path(__file__).resolve().parents[2]
    loaded: list[str] = []
    for candidate in (root / ".env", root / "backend" / ".env"):
        if load_env(candidate):
            loaded.append(str(candidate))
    return loaded


def create_app() -> FastAPI:
    loaded = load_environment()

    app = FastAPI(
        title="Canon API",
        version="0.1.0",
        summary="Cross-source data standardization. Twelve endpoints, thin by rule.",
        description=(
            "The contract is Frontend/src/api/types.ts. No API key is needed to start: "
            "with none configured /api/health reports `degraded` with the reason and "
            "every route still answers."
        ),
    )
    app.state.env_files_loaded = loaded

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS + _extra_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    @app.exception_handler(ApiProblem)
    async def _api_problem(_request, exc: ApiProblem) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.problem.model_dump())

    @app.exception_handler(RequestValidationError)
    async def _validation(_request, exc: RequestValidationError) -> JSONResponse:
        # The frontend reads the body as text, so the first error has to be legible in it.
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        detail = f"{where or 'body'}: {first.get('msg', 'invalid request')}"
        return JSONResponse(
            status_code=422,
            content=Problem(detail=detail, code="invalid_payload").model_dump(),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request, exc: Exception) -> JSONResponse:
        # Containment at the outermost seam: the type, never the trace. If this fires, the
        # bug is below -- a layer raised across a boundary that was supposed to return.
        return JSONResponse(
            status_code=500,
            content=Problem(
                detail=f"internal error ({type(exc).__name__})", code="internal_error"
            ).model_dump(),
        )

    app.include_router(routes_meta.router)
    app.include_router(routes_batches.router)
    app.include_router(routes_documents.router)
    app.include_router(routes_mappings.router)
    return app


def _extra_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS") or ""
    return [o.strip() for o in raw.split(",") if o.strip()]


app = create_app()


if __name__ == "__main__":  # pragma: no cover - the other entry point, same rule
    load_environment()
    import uvicorn

    uvicorn.run(
        "backend.api.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
