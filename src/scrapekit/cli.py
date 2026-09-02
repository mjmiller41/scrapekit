"""`sk` command line. Every command prints something an agent can act on."""

from __future__ import annotations

import argparse
import json
import sys

import yaml

from scrapekit import api
from scrapekit import config
from scrapekit.config import load_config
from scrapekit.schema import fill_rates, parse_fields_spec, validate_schema, weakest_field
from scrapekit.store import item_count, last_run, recall_oneoff, remember_oneoff
from scrapekit.targets import list_targets, load_target, save_target, targets_dir

LINE_CAP = 200
FILL_THRESHOLD = 0.5


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sk", description="Tiered scraping: probe, fetch, extract, run.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("probe", help="report which tier a URL needs")
    s.add_argument("url")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_probe)

    s = sub.add_parser("fetch", help="get a page as markdown (default), html, or json")
    s.add_argument("url")
    s.add_argument("--tier", type=int, choices=(1, 2))
    s.add_argument("--md", action="store_true", help="markdown (default)")
    s.add_argument("--html", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--full", action="store_true", help=f"do not cap output at {LINE_CAP} lines")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("extract", help="apply a schema to one URL and print rows + fill rates")
    s.add_argument("url")
    s.add_argument("--target", help="use targets/NAME.yaml")
    s.add_argument("--fields", help='inline schema: "title=h2,price=.price,url=a@href"')
    s.add_argument("--base", help="base selector for --fields (default: body, one row)")
    s.add_argument("--schema", help="YAML/JSON file with a JsonCss schema")
    s.add_argument("--tier", type=int, choices=(1, 2, 3))
    s.add_argument("--instruction", default="", help="tier 3 only: what to extract")
    s.add_argument("--dry-run", action="store_true", help="(target mode) never writes; same as default here")
    s.add_argument("--limit", type=int, default=20, help="rows to print")
    s.set_defaults(func=cmd_extract)

    s = sub.add_parser("save-target", help="write the last one-off extract as targets/NAME.yaml")
    s.add_argument("name")
    s.add_argument("--key", help="field used for dedupe")
    s.add_argument("--note", default="", help="comment line; required justification for tier 3")
    s.set_defaults(func=cmd_save_target)

    s = sub.add_parser("run", help="run a target: fetch all urls, upsert, write jsonl, log")
    s.add_argument("name")
    s.add_argument("--json", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-wait", action="store_true", help="fail instead of waiting for the run lock")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("targets", help="list targets with tier, last run, item count")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_targets)

    s = sub.add_parser("remote", help="run on the VPS and pull data back")
    rs = s.add_subparsers(dest="remote_cmd", required=True)
    r = rs.add_parser("run")
    r.add_argument("name")
    r.add_argument("--no-wait", action="store_true")
    r.set_defaults(func=cmd_remote_run)
    r = rs.add_parser("check", help="verify sk, chromium, and ollama on the VPS")
    r.set_defaults(func=cmd_remote_check)

    s = sub.add_parser("where", help="print data and targets directories")
    s.set_defaults(func=cmd_where)
    return p


# ---------------------------------------------------------------- commands

def cmd_probe(a) -> int:
    p = api.probe(a.url)
    if a.json:
        print(json.dumps(p.to_dict(), indent=2))
        return 0
    print(f"url:        {p.final_url or p.url}")
    print(f"status:     {p.status}" + (f"  ({p.error})" if p.error else ""))
    print(f"html:       {p.html_bytes} bytes, {p.text_chars} visible chars, ratio {p.text_ratio}")
    print(f"js_shell:   {p.js_shell}")
    print(f"blocked:    {p.blocked}" + (f"  markers={p.markers}" if p.markers else ""))
    print(f"robots:     {p.robots}")
    print(f"tier:       {p.recommended_tier}")
    print(f"reason:     {p.reason}")
    return 0


def cmd_fetch(a) -> int:
    page = api.fetch(a.url, tier=a.tier)
    if page.error or not page.ok:
        print(f"error: tier {page.tier} fetch of {a.url} failed: {page.error or f'status {page.status}'}", file=sys.stderr)
        return 1
    if a.json:
        body = json.dumps({"url": page.final_url, "tier": page.tier, "status": page.status, "markdown": page.markdown}, indent=2)
    elif a.html:
        body = page.html
    else:
        body = page.markdown
    print(f"# tier {page.tier} | status {page.status} | {page.final_url}", file=sys.stderr)
    _print_capped(body, a.full)
    return 0


def cmd_extract(a) -> int:
    instruction = a.instruction
    wait_for = None
    tier = a.tier
    if a.target:
        t = load_target(a.target)
        schema, instruction, wait_for = t.schema, instruction or t.llm_instruction, t.wait_for
        tier = tier or t.tier
    elif a.fields:
        schema = parse_fields_spec(a.fields, a.base)
    elif a.schema:
        with open(a.schema) as fh:
            schema = yaml.safe_load(fh)
    else:
        print("error: give --target, --fields, or --schema", file=sys.stderr)
        return 2
    validate_schema(schema)
    page = api.extract(a.url, schema, tier=tier, instruction=instruction, wait_for=wait_for)
    if page.error or not page.ok:
        print(f"error: tier {page.tier} extract failed: {page.error or f'status {page.status}'}", file=sys.stderr)
        return 1
    rows = page.rows or []
    rates = fill_rates(rows, schema)
    if not a.target:
        remember_oneoff(a.url, page.tier, schema, rates)
    print(json.dumps(rows[: a.limit], indent=2, ensure_ascii=False))
    print(f"# tier {page.tier} | {len(rows)} rows | fill: " + ", ".join(f"{k}={v:.0%}" for k, v in rates.items()), file=sys.stderr)
    weakest = weakest_field(rates)
    if not rows:
        print("# no rows: baseSelector matched nothing. Check `sk fetch --html` for the real markup, or raise the tier by one.", file=sys.stderr)
        return 3
    if weakest and weakest[1] < FILL_THRESHOLD:
        print(f"# weak field {weakest[0]!r} at {weakest[1]:.0%}: fix its selector, or raise the tier by exactly one.", file=sys.stderr)
        return 3
    return 0


def cmd_save_target(a) -> int:
    last = recall_oneoff()
    if not last:
        raise RuntimeError("no one-off extract recorded yet; run `sk extract URL --fields ...` first")
    if last["tier"] == 3 and not a.note:
        raise ValueError("tier 3 targets need --note explaining why a CSS schema was not enough")
    path = save_target(a.name, last["url"], last["tier"], last["schema"], key=a.key, note=a.note)
    print(f"wrote {path} (tier {last['tier']}, {len(last['schema']['fields'])} fields, last fill {last['fill_rates']})")
    print("edit urls/url_template and delay before `sk remote run`.")
    return 0


def cmd_run(a) -> int:
    summary = api.run(a.name, dry_run=a.dry_run, no_wait=a.no_wait)
    if a.json:
        print(json.dumps(summary.to_dict()))
    else:
        print(f"{summary.target}: tier {summary.tier}, {summary.urls} urls, {summary.rows} rows, {summary.new} new, {summary.changed} changed, {len(summary.errors)} errors")
        if summary.fill_rates:
            print("fill: " + ", ".join(f"{k}={v:.0%}" for k, v in summary.fill_rates.items()))
        if summary.output:
            print(f"output: {summary.output}")
        for e in summary.errors[:10]:
            print(f"  ! {e}")
    return 1 if summary.errors and not summary.rows else 0


def cmd_targets(a) -> int:
    names = list_targets()
    out = []
    for n in names:
        try:
            t = load_target(n)
            tier, urls, err = t.tier, len(t.all_urls()), ""
        except (ValueError, FileNotFoundError) as exc:
            tier, urls, err = "?", 0, str(exc)
        lr = last_run(n)
        out.append({"name": n, "tier": tier, "urls": urls, "items": item_count(n),
                    "last_run": lr["started"] if lr else None, "last_rows": lr["rows"] if lr else None,
                    "last_errors": len(lr["errors"]) if lr else None, "invalid": err})
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    if not out:
        print(f"no targets in {targets_dir()}")
        return 0
    print(f"{'name':24} {'tier':4} {'urls':5} {'items':6} {'last run':20} {'rows':5} err")
    for r in out:
        print(f"{r['name']:24} {str(r['tier']):4} {r['urls']:5} {r['items']:6} {str(r['last_run'] or '-'):20} {str(r['last_rows'] if r['last_rows'] is not None else '-'):5} {r['last_errors'] if r['last_errors'] is not None else '-'}" + (f"  INVALID: {r['invalid']}" if r["invalid"] else ""))
    return 0


def cmd_remote_run(a) -> int:
    from scrapekit.remote import remote_run

    summary = remote_run(a.name, no_wait=a.no_wait)
    print(json.dumps(summary, indent=2))
    if summary.get("output"):
        print(f"local copy: {config.DATA_DIR / a.name}/")
    return 0


def cmd_remote_check(a) -> int:
    from scrapekit.remote import remote_shell

    cfg = load_config()
    print(remote_shell(cfg, "$HOME/.local/bin/sk where; $HOME/.local/bin/sk targets; ls $HOME/.cache/ms-playwright 2>/dev/null | head -3; curl -s localhost:11434/api/tags | head -c 300; echo; uptime"))
    return 0


def cmd_where(a) -> int:
    cfg = load_config()
    print(f"data:     {config.DATA_DIR}")
    print(f"targets:  {targets_dir()}")
    print(f"remote:   {cfg.remote_host}:{cfg.remote_repo}")
    print(f"caps:     concurrency<={cfg.max_concurrency} browsers<={cfg.max_browsers} low_priority={cfg.low_priority}")
    print(f"tier 3:   {cfg.llm_provider}" + (f" at {cfg.llm_base_url}" if cfg.llm_provider.startswith("ollama/") else ""))
    return 0


def _print_capped(body: str, full: bool) -> None:
    lines = body.splitlines()
    if full or len(lines) <= LINE_CAP:
        print(body)
        return
    print("\n".join(lines[:LINE_CAP]))
    print(f"\n# … {len(lines) - LINE_CAP} more lines; rerun with --full", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
