from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_users.schemas import BaseUser, BaseUserCreate, BaseUserUpdate

from app.auth import auth_backend, fastapi_users
from app.config import settings
from app.database import Base, engine
from app.routers import companies, debt, excel, financials, forecasts


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (use alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Credit Analysis API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth routes
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(BaseUser, BaseUserCreate),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(BaseUser, BaseUserUpdate),
    prefix="/users",
    tags=["users"],
)

# Business routes
app.include_router(companies.router)
app.include_router(financials.router)
app.include_router(forecasts.router)
app.include_router(excel.router)
app.include_router(debt.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
