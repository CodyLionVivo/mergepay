from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  -- registra las tablas en Base.metadata
from app.config import settings
from app.database import Base, engine
from app.routers import bounties


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(bounties.router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}
