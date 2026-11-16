from __future__ import annotations

import json
import os
import platform
import shutil
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GITHUB_LATEST_API = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    download_url: str
    asset_name: str


def windows_asset_name() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        arch = "64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64-v8a"
    elif machine in {"x86", "i386", "i686"}:
        arch = "32"
    else:
        raise RuntimeError(f"不支持的 Windows 架构：{machine}")
    return f"Xray-windows-{arch}.zip"


def apply_proxy(url: str, ghproxy: str) -> str:
    prefix = ghproxy.strip().rstrip("/")
    return f"{prefix}/{url}" if prefix else url


class XrayUpdater:
    def __init__(self, xray_dir: Path, ghproxy: str = "") -> None:
        self.xray_dir = xray_dir
        self.ghproxy = ghproxy

    def latest(self) -> ReleaseInfo:
        request = urllib.request.Request(
            GITHUB_LATEST_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "xray-ui"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload: dict[str, Any] = json.load(response)
        expected = windows_asset_name()
        for asset in payload.get("assets", []):
            if asset.get("name") == expected:
                return ReleaseInfo(
                    version=str(payload["tag_name"]),
                    download_url=str(asset["browser_download_url"]),
                    asset_name=expected,
                )
        raise RuntimeError(f"发布版本中未找到 {expected}")

    def installed_version(self) -> str | None:
        version_file = self.xray_dir / "version.txt"
        if version_file.exists():
            return version_file.read_text(encoding="utf-8").strip() or None
        return None

    def install(self, release: ReleaseInfo, progress: Callable[[int], None] | None = None) -> None:
        self.xray_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="xray-ui-update-") as temp_name:
            temp = Path(temp_name)
            archive = temp / release.asset_name
            self._download(apply_proxy(release.download_url, self.ghproxy), archive, progress)
            extract_dir = temp / "extract"
            with zipfile.ZipFile(archive) as package:
                self._safe_extract(package, extract_dir)
            if not (extract_dir / "xray.exe").exists():
                raise RuntimeError("下载包中缺少 xray.exe")
            for name in ("xray.exe", "geoip.dat", "geosite.dat"):
                source = extract_dir / name
                if source.exists():
                    target = self.xray_dir / name
                    staged = target.with_suffix(target.suffix + ".new")
                    shutil.copy2(source, staged)
                    os.replace(staged, target)
            (self.xray_dir / "version.txt").write_text(release.version, encoding="utf-8")

    @staticmethod
    def _download(url: str, destination: Path, progress: Callable[[int], None] | None) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "xray-ui"})
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            destination.open("wb") as file,
        ):
            total = int(response.headers.get("Content-Length", "0"))
            downloaded = 0
            while chunk := response.read(1024 * 256):
                file.write(chunk)
                downloaded += len(chunk)
                if progress and total:
                    progress(min(100, downloaded * 100 // total))

    @staticmethod
    def _safe_extract(package: zipfile.ZipFile, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        root = destination.resolve()
        for member in package.infolist():
            target = (destination / member.filename).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError("压缩包包含不安全路径")
        package.extractall(destination)
