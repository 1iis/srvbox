from __future__ import annotations
import argparse
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
ROOT = Path(__file__).resolve().parents[1]
def log(msg: str) -> None:
    print(f"==> {msg}")
def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True)
def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("error: sync.py must run as root")
def require_ubuntuish() -> None:
    if not Path("/etc/os-release").exists():
        raise SystemExit("error: /etc/os-release not found")

    data = Path("/etc/os-release").read_text()
    if "Ubuntu" not in data and "Debian" not in data:
        raise SystemExit("error: only Ubuntu/Debian-like hosts are supported for now")
@dataclass(frozen=True)
class Step:
    name: str
    fn: Callable[[], None]
def ensure_base_dirs() -> None:
    for path in [
        Path("/opt/1iis"),
        Path("/etc/1iis"),
        Path("/var/lib/1iis"),
        Path("/var/log/1iis"),
    ]:
        log(f"TODO/ensure directory: {path}")
def ensure_admin_user() -> None:
    log("TODO: create non-root admin/service user conventions")
def configure_ssh() -> None:
    log("TODO: harden sshd_config: no root login, key auth only")
def configure_firewall() -> None:
    log("TODO: configure firewall baseline: deny incoming, allow SSH")
def configure_fail2ban() -> None:
    log("TODO: install/configure fail2ban")
def configure_unattended_upgrades() -> None:
    log("TODO: install/configure unattended-upgrades")
def configure_caddy() -> None:
    log("TODO: optionally install/configure Caddy")
def check_status() -> None:
    log(f"repo root: {ROOT}")
    log(f"python: {sys.version.split()[0]}")
    log(f"platform: {platform.platform()}")
    log(f"git: {shutil.which('git') or 'missing'}")
    log("status check complete")
STEPS = [
    Step("base directories", ensure_base_dirs),
    Step("admin/service users", ensure_admin_user),
    Step("ssh hardening", configure_ssh),
    Step("firewall", configure_firewall),
    Step("fail2ban", configure_fail2ban),
    Step("unattended upgrades", configure_unattended_upgrades),
    Step("caddy", configure_caddy),
]
def apply() -> None:
    require_root()
    require_ubuntuish()

    for step in STEPS:
        log(f"Step: {step.name}")
        step.fn()
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="srvbox host reconciler")
    parser.add_argument(
        "command",
        choices=["status", "apply"],
        help="status checks the host; apply reconciles desired state",
    )
    return parser.parse_args()
def main() -> None:
    args = parse_args()

    if args.command == "status":
        check_status()
    elif args.command == "apply":
        apply()
    else:
        raise SystemExit(f"unknown command: {args.command}")
if __name__ == "__main__":
    main()
