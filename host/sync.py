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
        path.mkdir(parents=True, exist_ok=True)
        shutil.chown(path, user="root", group="root")
        path.chmod(0o755)
        log(f"ensured directory: {path}")
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
def yesno(value: bool) -> str: return "yes" if value else "no"
def cmd_path(name: str) -> str: return shutil.which(name) or "missing"
def cmd_exists(name: str) -> bool: return cmd_path(name) != "missing"
def run_capture(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str] | None:
    try: return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError: return None
def read_text(path: Path) -> str | None:
    try: return path.read_text()
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError): return None
def file_exists(path: Path) -> bool: return path.is_file()
def dir_exists(path: Path) -> bool: return path.is_dir()
def os_release_summary() -> str:
    data = read_text(Path("/etc/os-release"))
    if data is None: return "unknown"
    fields = dict(line.split("=", 1) for line in data.splitlines() if "=" in line and not line.startswith("#"))
    fields = {k: v.strip().strip('"') for k,v in fields.items()}
    return fields.get("PRETTY_NAME") or " ".join(x for x in [fields.get("NAME"), fields.get("VERSION")] if x) or "unknown"
def service_is_active(name: str) -> str:
    return "unknown" if not cmd_exists("systemctl") or (r := run_capture(["systemctl", "is-active", "--quiet", name])) is None else yesno(r.returncode == 0)
def service_is_enabled(name: str) -> str:
    return "unknown" if not cmd_exists("systemctl") or (r := run_capture(["systemctl", "is-enabled", "--quiet", name])) is None else yesno(r.returncode == 0)
def sshd_config_path() -> Path: return Path("/etc/ssh/sshd_config")
def sshd_config_d_path() -> Path: return Path("/etc/ssh/sshd_config.d")
def active_config_lines(text: str) -> list[str]:
    return [line for raw in text.splitlines() if (line := raw.strip()) and not line.startswith("#")]
def sshd_config_includes_dropins() -> str:
    text = read_text(sshd_config_path())
    if text is None: return "unknown"
    includes = [" ".join(parts[1:]) for line in active_config_lines(text) if len(parts := line.split()) >= 2 and parts[0].lower() == "include"]
    return yesno(any("sshd_config.d" in include and "*.conf" in include for include in includes))
def configured_ssh_ports() -> str:
    paths = [sshd_config_path()] + (sorted(sshd_config_d_path().glob("*.conf")) if sshd_config_d_path().is_dir() else [])
    texts = [text for path in paths if (text := read_text(path)) is not None]
    ports = [parts[1] for text in texts for line in active_config_lines(text) if len(parts := line.split()) >= 2 and parts[0].lower() == "port"]
    if ports: return ", ".join(dict.fromkeys(ports))
    if texts: return "22"
    return "unknown"
def ufw_status() -> str:
    if not cmd_exists("ufw") or (r := run_capture(["ufw", "status"])) is None or r.returncode != 0: return "unknown"
    return r.stdout.splitlines()[0].strip() if r.stdout.splitlines() else "unknown"
def unattended_upgrades_status() -> str:
    binary   = cmd_exists("unattended-upgrade")
    config   = file_exists(Path("/etc/apt/apt.conf.d/50unattended-upgrades"))
    periodic = file_exists(Path("/etc/apt/apt.conf.d/20auto-upgrades"))
    return f"binary={yesno(binary)}, config={yesno(config)}, periodic={yesno(periodic)}, timer_active={service_is_active('apt-daily-upgrade.timer')}"
def check_status() -> None:
    facts = [
        ("repo root",                         ROOT),
        ("python",                            sys.version.split()[0]),
        ("platform",                          platform.platform()),
        ("euid",                              os.geteuid()),
        ("root",                              yesno(os.geteuid() == 0)),
        ("os",                                os_release_summary()),

        ("apt-get",                           cmd_path("apt-get")),
        ("systemctl",                         cmd_path("systemctl")),

        ("ssh",                               cmd_path("ssh")),
        ("sshd",                              cmd_path("sshd")),
        ("ssh service active",                service_is_active("ssh")),
        ("ssh service enabled",               service_is_enabled("ssh")),
        ("sshd_config",                       yesno(file_exists(sshd_config_path()))),
        ("sshd_config.d",                     yesno(dir_exists(sshd_config_d_path()))),
        ("sshd_config includes drop-ins",     sshd_config_includes_dropins()),
        ("ssh ports",                         configured_ssh_ports()),

        ("ufw",                               cmd_path("ufw")),
        ("ufw status",                        ufw_status()),

        ("fail2ban-client",                   cmd_path("fail2ban-client")),
        ("fail2ban active",                   service_is_active("fail2ban")),
        ("fail2ban enabled",                  service_is_enabled("fail2ban")),

        ("unattended-upgrade",                cmd_path("unattended-upgrade")),
        ("unattended-upgrades",               unattended_upgrades_status()),
    ]

    for key, value in facts: log(f"{key}: {value}")
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
