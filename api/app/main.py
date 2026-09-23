from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401  -- registra las tablas en Base.metadata
from app.config import settings
from app.database import Base, engine
from app.routers import auth, bounties


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# El frontend vive en otro dominio. La sesion viaja en la cabecera
# Authorization, no en cookies, asi que no hacen falta credenciales.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(bounties.router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}
