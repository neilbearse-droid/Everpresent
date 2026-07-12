from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.db import init_db
from api.routes import health, me


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="EverPresent v3", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(me.router, prefix="/api")
