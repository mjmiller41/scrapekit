import pytest
import yaml

from scrapekit.targets import list_targets, load_target, save_target, targets_dir

SCHEMA = {"baseSelector": "li", "fields": [{"name": "t", "selector": "a", "type": "text"}]}


def test_save_then_load_and_list():
    path = save_target("shop", "https://x/1", 1, SCHEMA, key="t", note="first")
    assert path.read_text().startswith("# first\n")
    t = load_target("shop")
    assert t.tier == 1 and t.key == "t" and t.all_urls() == ["https://x/1"]
    assert list_targets() == ["shop"]
    with pytest.raises(FileExistsError):
        save_target("shop", "https://x/1", 1, SCHEMA)


def test_url_template_expands():
    (targets_dir() / "p.yaml").write_text(yaml.safe_dump({
        "tier": 1, "schema": SCHEMA, "url_template": "https://x/?page={page}", "page_range": [2, 4]}))
    assert load_target("p").all_urls() == ["https://x/?page=2", "https://x/?page=3", "https://x/?page=4"]


@pytest.mark.parametrize("bad, msg", [
    ({"tier": 5, "schema": SCHEMA, "urls": ["u"]}, "tier"),
    ({"tier": 4, "schema": SCHEMA, "urls": ["u"]}, "tier4_reason"),
    ({"tier": 1, "schema": SCHEMA, "urls": ["u"], "steps": ["x"]}, "steps"),
    ({"tier": 1, "schema": SCHEMA}, "no urls"),
    ({"tier": 1, "schema": SCHEMA, "urls": ["u"], "key": "zzz"}, "not a schema field"),
    ({"tier": 3, "schema": SCHEMA, "urls": ["u"]}, "llm_instruction"),
    ({"tier": 1, "schema": SCHEMA, "urls": ["u"], "bogus": 1}, "unknown keys"),
])
def test_validation_errors(bad, msg):
    (targets_dir() / "bad.yaml").write_text(yaml.safe_dump(bad))
    with pytest.raises(ValueError, match=msg):
        load_target("bad")


def test_underscore_targets_are_hidden():
    (targets_dir() / "_example.yaml").write_text("tier: 1\n")
    assert list_targets() == []
