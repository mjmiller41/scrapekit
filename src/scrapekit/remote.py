"""Run a target on the VPS: push targets, run there, pull data back."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys

from scrapekit.config import Config, ensure_data_dir, load_config
from scrapekit.targets import targets_dir


def _sh(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(shlex.quote(c) for c in cmd), file=sys.stderr)
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def push_targets(cfg: Config) -> None:
    src = str(targets_dir()) + "/"
    dst = f"{cfg.remote_host}:{cfg.remote_repo}/targets/"
    _sh(["rsync", "-az", "--delete", "--exclude", "_*", src, dst])


def pull_data(cfg: Config) -> None:
    src = f"{cfg.remote_host}:{cfg.remote_data}/"
    dst = str(ensure_data_dir()) + "/"
    _sh(["rsync", "-az", "--exclude", ".run.lock", "--exclude", "last_oneoff.json", src, dst])


def remote_run(name: str, cfg: Config | None = None, no_wait: bool = False) -> dict:
    cfg = cfg or load_config()
    push_targets(cfg)
    remote_cmd = f"$HOME/.local/bin/sk run {shlex.quote(name)} --json" + (" --no-wait" if no_wait else "")
    proc = _sh(["ssh", cfg.remote_host, remote_cmd], check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"remote run failed ({proc.returncode}):\n{proc.stderr.strip()}\n{proc.stdout.strip()}")
    pull_data(cfg)
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"raw": proc.stdout}


def remote_shell(cfg: Config, command: str) -> str:
    proc = _sh(["ssh", cfg.remote_host, command], check=False)
    return (proc.stdout + proc.stderr).strip()
