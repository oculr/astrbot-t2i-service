import asyncio
import io
import stat
import zipfile

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from src import api
from src.websites import (
    WebsiteImportError,
    WebsiteManager,
    WebsiteNotFoundError,
    WebsiteTooLargeError,
)


def make_zip(files: dict[str, bytes]) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    buffer.seek(0)
    return buffer


def test_zip_import_hosts_static_site_and_spa_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_PUBLIC_URL_PREFIX", "https://images.example.com/t2i/")
    manager = WebsiteManager(tmp_path / "websites")
    upload = UploadFile(
        make_zip(
            {
                "site/index.html": b"<html>home</html>",
                "site/assets/app.js": b"console.log('ready')",
            }
        ),
        filename="site.zip",
    )

    site = asyncio.run(manager.import_zip(upload))
    path, url = manager.public_location(site.site_id)

    assert path == f"/websites/{site.site_id}/"
    assert url == f"https://images.example.com/t2i/websites/{site.site_id}/"
    assert manager.resolve_file(site.site_id).read_bytes() == b"<html>home</html>"
    assert manager.resolve_file(site.site_id, "assets/app.js").read_bytes() == (
        b"console.log('ready')"
    )
    assert manager.resolve_file(site.site_id, "dashboard").name == "index.html"
    assert manager.resolve_file(site.site_id, "assets/missing.js") is None
    assert manager.resolve_file(site.site_id, "../outside") is None


def test_zip_import_rejects_path_traversal(tmp_path):
    manager = WebsiteManager(tmp_path / "websites")
    upload = UploadFile(
        make_zip({"index.html": b"ok", "../outside.txt": b"unsafe"}),
        filename="unsafe.zip",
    )

    with pytest.raises(WebsiteImportError, match="unsafe"):
        asyncio.run(manager.import_zip(upload))

    assert not (tmp_path / "outside.txt").exists()


