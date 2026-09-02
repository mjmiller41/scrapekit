"""Paths and machine-level caps.

Data lives outside the repo so other projects and the VPS can read it without a checkout.
Caps live in a per-machine config file so a shared box can be protected without touching
target definitions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

DATA_DIR = Path(os.environ.get("SCRAPEKIT_DATA", "~/.local/share/scrapekit")).expanduser()
CONFIG_FILE = Path(os.environ.get("SCRAPEKIT_CONFIG", "~/.config/scrapekit/config.yaml")).expanduser()
REPO_DIR = Path(__file__).resolve().parents[2]
TARGETS_DIR = Path(os.environ.get("SCRAPEKIT_TARGETS", REPO_DIR / "targets")).expanduser()


@dataclass
class Config:
    max_concurrency: int = 4
    max_browsers: int = 1
    tier3_serial: bool = True
    low_priority: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    remote_host: str = "hostinger-vps"
    remote_repo: str = "~/Code/scrapekit"
    remote_data: str = "~/.local/share/scrapekit"
    timeout_seconds: float = 30.0
    extra: dict = field(default_factory=dict)


def load_config() -> Config:
    cfg = Config()
    if CONFIG_FILE.exists():
        raw = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        for key, value in raw.items():
            if hasattr(cfg, key) and key != "extra":
                setattr(cfg, key, value)
            else:
                cfg.extra[key] = value
    return cfg


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
