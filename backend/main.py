from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import app_allowed_origins
from .routes import router

app = FastAPI(title="Overseas Ads Agent MVP", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
def index() -> dict[str, str]:
    return {
        "name": "Overseas Ads Agent API",
        "frontend": "Run the Next.js workbench from frontend/ at http://127.0.0.1:3000/app",
        "api": "/api",
    }
