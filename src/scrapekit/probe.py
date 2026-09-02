"""Decide the minimum tier a URL needs. Recommends; never escalates on its own."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib import robotparser
from urllib.parse import urlsplit, urlunsplit

import httpx
from selectolax.parser import HTMLParser

from scrapekit.config import USER_AGENT

CHALLENGE_MARKERS = [
    "cf-chl", "challenge-platform", "just a moment", "cf_chl_opt", "__cf_chl",
    "captcha", "perimeterx", "_pxhd", "datadome", "access denied", "are you a robot",
    "please verify you are a human", "attention required",
]
JS_ROOT_IDS = {"app", "root", "__next", "__nuxt", "___gatsby", "svelte", "q-app"}
JS_NOSCRIPT = re.compile(r"enable\s+javascript|javascript\s+is\s+required|requires\s+javascript", re.I)


@dataclass
class Probe:
    url: str
    final_url: str = ""
    status: int = 0
    html_bytes: int = 0
    text_chars: int = 0
    text_ratio: float = 0.0
    js_shell: bool = False
    blocked: bool = False
    markers: list[str] = field(default_factory=list)
    robots: str = "unknown"
    recommended_tier: int | str = 1
    reason: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def probe(url: str, timeout: float = 20.0) -> Probe:
    p = Probe(url=url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            resp = client.get(url)
            p.robots = _robots_verdict(client, url)
    except httpx.HTTPError as exc:
        p.error = f"{type(exc).__name__}: {exc}"
        p.recommended_tier = 2
        p.reason = "plain HTTP request failed; a browser fetch may still work"
        return p
    p.final_url = str(resp.url)
    p.status = resp.status_code
    html = resp.text
    p.html_bytes = len(html)
    analyse_html(p, html)
    return p


def analyse_html(p: Probe, html: str) -> Probe:
    """Pure function over HTML so tests can run on fixtures. Mutates and returns `p`."""
    lowered = html.lower()
    p.markers = [m for m in CHALLENGE_MARKERS if m in lowered]
    tree = HTMLParser(html)
    noscript = " ".join(n.text() for n in tree.css("noscript"))
    tree.strip_tags(["script", "style", "noscript", "template", "svg"])
    body = tree.body
    body_text = body.text(separator=" ", strip=True) if body else ""
    p.text_chars = len(body_text)
    p.html_bytes = p.html_bytes or len(html)
    p.text_ratio = round(p.text_chars / p.html_bytes, 4) if p.html_bytes else 0.0

    empty_root = False
    if body is not None:
        for node in body.css("div, main, section"):
            node_id = (node.attributes.get("id") or "").lower()
            if node_id in JS_ROOT_IDS and len(node.text(strip=True)) < 50:
                empty_root = True
                break
    p.js_shell = bool(
        (p.text_chars < 300 and p.html_bytes > 2000)
        or empty_root
        or JS_NOSCRIPT.search(noscript)
    )

    challenge_status = p.status in (403, 429, 503)
    p.blocked = bool(p.markers and (challenge_status or p.text_chars < 300)) or (challenge_status and p.text_chars < 200)

    if p.blocked:
        p.recommended_tier = "blocked"
        p.reason = f"status {p.status} with challenge markers {p.markers or '[]'}; tiers 1-3 will not pass. Write the need into docs/tier4.md."
    elif p.js_shell:
        p.recommended_tier = 2
        p.reason = f"JS shell: {p.text_chars} visible chars in {p.html_bytes} bytes" + (", empty app root" if empty_root else "")
    elif p.status >= 400:
        p.recommended_tier = 2
        p.reason = f"status {p.status} without challenge markers; try a browser fetch before giving up"
    else:
        p.recommended_tier = 1
        p.reason = f"server-rendered: {p.text_chars} visible chars, ratio {p.text_ratio}"
    return p


def _robots_verdict(client: httpx.Client, url: str) -> str:
    parts = urlsplit(url)
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        resp = client.get(robots_url)
    except httpx.HTTPError:
        return "unknown"
    if resp.status_code != 200:
        return "allowed" if resp.status_code == 404 else "unknown"
    rp = robotparser.RobotFileParser()
    rp.parse(resp.text.splitlines())
    return "allowed" if rp.can_fetch("*", url) else "disallowed"
