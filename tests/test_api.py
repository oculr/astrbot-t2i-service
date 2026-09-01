import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src import api
from src.storage import StoredImage


class FakeRenderer:
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.requested_url: str | None = None
        self.requested_options = None

    async def from_html(self, html: str):
        return "data/rendered_test.html", str(self.output_path.with_suffix(".html"))

    async def html2pic(self, html_file_path, screenshot_options):
        self.output_path.write_bytes(b"png")
        return str(self.output_path)

    async def url2pic(self, url, screenshot_options):
        self.requested_url = url
        self.requested_options = screenshot_options
        self.output_path.write_bytes(b"png")
        return str(self.output_path)


class FakeStorage:
    def __init__(self):
        self.saved_path: str | None = None

    async def save(self, image_path: str) -> str:
        self.saved_path = image_path
        return "rendered_test.png"

    async def get(self, image_id: str):
        if image_id == "rendered_test.png":
            return StoredImage(content=b"png", media_type="image/png")
        return None


def test_generate_json_response_remains_compatible(tmp_path, monkeypatch):
    output_path = tmp_path / "rendered_test.png"
    storage = FakeStorage()
    monkeypatch.setattr(api, "render", FakeRenderer(output_path))
    monkeypatch.setattr(api, "image_storage", storage)

    response = asyncio.run(
        api.text2img(
            api.GenerateRequest(
                html="<html><body>test</body></html>",
                json=True,
            )
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "code": 0,
        "message": "success",
        "data": {"id": "data/rendered_test.png"},
    }
    assert storage.saved_path == str(output_path)


def test_get_image_response_remains_compatible(monkeypatch):
    monkeypatch.setattr(api, "image_storage", FakeStorage())

    response = asyncio.run(api.text2img_image("rendered_test.png"))

    assert response.status_code == 200
    assert response.body == b"png"
    assert response.media_type == "image/png"


def test_get_missing_image_response_remains_compatible(monkeypatch):
    monkeypatch.setattr(api, "image_storage", FakeStorage())

    response = asyncio.run(api.text2img_image("missing.png"))

    assert response.status_code == 404
    assert json.loads(response.body) == {
        "code": 1,
        "message": "file not found",
        "data": {},
    }


def test_url_generate_returns_image(tmp_path, monkeypatch):
    output_path = tmp_path / "url_render.png"
    renderer = FakeRenderer(output_path)
    monkeypatch.setattr(api, "render", renderer)

    response = asyncio.run(
        api.url2img(api.UrlGenerateRequest(url="https://example.com/page"))
    )

    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert renderer.requested_url == "https://example.com/page"
    assert renderer.requested_options.type == "png"
    assert renderer.requested_options.full_page is True


def test_url_generate_supports_json_response(tmp_path, monkeypatch):
    output_path = tmp_path / "url_render.png"
    renderer = FakeRenderer(output_path)
    storage = FakeStorage()
    monkeypatch.setattr(api, "render", renderer)
    monkeypatch.setattr(api, "image_storage", storage)

    response = asyncio.run(
        api.url2img(
            api.UrlGenerateRequest(
                url="http://localhost:3000/preview",
                options=api.ScreenshotOptions(viewport_width=1200),
                json=True,
            )
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body)["data"] == {"id": "data/rendered_test.png"}
    assert renderer.requested_url == "http://localhost:3000/preview"
    assert renderer.requested_options.viewport_width == 1200
    assert storage.saved_path == str(output_path)


def test_url_generate_rejects_non_http_url():
    with pytest.raises(ValidationError):
        api.UrlGenerateRequest(url="file:///etc/passwd")


def test_url_image_data_route_is_registered():
    paths = {route.path for route in api.app.routes}
    assert "/url2img/data/{id}" in paths
