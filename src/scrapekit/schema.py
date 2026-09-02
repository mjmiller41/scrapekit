"""Schema handling shared by every tier.

The schema format is Crawl4AI's JsonCss format so the same target definition drives tier 1
(interpreted here with selectolax) and tier 2 (handed to Crawl4AI unchanged).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

URL_ATTRIBUTES = {"href", "src", "action", "data-src", "data-href"}


def apply_schema(html: str, schema: dict, base_url: str | None = None) -> list[dict]:
    """Interpret a JsonCss schema against raw HTML without a browser."""
    tree = HTMLParser(html)
    base_selector = schema.get("baseSelector") or "body"
    fields = schema.get("fields", [])
    rows: list[dict] = []
    for node in tree.css(base_selector):
        row = {f["name"]: _extract_field(node, f) for f in fields}
        rows.append(row)
    if base_url:
        rows = resolve_urls(rows, base_url, schema)
    return rows


def _extract_field(node: Node, field: dict):
    selector = field.get("selector")
    target = node.css_first(selector) if selector else node
    if target is None:
        return field.get("default")
    kind = field.get("type", "text")
    if kind == "text":
        value = target.text(strip=True)
    elif kind == "attribute":
        value = target.attributes.get(field.get("attribute", ""))
    elif kind == "html":
        value = target.html
    elif kind == "regex":
        match = re.search(field.get("pattern", ""), target.text(strip=True))
        value = match.group(0) if match else None
    else:
        raise ValueError(f"unknown field type {kind!r} for field {field.get('name')!r}")
    if value in ("", None):
        return field.get("default")
    return value


def resolve_urls(rows: list[dict], base_url: str, schema: dict) -> list[dict]:
    url_fields = [
        f["name"]
        for f in schema.get("fields", [])
        if f.get("type") == "attribute" and f.get("attribute") in URL_ATTRIBUTES
    ]
    if not url_fields:
        return rows
    for row in rows:
        for name in url_fields:
            if isinstance(row.get(name), str):
                row[name] = urljoin(base_url, row[name])
    return rows


def fill_rates(rows: list[dict], schema: dict) -> dict[str, float]:
    """Fraction of rows where each field is non-empty. The escalation signal."""
    names = [f["name"] for f in schema.get("fields", [])]
    if not rows:
        return {n: 0.0 for n in names}
    return {
        n: round(sum(1 for r in rows if r.get(n) not in ("", None)) / len(rows), 3)
        for n in names
    }


def weakest_field(rates: dict[str, float]) -> tuple[str, float] | None:
    if not rates:
        return None
    name = min(rates, key=rates.get)
    return name, rates[name]


def parse_fields_spec(spec: str, base_selector: str | None = None) -> dict:
    """Turn `title=h2,price=.price,url=a@href` into a JsonCss schema.

    Two forms. A spec with no "=" at all is a plain list of field names ("text,author"),
    which is what tiers 3 and 4 want (they extract by name, not by CSS). Otherwise every
    field is `name=selector` (selector may be empty), split on commas only when the comma is
    followed by `name=`, so selectors that contain commas still work.
    """
    fields = []
    parts = spec.split(",") if "=" not in spec else re.split(r",(?=\s*[\w-]+=)", spec)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        name, _, selector = part.partition("=")
        name, selector = name.strip(), selector.strip()
        if not name or not re.fullmatch(r"[\w-]+", name):
            raise ValueError(f"bad field spec {part!r}; expected name, name=selector, or name=selector@attr")
        if not selector:
            fields.append({"name": name, "type": "text"})
        elif "@" in selector:
            selector, attribute = selector.rsplit("@", 1)
            fields.append({"name": name, "selector": selector.strip() or None, "type": "attribute", "attribute": attribute})
        else:
            fields.append({"name": name, "selector": selector, "type": "text"})
    for f in fields:
        if "selector" in f and f["selector"] is None:
            del f["selector"]
    return {"name": "oneoff", "baseSelector": base_selector or "body", "fields": fields}


def validate_schema(schema: dict) -> None:
    if not isinstance(schema, dict):
        raise ValueError("schema must be a mapping")
    if not schema.get("fields"):
        raise ValueError("schema needs at least one field")
    for f in schema["fields"]:
        if "name" not in f:
            raise ValueError(f"field without a name: {f}")
        if f.get("type", "text") == "attribute" and not f.get("attribute"):
            raise ValueError(f"attribute field {f['name']!r} needs an 'attribute'")
        if f.get("type") == "regex" and not f.get("pattern"):
            raise ValueError(f"regex field {f['name']!r} needs a 'pattern'")
