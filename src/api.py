import asyncio
import os
import secrets
import time
from collections import deque

import fastapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from jinja2.exceptions import SecurityError
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import AnyHttpUrl, BaseModel

from .metrics import (
    CLEANUP_DURATION,
    CLEANUP_FILES,
    CLEANUP_RUNS,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS,
    HTTP_REQUESTS_IN_PROGRESS,
    IMAGE_STORAGE_DURATION,
    IMAGE_STORAGE_OPERATIONS,
    METRICS_ENABLED,
    RATE_LIMIT_REJECTIONS,
    RENDER_INPUT_BYTES,
)
from .render import ScreenshotOptions, Text2ImgRender
from .storage import create_image_storage
from .util import cleanup_expired_files

app = fastapi.FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
render = Text2ImgRender()
image_storage = create_image_storage()
rate_limit_lock = asyncio.Lock()
rate_limit_timestamps: deque[float] = deque()
rate_limit_max_requests = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "0"))
rate_limit_window_seconds = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "0"))


def metric_route(path: str) -> str:
    if path.startswith("/text2img/data/"):
        return "/text2img/data/{id}"
    if path.startswith("/url2img/data/"):
        return "/url2img/data/{id}"
    if path in {
        "/text2img/generate",
        "/url2img/generate",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
    }:
        return path
    return "unmatched"


@app.middleware("http")
async def observe_http_requests(request: fastapi.Request, call_next):
    if not METRICS_ENABLED:
        return await call_next(request)

    method = request.method.upper()
    route_path = metric_route(request.url.path)
    started = time.perf_counter()
    status_code = 500
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()
        if route_path != "/metrics":
            HTTP_REQUESTS.labels(
                method=method,
                route=route_path,
                status_code=str(status_code),
            ).inc()
            HTTP_REQUEST_DURATION.labels(method=method, route=route_path).observe(
                time.perf_counter() - started
            )


class GenerateRequest(BaseModel):
    html: str | None = None
    tmpl: str | None = None
    tmplname: str | None = None
    tmpldata: dict | None = None
    options: ScreenshotOptions | None = None
    json: bool = False


class UrlGenerateRequest(BaseModel):
    url: AnyHttpUrl
    options: ScreenshotOptions | None = None
    json: bool = False


def default_screenshot_options() -> ScreenshotOptions:
    return ScreenshotOptions(
        timeout=None,
        type="png",
        quality=None,
        omit_background=None,
        full_page=True,
        clip=None,
        animations=None,
        caret=None,
        scale="device",
        viewport_width=None,
        viewport_height=None,
        device_scale_factor_level=None,
    )


def url_screenshot_options(options: ScreenshotOptions | None) -> ScreenshotOptions:
    resolved = options or default_screenshot_options()
    dynamic_defaults = {
        "navigation_wait_until": "load",
        "wait_after_load": 1_000,
        "auto_scroll": True,
        "wait_for_network_idle": True,
        "wait_for_images": True,
    }
    updates = {
        name: value
        for name, value in dynamic_defaults.items()
        if getattr(resolved, name) is None
    }
    return resolved.model_copy(update=updates)


async def image_response(pic: str, is_json_return: bool) -> Response:
    media_type = "image/png" if pic.endswith(".png") else "image/jpeg"

    if not is_json_return:
        return FileResponse(pic, media_type=media_type)

    started = time.perf_counter()
    try:
        image_id = await image_storage.save(pic)
    except Exception:
        IMAGE_STORAGE_OPERATIONS.labels(operation="save", result="error").inc()
        logger.exception("Failed to persist rendered image")
        return JSONResponse(
            status_code=500,
            content={
                "code": 1,
                "message": "image storage error",
                "data": {},
            },
        )
    finally:
        IMAGE_STORAGE_DURATION.labels(operation="save").observe(
            time.perf_counter() - started
        )
    IMAGE_STORAGE_OPERATIONS.labels(operation="save", result="success").inc()
    return JSONResponse(
        content={
            "code": 0,
            "message": "success",
            "data": {"id": f"data/{image_id}"},
        },
    )


# 启动时创建清理任务
@app.on_event("startup")
async def startup_event():
    """应用启动时的事件处理"""
    # 启动定期清理任务
    asyncio.create_task(periodic_cleanup())
    logger.info("Started periodic cleanup task")


async def periodic_cleanup():
    """定期清理过期文件的后台任务"""
    while True:
        started = time.perf_counter()
        try:
            cleaned = await asyncio.to_thread(cleanup_expired_files)
            CLEANUP_FILES.inc(cleaned)
            CLEANUP_RUNS.labels(result="success").inc()
        except Exception:
            CLEANUP_RUNS.labels(result="error").inc()
            logger.exception("Error during periodic cleanup")
        finally:
            CLEANUP_DURATION.observe(time.perf_counter() - started)
        # 每小时执行一次清理
        await asyncio.sleep(3600)


