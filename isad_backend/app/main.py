import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.routes import router

app = FastAPI(
    title="ИСАД — интеллектуальная система анализа договоров аренды",
    version="0.1.0",
    description=(
        "Технический анализ текста договора аренды. Не является юридическим заключением. "
        "Только учебные/обезличенные документы. Текст может отправляться во внешний LLM."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-API-Key"],
)


def _api_key() -> str:
    return (os.getenv("API_KEY") or "").strip()


def _llm_configured() -> bool:
    return bool(
        (os.getenv("LLM_BASE_URL") or "").strip()
        and (os.getenv("LLM_API_KEY") or "").strip()
        and (os.getenv("LLM_MODEL") or "").strip()
    )


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    path = request.url.path
    open_paths = {"/health", "/docs", "/redoc", "/openapi.json"}
    expected = _api_key()
    if expected and path not in open_paths and not path.startswith("/docs"):
        provided = request.headers.get("X-API-Key", "")
        if provided != expected:
            return JSONResponse(
                status_code=401,
                content={"detail": "Требуется заголовок X-API-Key. См. README: API_KEY в .env."},
            )
    return await call_next(request)


app.include_router(router)


@app.get("/health")
def health():
    llm_ok = _llm_configured()
    return {
        "status": "ok" if llm_ok else "degraded",
        "api_key_required": bool(_api_key()),
        "llm_configured": llm_ok,
        "llm": {
            "base_url_set": bool((os.getenv("LLM_BASE_URL") or "").strip()),
            "api_key_set": bool((os.getenv("LLM_API_KEY") or "").strip()),
            "model_set": bool((os.getenv("LLM_MODEL") or "").strip()),
            "model": (os.getenv("LLM_MODEL") or None) or None,
        },
        "message": (
            None
            if llm_ok
            else "LLM не настроен: заполните LLM_BASE_URL, LLM_API_KEY, LLM_MODEL в .env"
        ),
    }