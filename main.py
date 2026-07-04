from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import importar, status
from routers import auth as auth_router
from routers import historico as historico_router
from routers import usuarios as usuarios_router
from routers import vendas as vendas_router
from routers import vendas_semana as vendas_semana_router
from routers import metas as metas_router
from routers import vendedores as vendedores_router
from routers import fiado as fiado_router

app = FastAPI(title="Hayashi API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(usuarios_router.router, prefix="/admin/usuarios", tags=["usuarios"])
app.include_router(importar.router, prefix="/importar", tags=["importar"])
app.include_router(status.router, prefix="/status", tags=["status"])
app.include_router(vendas_router.router, prefix="/vendas", tags=["vendas"])
app.include_router(historico_router.router, prefix="/historico", tags=["historico"])
app.include_router(vendas_semana_router.router, prefix="/vendas-semana", tags=["vendas-semana"])
app.include_router(metas_router.router, prefix="/metas", tags=["metas"])
app.include_router(vendedores_router.router, prefix="/vendedores", tags=["vendedores"])
app.include_router(fiado_router.router, prefix="/fiado", tags=["fiado"])


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
