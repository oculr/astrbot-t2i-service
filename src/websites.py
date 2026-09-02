from __future__ import annotations

import asyncio
import mimetypes
import os
import re
import shutil
import stat
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from fastapi import UploadFile


class WebsiteImportError(ValueError):
    pass


class WebsiteTooLargeError(WebsiteImportError):
    pass


@dataclass(frozen=True)
class HostedWebsite:
    site_id: str
    root: Path


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class WebsiteManager:
    SITE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
    REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.getenv("WEB_ROOT", "data/websites")).resolve()
        self.max_archive_bytes = _positive_env_int(
            "WEB_MAX_ARCHIVE_BYTES", 100 * 1024 * 1024
        )
        self.max_site_bytes = _positive_env_int(
            "WEB_MAX_SITE_BYTES", 500 * 1024 * 1024
        )
        self.max_site_files = _positive_env_int("WEB_MAX_SITE_FILES", 10_000)
        self.git_timeout_seconds = _positive_env_int(
            "WEB_GIT_TIMEOUT_SECONDS", 120
        )
        self.root.mkdir(parents=True, exist_ok=True)

    def public_location(
        self, site_id: str, fallback_prefix: str = ""
    ) -> tuple[str, str]:
        path = f"/websites/{site_id}/"
        prefix = (
            os.getenv("WEB_PUBLIC_URL_PREFIX", "").strip() or fallback_prefix
        ).rstrip("/")
        return path, f"{prefix}{path}" if prefix else path

    def site_exists(self, site_id: str) -> bool:
        return self._site_root(site_id) is not None

    def resolve_file(self, site_id: str, file_path: str = "") -> Path | None:
        site_root = self._site_root(site_id)
        if site_root is None:
            return None

        relative_path = file_path.replace("\\", "/").lstrip("/")
        candidate = (site_root / relative_path).resolve()
        if not _is_within(candidate, site_root):
            return None

        if candidate.is_dir():
            candidate = candidate / "index.html"
        if candidate.is_file():
            return candidate

        # Support client-side routing without returning HTML for missing assets.
        if not Path(relative_path).suffix:
            index = site_root / "index.html"
            if index.is_file():
                return index
        return None

    def media_type(self, path: Path) -> str:
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    async def import_zip(
        self, upload: UploadFile, subdirectory: str | None = None
    ) -> HostedWebsite:
        token = uuid.uuid4().hex
        archive_path = self.root / f".incoming-{token}.zip"
        extract_root = self.root / f".incoming-{token}"
        try:
            await self._save_upload(upload, archive_path)
            await asyncio.to_thread(self._extract_zip, archive_path, extract_root)
            return await asyncio.to_thread(
                self._publish_site, extract_root, subdirectory
            )
        finally:
            archive_path.unlink(missing_ok=True)
            await asyncio.to_thread(self._remove_tree, extract_root)
            await upload.close()

    async def import_git(
        self,
        repository_url: str,
        ref: str | None = None,
        subdirectory: str | None = None,
    ) -> HostedWebsite:
        self._validate_git_url(repository_url)
        if ref and (not self.REF_PATTERN.fullmatch(ref) or ".." in ref):
            raise WebsiteImportError("invalid git ref")

        clone_root = self.root / f".incoming-{uuid.uuid4().hex}"
        try:
            await self._clone_git(repository_url, clone_root, ref)
            return await asyncio.to_thread(self._publish_site, clone_root, subdirectory)
        finally:
            await asyncio.to_thread(self._remove_tree, clone_root)

    async def _save_upload(self, upload: UploadFile, destination: Path) -> None:
        total = 0
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > self.max_archive_bytes:
                    raise WebsiteTooLargeError("zip archive is too large")
                output.write(chunk)

    def _extract_zip(self, archive_path: Path, destination: Path) -> None:
        if not zipfile.is_zipfile(archive_path):
            raise WebsiteImportError("uploaded file is not a valid zip archive")

        destination.mkdir(parents=True, exist_ok=False)
        destination_root = destination.resolve()
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > self.max_site_files:
                raise WebsiteTooLargeError("zip archive contains too many files")

            extracted_bytes = 0
            for member in members:
                normalized = member.filename.replace("\\", "/")
                member_path = PurePosixPath(normalized)
                if (
                    not normalized
                    or not member_path.parts
                    or member_path.is_absolute()
                    or ".." in member_path.parts
                    or "." in member_path.parts
                    or ":" in member_path.parts[0]
                    or member.flag_bits & 0x1
                ):
                    raise WebsiteImportError("zip archive contains an unsafe entry")

                file_mode = member.external_attr >> 16
                if stat.S_ISLNK(file_mode):
                    raise WebsiteImportError("zip archive contains a symbolic link")

                extracted_bytes += member.file_size
                if extracted_bytes > self.max_site_bytes:
                    raise WebsiteTooLargeError("extracted website is too large")

                target = (destination / Path(*member_path.parts)).resolve()
                if not _is_within(target, destination_root):
                    raise WebsiteImportError("zip archive contains an unsafe path")

                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)

    async def _clone_git(
        self, repository_url: str, destination: Path, ref: str | None
    ) -> None:
        command = ["git", "clone", "--depth", "1", "--single-branch"]
        if ref:
            command.extend(["--branch", ref])
        command.extend(["--", repository_url, str(destination)])

        environment = dict(os.environ)
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise WebsiteImportError("git is not installed") from exc

        try:
            await asyncio.wait_for(
                process.communicate(), timeout=self.git_timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise WebsiteImportError("git clone timed out") from exc
        if process.returncode != 0:
            raise WebsiteImportError("git clone failed")

    def _publish_site(
        self, imported_root: Path, subdirectory: str | None
    ) -> HostedWebsite:
        source = self._select_source(imported_root, subdirectory)
        self._validate_tree(source)

        site_id = uuid.uuid4().hex
        destination = self.root / site_id
        try:
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns(".git"),
            )
        except Exception:
            self._remove_tree(destination)
            raise
        return HostedWebsite(site_id=site_id, root=destination)

    def _select_source(self, root: Path, subdirectory: str | None) -> Path:
        root = root.resolve()
        if subdirectory:
            normalized = PurePosixPath(subdirectory.replace("\\", "/"))
            if normalized.is_absolute() or ".." in normalized.parts:
                raise WebsiteImportError("invalid website subdirectory")
            source = (root / Path(*normalized.parts)).resolve()
            if not _is_within(source, root) or not source.is_dir():
                raise WebsiteImportError("website subdirectory was not found")
        else:
            source = root
            if not (source / "index.html").is_file():
                entries = [
                    entry
                    for entry in source.iterdir()
                    if entry.name not in {".git", "__MACOSX", ".DS_Store"}
                ]
                if len(entries) == 1 and entries[0].is_dir():
                    source = entries[0]

        if not (source / "index.html").is_file():
            raise WebsiteImportError(
                "index.html was not found; specify the built output subdirectory"
            )
        return source

    def _validate_tree(self, root: Path) -> None:
        total_bytes = 0
        file_count = 0
        for entry in root.rglob("*"):
            relative = entry.relative_to(root)
            if ".git" in relative.parts:
                continue
            if entry.is_symlink():
                raise WebsiteImportError("website contains a symbolic link")
            if not entry.is_file():
                continue
            file_count += 1
            total_bytes += entry.stat().st_size
            if file_count > self.max_site_files:
                raise WebsiteTooLargeError("website contains too many files")
            if total_bytes > self.max_site_bytes:
                raise WebsiteTooLargeError("website is too large")

    def _site_root(self, site_id: str) -> Path | None:
        if not self.SITE_ID_PATTERN.fullmatch(site_id):
            return None
        candidate = (self.root / site_id).resolve()
        if not _is_within(candidate, self.root) or not candidate.is_dir():
            return None
        return candidate

    def _validate_git_url(self, repository_url: str) -> None:
        parsed = urlsplit(repository_url)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(character in repository_url for character in "\r\n\0")
        ):
            raise WebsiteImportError("repository URL must be a credential-free HTTP(S) URL")

    @staticmethod
    def _remove_tree(path: Path) -> None:
        def make_writable(function, filename, _error_info):
            os.chmod(filename, stat.S_IWRITE)
            function(filename)

        if not path.exists():
            return
        try:
            shutil.rmtree(path, onerror=make_writable)
        except OSError:
            # Cleanup must not replace the original import result or error.
            pass
