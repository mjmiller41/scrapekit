"""Target definitions: one YAML per repeated scrape."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from scrapekit import config
from scrapekit.schema import validate_schema

VALID_TIERS = (1, 2, 3, 4)


@dataclass
class Target:
    name: str
    tier: int
    schema: dict
    urls: list[str] = field(default_factory=list)
    url_template: str | None = None
    page_range: list[int] | None = None
    key: str | None = None
    delay_seconds: float = 1.0
    concurrency: int = 2
    wait_for: str | None = None
    llm_instruction: str = ""
    steps: list[str] = field(default_factory=list)   # tier 4: natural-language actions before extracting
    tier4_reason: str = ""                            # tier 4: what defeated tiers 1-3
    path: Path | None = None

    def all_urls(self) -> list[str]:
        urls = list(self.urls)
        if self.url_template and self.page_range:
            start, end = self.page_range
            urls += [self.url_template.format(page=p) for p in range(start, end + 1)]
        return urls

    def validate(self) -> None:
        if self.tier not in VALID_TIERS:
            raise ValueError(f"{self.name}: tier must be one of {VALID_TIERS}, got {self.tier!r}")
        validate_schema(self.schema)
        if not self.all_urls():
            raise ValueError(f"{self.name}: no urls (set 'urls' or 'url_template' + 'page_range')")
        names = {f["name"] for f in self.schema["fields"]}
        if self.key and self.key not in names:
            raise ValueError(f"{self.name}: key {self.key!r} is not a schema field")
        if self.tier == 3 and not self.llm_instruction:
            raise ValueError(f"{self.name}: tier 3 requires 'llm_instruction' explaining what to extract and why CSS was not enough")
        if self.tier == 4 and not self.tier4_reason:
            raise ValueError(f"{self.name}: tier 4 requires 'tier4_reason' naming what defeated tiers 1-3 (challenge page, login, ...)")
        if self.steps and self.tier != 4:
            raise ValueError(f"{self.name}: 'steps' only apply to tier 4")


def targets_dir() -> Path:
    return config.TARGETS_DIR


def target_path(name: str) -> Path:
    return targets_dir() / f"{name}.yaml"


def load_target(name: str) -> Target:
    path = target_path(name)
    if not path.exists():
        raise FileNotFoundError(f"no target {name!r} at {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    known = {f.name for f in Target.__dataclass_fields__.values()} - {"path"}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{name}: unknown keys {sorted(unknown)}")
    raw.setdefault("name", name)
    t = Target(**raw, path=path)
    t.validate()
    return t


def list_targets() -> list[str]:
    d = targets_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.yaml") if not p.stem.startswith("_"))


def save_target(name: str, url: str, tier: int, schema: dict, key: str | None = None, note: str = "") -> Path:
    d = targets_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = target_path(name)
    if path.exists():
        raise FileExistsError(f"target {name!r} already exists at {path}")
    body = {
        "name": name,
        "tier": tier,
        "urls": [url],
        "delay_seconds": 2,
        "concurrency": 2,
        "schema": {"name": name, "baseSelector": schema.get("baseSelector", "body"), "fields": schema.get("fields", [])},
    }
    if key:
        body["key"] = key
    if tier == 3:
        body["llm_instruction"] = note or "TODO: say what to extract and why a CSS schema could not"
    if tier == 4:
        body["tier4_reason"] = note or "TODO: name what defeated tiers 1-3"
        body["steps"] = []
    header = f"# {note}\n" if note and tier not in (3, 4) else ""
    path.write_text(header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True))
    return path
