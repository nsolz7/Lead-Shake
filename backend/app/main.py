from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import get_settings
from app.observability import configure_logging, request_logging_middleware


settings = get_settings()
configure_logging()

# Interactive docs and the OpenAPI schema are development conveniences only.
# Outside local environments they hand attackers a complete endpoint map.
_docs_kwargs = (
    {}
    if settings.is_local
    else {"docs_url": None, "redoc_url": None, "openapi_url": None}
)

app = FastAPI(title=settings.app_name, version="0.1.0", **_docs_kwargs)
app.middleware("http")(request_logging_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router)


@app.get("/health")
def health() -> dict:
    """Liveness probe. Dependency detail lives at the authenticated
    /api/system/health so infrastructure state is not disclosed publicly."""
    return {"status": "ok"}
