import json
import subprocess

from scrapekit import tiers
from scrapekit.config import Config
from scrapekit.tiers import Page, build_claude_prompt, parse_json_array, tier3_claude

SCHEMA = {"fields": [{"name": "text", "description": "the quote"}, {"name": "author"}]}


def test_parse_json_array_variants():
    assert parse_json_array('[{"a": 1}]') == [{"a": 1}]
    assert parse_json_array('Sure:\n```json\n[{"a": 1}]\n```\n') == [{"a": 1}]
    assert parse_json_array('Here you go [{"a": 1}, {"a": 2}] done') == [{"a": 1}, {"a": 2}]
    assert parse_json_array("no json here") == []
    assert parse_json_array('{"a": 1}') == []


def test_prompt_lists_fields_and_wraps_page():
    p = build_claude_prompt("# Hi", SCHEMA, "Get quotes.")
    assert p.startswith("Get quotes.")
    assert "- text: the quote" in p and "- author" in p
    assert "<page>\n# Hi\n</page>" in p


def test_tier3_claude_end_to_end_with_fake_cli(monkeypatch):
    monkeypatch.setattr(tiers, "tier1_fetch", lambda url, schema=None, cfg=None: Page(url=url, tier=1, status=200, final_url=url, html="<p>" + "x " * 200 + "</p>"))
    monkeypatch.setattr(tiers, "html_to_markdown", lambda html, base_url="": "quote one by A\n" * 30)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = json.dumps({"result": '[{"text": "quote one", "author": "A", "extra": 1}]'})
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(tiers.subprocess, "run", fake_run)
    page = tier3_claude("https://x/", SCHEMA, instruction="Get quotes.", cfg=Config(llm_provider="claude/haiku"))
    assert page.rows == [{"text": "quote one", "author": "A"}]
    assert calls[0][:6] == ["claude", "-p", "--model", "haiku", "--output-format", "json"]
    assert "Get quotes." in calls[0][-1]


def test_tier3_claude_reports_cli_failure(monkeypatch):
    monkeypatch.setattr(tiers, "tier1_fetch", lambda url, schema=None, cfg=None: Page(url=url, tier=1, status=200, final_url=url, html="<p>hi</p>"))
    monkeypatch.setattr(tiers, "html_to_markdown", lambda html, base_url="": "long enough " * 30)
    monkeypatch.setattr(tiers.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in"))
    page = tier3_claude("https://x/", SCHEMA, cfg=Config(llm_provider="claude/haiku"))
    assert page.rows is None and "not logged in" in page.error