def test_zip_import_rejects_symbolic_links(tmp_path):
    manager = WebsiteManager(tmp_path / "websites")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("index.html", b"ok")
        link = zipfile.ZipInfo("assets/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(link, "../../outside")
    archive.seek(0)

    with pytest.raises(WebsiteImportError, match="symbolic link"):
        asyncio.run(
            manager.import_zip(UploadFile(archive, filename="symlink.zip"))
        )


def test_zip_import_enforces_archive_size_limit(tmp_path):
    manager = WebsiteManager(tmp_path / "websites")
    manager.max_archive_bytes = 16
    upload = UploadFile(
        make_zip({"index.html": b"larger than the configured archive limit"}),
        filename="large.zip",
    )

    with pytest.raises(WebsiteTooLargeError, match="too large"):
        asyncio.run(manager.import_zip(upload))


def test_zip_import_can_select_build_subdirectory(tmp_path):
    manager = WebsiteManager(tmp_path / "websites")
    upload = UploadFile(
        make_zip(
            {
                "package.json": b"{}",
                "dist/index.html": b"<html>built</html>",
            }
        ),
        filename="source.zip",
    )

    site = asyncio.run(manager.import_zip(upload, subdirectory="dist"))

    assert manager.resolve_file(site.site_id).read_bytes() == b"<html>built</html>"
    assert manager.resolve_file(site.site_id, "package.json") is None


def test_git_import_uses_cloned_static_output(tmp_path, monkeypatch):
    manager = WebsiteManager(tmp_path / "websites")
    calls = []

    async def fake_clone(repository_url, destination, ref):
        calls.append((repository_url, ref))
        (destination / "dist").mkdir(parents=True)
        (destination / "dist" / "index.html").write_text("built", encoding="utf-8")
        git_object = destination / ".git" / "objects" / "example"
        git_object.parent.mkdir(parents=True)
        git_object.write_bytes(b"git metadata")
        git_object.chmod(stat.S_IREAD)

    monkeypatch.setattr(manager, "_clone_git", fake_clone)

    site = asyncio.run(
        manager.import_git(
            "https://example.com/frontend.git",
            ref="v1.2.3",
            subdirectory="dist",
        )
    )

    assert calls == [("https://example.com/frontend.git", "v1.2.3")]
    assert manager.resolve_file(site.site_id).read_text(encoding="utf-8") == "built"
    assert not list(manager.root.glob(".incoming-*"))


def test_git_import_rejects_embedded_credentials(tmp_path):
    manager = WebsiteManager(tmp_path / "websites")

    with pytest.raises(WebsiteImportError, match="credential-free"):
        asyncio.run(
            manager.import_git("https://user:secret@example.com/frontend.git")
        )


def test_list_replace_and_delete_site(tmp_path):
    manager = WebsiteManager(tmp_path / "websites")
    first = asyncio.run(
        manager.import_zip(
            UploadFile(
                make_zip(
                    {
                        "index.html": b"old",
                        "assets/old.js": b"old asset",
                    }
                ),
                filename="old.zip",
            )
        )
    )
    second = asyncio.run(
        manager.import_zip(
            UploadFile(make_zip({"index.html": b"second"}), filename="second.zip")
        )
    )

    assert [site.site_id for site in manager.list_sites()] == sorted(
        [first.site_id, second.site_id]
    )

    replacement = asyncio.run(
        manager.import_zip(
            UploadFile(
                make_zip(
                    {
                        "index.html": b"new",
                        "assets/new.js": b"new asset",
                    }
                ),
                filename="new.zip",
            ),
        )
    )
    replaced = asyncio.run(manager.replace_site(first.site_id, replacement.site_id))

    assert replaced.site_id == first.site_id
    assert manager.resolve_file(first.site_id).read_bytes() == b"new"
    assert manager.resolve_file(first.site_id, "assets/new.js").is_file()
    assert manager.resolve_file(first.site_id, "assets/old.js") is None
    assert manager.get_site(replacement.site_id) is None
    assert not list(manager.root.glob(".replacement-*"))
    assert not list(manager.root.glob(".backup-*"))

    asyncio.run(manager.delete_site(first.site_id))
    assert manager.get_site(first.site_id) is None
    assert [site.site_id for site in manager.list_sites()] == [second.site_id]
    with pytest.raises(WebsiteNotFoundError):
        asyncio.run(manager.delete_site(first.site_id))


def test_replace_site_with_git_import_preserves_id(tmp_path, monkeypatch):
    manager = WebsiteManager(tmp_path / "websites")
    site = asyncio.run(
        manager.import_zip(
            UploadFile(make_zip({"index.html": b"old"}), filename="old.zip")
        )
    )

    async def fake_clone(repository_url, destination, ref):
        destination.mkdir(parents=True)
        (destination / "index.html").write_bytes(b"from git")

    monkeypatch.setattr(manager, "_clone_git", fake_clone)

    replacement = asyncio.run(
        manager.import_git(
            "https://example.com/site.git",
            ref="main",
        )
    )
    replaced = asyncio.run(manager.replace_site(site.site_id, replacement.site_id))

    assert replaced.site_id == site.site_id
    assert manager.resolve_file(site.site_id).read_bytes() == b"from git"


def test_missing_replacement_preserves_existing_site(tmp_path):
    manager = WebsiteManager(tmp_path / "websites")
    site = asyncio.run(
        manager.import_zip(
            UploadFile(make_zip({"index.html": b"original"}), filename="old.zip")
        )
    )

    with pytest.raises(WebsiteNotFoundError, match="replacement"):
        asyncio.run(manager.replace_site(site.site_id, "f" * 32))

    assert manager.resolve_file(site.site_id).read_bytes() == b"original"


def test_zip_import_and_static_hosting_end_to_end(tmp_path, monkeypatch):
    manager = WebsiteManager(tmp_path / "websites")
    monkeypatch.setattr(api, "website_manager", manager)
    monkeypatch.delenv("WEB_PUBLIC_URL_PREFIX", raising=False)
    archive = make_zip(
        {
            "index.html": b"<html>hosted</html>",
            "assets/app.css": b"body { color: blue; }",
        }
    )

    client = TestClient(api.app)
    response = client.post(
        "/websites/import/zip",
        files={"file": ("site.zip", archive.getvalue(), "application/zip")},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["url"] == f"http://testserver{data['path']}"
    no_slash = client.get(data["path"].rstrip("/"), follow_redirects=False)
    assert no_slash.status_code == 307
    assert no_slash.headers["location"] == data["url"]
    assert client.post("/websites/mgmt", json={"action": "list"}).json()["data"] == {
        "items": [data],
        "total": 1,
    }
    assert client.post(
        "/websites/mgmt",
        json={"action": "get", "id": data["id"]},
    ).json()["data"] == data
    assert client.get(data["path"]).text == "<html>hosted</html>"
    assert client.get(f"{data['path']}assets/app.css").headers[
        "content-type"
    ].startswith("text/css")
    assert client.get(f"{data['path']}dashboard").text == "<html>hosted</html>"

    replacement = make_zip({"index.html": b"<html>replacement</html>"})
    replacement_response = client.post(
        "/websites/import/zip",
        files={
            "file": ("replacement.zip", replacement.getvalue(), "application/zip")
        },
    )
    replacement_data = replacement_response.json()["data"]
    replace_response = client.post(
        "/websites/mgmt",
        json={
            "action": "replace",
            "id": data["id"],
            "replacement_id": replacement_data["id"],
        },
    )
    assert replace_response.status_code == 200
    assert replace_response.json()["data"] == data
    assert client.get(data["path"]).text == "<html>replacement</html>"
    missing_replacement = client.post(
        "/websites/mgmt",
        json={"action": "get", "id": replacement_data["id"]},
    )
    assert missing_replacement.status_code == 404

    delete_response = client.post(
        "/websites/mgmt",
        json={"action": "delete", "id": data["id"]},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {"id": data["id"]}
    assert client.get(data["path"]).status_code == 404
    assert client.post("/websites/mgmt", json={"action": "list"}).json()[
        "data"
    ] == {"items": [], "total": 0}


def test_management_request_validation():
    client = TestClient(api.app)

    missing_id = client.post("/websites/mgmt", json={"action": "get"})
    unsupported_action = client.post(
        "/websites/mgmt",
        json={"action": "unknown"},
    )

    assert missing_id.status_code == 400
    assert missing_id.json()["message"] == "id is required"
    assert unsupported_action.status_code == 422