async def enforce_rate_limit() -> int | None:
    if rate_limit_max_requests <= 0 or rate_limit_window_seconds <= 0:
        return None
    now = time.monotonic()
    async with rate_limit_lock:
        while (
            rate_limit_timestamps
            and now - rate_limit_timestamps[0] >= rate_limit_window_seconds
        ):
            rate_limit_timestamps.popleft()
        if len(rate_limit_timestamps) >= rate_limit_max_requests:
            retry_after = rate_limit_window_seconds - (now - rate_limit_timestamps[0])
            return max(0, int(retry_after) + 1)
        rate_limit_timestamps.append(now)
    return None


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics(request: fastapi.Request):
    if not METRICS_ENABLED:
        return Response(status_code=404)

    metrics_token = os.getenv("METRICS_TOKEN", "")
    authorization = request.headers.get("Authorization", "")
    if metrics_token and not secrets.compare_digest(
        authorization,
        f"Bearer {metrics_token}",
    ):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    content = await asyncio.to_thread(generate_latest)
    return Response(
        content=content,
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


@app.get("/url2img/data/{id}")
@app.get("/text2img/data/{id}")
async def text2img_image(id: str):
    started = time.perf_counter()
    try:
        image = await image_storage.get(id)
    except Exception:
        IMAGE_STORAGE_OPERATIONS.labels(operation="get", result="error").inc()
        logger.exception("Failed to load image from storage")
        return JSONResponse(
            status_code=500,
            content={"code": 1, "message": "image storage error", "data": {}},
        )
    finally:
        IMAGE_STORAGE_DURATION.labels(operation="get").observe(
            time.perf_counter() - started
        )

    if image is None:
        IMAGE_STORAGE_OPERATIONS.labels(operation="get", result="not_found").inc()
        return JSONResponse(
            status_code=404,
            content={"code": 1, "message": "file not found", "data": {}},
        )
    IMAGE_STORAGE_OPERATIONS.labels(operation="get", result="success").inc()
    if image.path is not None:
        return FileResponse(image.path, media_type=image.media_type)
    return Response(content=image.content, media_type=image.media_type)


@app.post("/text2img/generate")
async def text2img(request: GenerateRequest):
    """
    html: str
    options: ScreenshotOptions
    """

    retry_after = await enforce_rate_limit()
    if retry_after is not None:
        RATE_LIMIT_REJECTIONS.inc()
        return JSONResponse(
            status_code=429,
            content={"code": 1, "message": "rate limit exceeded", "data": {}},
            headers={"Retry-After": str(retry_after)},
        )

    is_json_return = request.json or False
    if request.tmpl or request.tmplname:
        if request.tmpl:
            tmpl = request.tmpl
            source = "template"
        else:
            tmpl = open(f"tmpl/{request.tmplname}.html", "r", encoding="utf-8").read()
            source = "template_name"
        RENDER_INPUT_BYTES.labels(source=source).observe(len(tmpl.encode("utf-8")))
        try:
            _, abs_path = await render.from_jinja_template(tmpl, request.tmpldata or {})
        except SecurityError as e:
            return JSONResponse(
                status_code=400,
                content={"code": 1, "message": f"security error: {str(e)}", "data": {}},
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={
                    "code": 1,
                    "message": f"template render error: {str(e)}",
                    "data": {},
                },
            )
    elif request.html:
        RENDER_INPUT_BYTES.labels(source="html").observe(
            len(request.html.encode("utf-8"))
        )
        html = request.html
        _, abs_path = await render.from_html(html)
    else:
        return JSONResponse(
            status_code=400,
            content={"code": 1, "message": "html or tmpl not found", "data": {}},
        )
    options = request.options or default_screenshot_options()

    pic = await render.html2pic(abs_path, options)
    return await image_response(pic, is_json_return)


@app.post("/url2img/generate")
async def url2img(request: UrlGenerateRequest):
    """Navigate to a URL and return a screenshot of the rendered page."""
    retry_after = await enforce_rate_limit()
    if retry_after is not None:
        RATE_LIMIT_REJECTIONS.inc()
        return JSONResponse(
            status_code=429,
            content={"code": 1, "message": "rate limit exceeded", "data": {}},
            headers={"Retry-After": str(retry_after)},
        )

    options = url_screenshot_options(request.options)
    pic = await render.url2pic(str(request.url), options)
    return await image_response(pic, request.json)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8999)))
