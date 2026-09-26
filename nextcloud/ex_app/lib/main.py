"""FastAPI entry point served behind the Nextcloud AppAPI proxy."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from nc_py_api.ex_app import AppAPIAuthMiddleware, anc_app, set_handlers
from pydantic import BaseModel, ConfigDict, Field

from .service import (
    AppDisabled, ModelNotReady, RootOverlap, RootUnavailable, ServiceError,
    SkjalfService, VectorStoreUnavailable,
)

APP_ID = os.getenv("APP_ID", "skjalf")
MENU_ENTRY = "skjalf"
MODEL_NAME = "kakaobrain/align-base"
PERSISTENT = Path(os.getenv("APP_PERSISTENT_STORAGE", "/app_data"))
MODEL_CACHE = PERSISTENT / "models"
APP_ROOT = Path(__file__).resolve().parents[1]
service = SkjalfService(PERSISTENT / "state", MODEL_CACHE)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await service.shutdown()
        service.close()


APP = FastAPI(title="Skjalf Nextcloud", docs_url=None, redoc_url=None, lifespan=lifespan)
APP.add_middleware(AppAPIAuthMiddleware)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RootBody(StrictBody):
    file_id: str = Field(min_length=1, max_length=300)


class SearchBody(StrictBody):
    query: str = Field(min_length=1, max_length=500)


@APP.exception_handler(RootUnavailable)
async def unavailable_handler(_request: Request, exc: RootUnavailable) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@APP.exception_handler(RootOverlap)
async def overlap_handler(_request: Request, exc: RootOverlap) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@APP.exception_handler(ServiceError)
async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@APP.exception_handler(ModelNotReady)
async def model_not_ready_handler(_request: Request, exc: ModelNotReady) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@APP.exception_handler(VectorStoreUnavailable)
async def vector_store_unavailable_handler(_request: Request, exc: VectorStoreUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@APP.exception_handler(AppDisabled)
async def app_disabled_handler(_request: Request, exc: AppDisabled) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


async def _enabled_handler(enabled: bool, nc: Any) -> str:
    """Register the Nextcloud top-menu entry only while this app is enabled."""
    await service.set_enabled(enabled)
    if enabled:
        await nc.ui.resources.set_script("top_menu", MENU_ENTRY, "js/skjalf-main")
        await nc.ui.top_menu.register(MENU_ENTRY, "Skjalf", "img/skjalf.svg", False)
    else:
        await nc.ui.top_menu.unregister(MENU_ENTRY)
    return ""


set_handlers(
    APP,
    _enabled_handler,
    models_to_fetch={MODEL_NAME: {"cache_dir": str(MODEL_CACHE)}},
)


def _index_file() -> Path:
    return APP_ROOT / "index.html"


@APP.get("/", include_in_schema=False)
async def index() -> FileResponse:
    if not _index_file().is_file():
        raise HTTPException(status_code=503, detail="Die Skjalf-Oberfläche wurde noch nicht gebaut.")
    return FileResponse(_index_file(), media_type="text/html; charset=utf-8")


@APP.get("/js/{asset:path}", include_in_schema=False)
async def javascript(asset: str) -> FileResponse:
    target = (APP_ROOT / "js" / asset).resolve()
    if APP_ROOT.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset nicht gefunden")
    return FileResponse(target, media_type="text/javascript")


@APP.get("/css/{asset:path}", include_in_schema=False)
async def stylesheet(asset: str) -> FileResponse:
    target = (APP_ROOT / "css" / asset).resolve()
    if APP_ROOT.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset nicht gefunden")
    return FileResponse(target, media_type="text/css")


@APP.get("/img/{asset:path}", include_in_schema=False)
async def image_asset(asset: str) -> FileResponse:
    target = (APP_ROOT / "img" / asset).resolve()
    if APP_ROOT.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset nicht gefunden")
    return FileResponse(target, media_type="image/svg+xml" if target.suffix == ".svg" else "application/octet-stream")


@APP.get("/api/folders")
async def folders(path: str = Query(default="", max_length=2048), nc: Any = Depends(anc_app)) -> dict[str, Any]:
    try:
        return {"folders": await service.browse(nc, path)}
    except ServiceError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@APP.get("/api/roots")
async def roots(nc: Any = Depends(anc_app)) -> dict[str, Any]:
    # Each UI open/refresh performs a complete, manual DAV reconcile. It never
    # starts image embedding and a failed scan cannot delete rows from a partial list.
    return {"roots": await service.list_and_reconcile(nc)}


@APP.post("/api/roots", status_code=201)
async def add_root(body: RootBody, nc: Any = Depends(anc_app)) -> dict[str, Any]:
    return {"root": await service.add_root(nc, body.file_id)}


@APP.delete("/api/roots/{root_id}", status_code=204)
async def remove_root(root_id: str, nc: Any = Depends(anc_app)) -> None:
    await service.remove_root(nc, root_id)


@APP.post("/api/roots/{root_id}/index")
async def start_index(root_id: str, nc: Any = Depends(anc_app)) -> dict[str, Any]:
    return {"root": await service.start(nc, root_id)}


@APP.post("/api/roots/{root_id}/pause")
async def pause_index(root_id: str, nc: Any = Depends(anc_app)) -> dict[str, Any]:
    return {"root": await service.pause(nc, root_id)}


@APP.post("/api/roots/{root_id}/search")
async def search(root_id: str, body: SearchBody, nc: Any = Depends(anc_app)) -> dict[str, Any]:
    return {"results": await service.search(nc, root_id, body.query)}


@APP.get("/api/status")
async def status(nc: Any = Depends(anc_app)) -> dict[str, Any]:
    user_id = await service.user_id(nc)
    return {"roots": service.roots(user_id)}
