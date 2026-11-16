from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .models import AppConfig


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "xray-ui"


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


class JsonConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_data_dir() / "config.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        with self.path.open("r", encoding="utf-8") as file:
            return AppConfig.from_dict(json.load(file))

    def save(self, config: AppConfig) -> None:
        errors = config.validate()
        if errors:
            raise ValueError("；".join(errors))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(config.to_dict(), file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary, self.path)
