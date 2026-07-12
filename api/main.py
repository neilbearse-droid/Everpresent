from fastapi import FastAPI

from api.routes import admin, health, me, tenant

# Schema is managed by Alembic (`alembic upgrade head`, run by the deploy
# script before the stack comes up); the app never create_all's in prod.
app = FastAPI(title="EverPresent v3")
app.include_router(health.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(tenant.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
