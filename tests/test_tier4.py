import json
import subprocess

import pytest

from scrapekit import tier4
from scrapekit.tier4 import build_llm_prompt, flatten_content, json_from_text, make_claude_generate


def test_flatten_content_handles_str_block_and_list():
    assert flatten_content("hi") == "hi"
    assert flatten_content({"type": "text", "text": "one"}) == "one"
    assert flatten_content([{"type": "text", "text": "a"}, {"type": "image", "data": "..."}, {"type": "text", "text": "b"}]) == "a\n[image omitted]\nb"


def test_build_llm_prompt_structured_and_text():
    params = {
        "system_prompt": "SYS",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "extract"}]}],
        "response_format": {"type": "json_schema", "name": "x", "schema": {"type": "object"}},
    }
    prompt, structured = build_llm_prompt(params)
    assert structured and prompt.startswith("<system>\nSYS\n</system>") and '{"type": "object"}' in prompt
    prompt, structured = build_llm_prompt({"messages": [{"role": "user", "content": "hi"}]})
    assert not structured and prompt == "[user]\nhi"


def test_json_from_text():
    assert json_from_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert json_from_text('Sure: {"a": [1, 2]} ok') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        json_from_text("nothing")


def test_claude_generate_callback_structured(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"result": '{"items": [{"t": "x"}]}', "usage": {"input_tokens": 5, "output_tokens": 2}}), stderr="")

    monkeypatch.setattr(tier4.subprocess, "run", fake_run)
    gen = make_claude_generate("haiku", 30)
    import asyncio
    out = asyncio.run(gen({"messages": [{"role": "user", "content": "go"}], "response_format": {"type": "json_schema", "schema": {}}}))
    assert out["output_format"] == "json_schema" and out["structured_content"] == {"items": [{"t": "x"}]}
    assert out["usage"]["total_tokens"] == 7
    assert seen["cmd"][:4] == ["claude", "-p", "--model", "haiku"]


def test_tier4_reports_missing_steel(monkeypatch):
    from scrapekit.config import Config
    monkeypatch.setattr(tier4, "steel_ok", lambda url: False)
    page = tier4.tier4_stagehand("https://x/", {"fields": [{"name": "t"}]}, cfg=Config(steel_url="http://localhost:1"))
    assert "Steel is not answering" in page.error
