import json

import pytest

from scrapekit.store import RunSummary, item_count, last_run, log_run, run_lock, upsert, write_jsonl


def test_upsert_counts_new_then_changed_then_unchanged():
    rows = [{"url": "a", "price": "1"}, {"url": "b", "price": "2"}]
    assert upsert("t", rows, "url") == (2, 0)
    rows[0]["price"] = "9"
    assert upsert("t", rows, "url") == (0, 1)
    assert upsert("t", rows, "url") == (0, 0)
    assert item_count("t") == 2


def test_upsert_without_key_uses_row_hash():
    rows = [{"a": 1}, {"a": 2}]
    assert upsert("t", rows, None) == (2, 0)
    assert upsert("t", rows, None) == (0, 0)


def test_upsert_skips_rows_missing_key():
    assert upsert("t", [{"url": None, "x": 1}, {"url": "ok"}], "url") == (1, 0)


def test_jsonl_and_run_log(tmp_path):
    path = write_jsonl("t", [{"a": "é"}])
    assert path.suffix == ".jsonl"
    assert json.loads(path.read_text().strip()) == {"a": "é"}
    s = RunSummary(target="t", tier=1, started="2026-01-01T00:00:00+00:00", finished="x", urls=1, rows=1, new=1, output=str(path))
    log_run(s)
    lr = last_run("t")
    assert lr["rows"] == 1 and lr["tier"] == 1 and lr["errors"] == []


def test_run_lock_no_wait_raises_when_held():
    with run_lock():
        with pytest.raises(RuntimeError):
            with run_lock(wait=False):
                pass
