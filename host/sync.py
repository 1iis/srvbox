from __future__ import annotations
import argparse
import os
import platform
import pwd
import shutil
import subprocess
import sys
import time
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
def check_access_policy() -> None:
    facts = [
        ("human users",        "unmanaged by srvbox; deploy user must already exist"),
        ("deploy access",      "pre-existing SSH user with sudo"),
        ("privilege",          "satisfied: apply is running as root"),
        ("srvbox user",        "not created; srvbox is a root-run reconciler, not a daemon"),
        ("future app users",   "per-app system users named iis-<app>, created by app deployment when needed"),
    ]

    for key, value in facts: log(f"{key}: {value}")

SSHD_DROPIN = Path("/etc/ssh/sshd_config.d/90-1iis-srvbox.conf")
SSHD_DROPIN_TEXT = """\
# Managed by srvbox. Local changes may be overwritten.

PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication no
PermitEmptyPasswords no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
UsePAM yes
X11Forwarding no
"""
def write_text_if_changed(path: Path, text: str) -> bool:
    if read_text(path) == text: return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True
def chown_root(path: Path) -> None: shutil.chown(path, user="root", group="root")
def chmod(path: Path, mode: int) -> None: path.chmod(mode)
def systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["systemctl", *args], check=check)
def ssh_service_name() -> str:
    if service_is_active("ssh") != "unknown" or service_is_enabled("ssh") != "unknown": return "ssh"
    if service_is_active("sshd") != "unknown" or service_is_enabled("sshd") != "unknown": return "sshd"
    return "ssh"
def validate_sshd_config() -> None:
    if not cmd_exists("sshd"): raise SystemExit("error: sshd command not found")
    result = run_capture(["sshd", "-t"])
    if result is None or result.returncode != 0:
        err = "" if result is None else result.stderr.strip()
        raise SystemExit(f"error: sshd config validation failed: {err}")
def restore_file(path: Path, previous: str | None) -> None:
    if previous is None:
        if path.exists(): path.unlink()
    else:
        path.write_text(previous)
def reload_ssh_service() -> None:
    service = ssh_service_name()
    if not cmd_exists("systemctl"): raise SystemExit("error: systemctl command not found")
    if systemctl("reload", service, check=False).returncode == 0:
        log(f"reloaded SSH service: {service}")
        return
    systemctl("restart", service)
    log(f"restarted SSH service: {service}")
def sudo_or_login_user() -> str: return os.environ.get("SUDO_USER") or os.environ.get("USER") or "unknown"
def home_for_user(user: str) -> Path | None:
    try: return Path(pwd.getpwnam(user).pw_dir) if user != "unknown" else None
    except KeyError: return None
def authorized_keys_path(user: str) -> Path | None:
    return None if (home := home_for_user(user)) is None else home / ".ssh" / "authorized_keys"
def has_authorized_keys(user: str) -> bool:
    return False if (path := authorized_keys_path(user)) is None else bool((text := read_text(path)) and text.strip())
def require_key_auth_viable() -> None:
    user = sudo_or_login_user()
    if not has_authorized_keys(user): raise SystemExit(f"error: refusing to disable password auth; no authorized_keys found for {user}")
    log(f"key-auth viability: authorized_keys present for {user}")
def configure_ssh() -> None:
    require_key_auth_viable()
    previous = read_text(SSHD_DROPIN)
    changed = write_text_if_changed(SSHD_DROPIN, SSHD_DROPIN_TEXT)
    chown_root(SSHD_DROPIN)
    chmod(SSHD_DROPIN, 0o644)

    try:
        validate_sshd_config()
    except SystemExit:
        restore_file(SSHD_DROPIN, previous)
        validate_sshd_config()
        raise

    if changed: reload_ssh_service()
    else: log(f"SSH drop-in unchanged: {SSHD_DROPIN}")

SSH_DEFAULT_PORT = "22"
APT_RETRIES = 12
APT_RETRY_SECONDS = 10

def run_apt(cmd: list[str]) -> None:
    last: subprocess.CalledProcessError | None = None
    for attempt in range(1, APT_RETRIES + 1):
        try:
            run(cmd)
            return
        except subprocess.CalledProcessError as e:
            last = e
            log(f"apt attempt {attempt}/{APT_RETRIES} failed; retrying in {APT_RETRY_SECONDS}s")
            time.sleep(APT_RETRY_SECONDS)
    raise last or SystemExit(f"error: apt command failed: {' '.join(cmd)}")

def install_packages(names: list[str]) -> None:
    run_apt(["apt-get", "update"])
    run_apt(["apt-get", "install", "-y", *names])

def ufw(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["ufw", *args], check=check)
def known_ssh_ports() -> list[str]:
    ports = configured_ssh_ports()
    if ports == "unknown": raise SystemExit("error: refusing to enable firewall; SSH port is unknown")
    return [port.strip() for port in ports.split(",") if port.strip()] or [SSH_DEFAULT_PORT]
def configure_firewall() -> None:
    install_packages(["ufw"])
    if not cmd_exists("ufw"): raise SystemExit("error: ufw command not found after install")

    ports = known_ssh_ports()
    log(f"firewall SSH port(s): {', '.join(ports)}")

    ufw("default", "deny", "incoming")
    ufw("default", "allow", "outgoing")

    for port in ports:
        ufw("allow", f"{port}/tcp")
        log(f"firewall allowed SSH: {port}/tcp")

    if "Status: active" in ufw_status():
        log("ufw already active")
    else:
        log("enabling ufw after SSH allow rule")
        ufw("--force", "enable")

    log("ufw status:")
    print(ufw_status(verbose=True))
ENABLE_FAIL2BAN = False
FAIL2BAN_JAIL = Path("/etc/fail2ban/jail.d/90-1iis-srvbox.local")
def fail2ban_jail_text() -> str:
    enabled = "true" if ENABLE_FAIL2BAN else "false"
    return f"""\
# Managed by srvbox. Local changes may be overwritten.

[sshd]
enabled = {enabled}
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
"""
def fail2ban_active_jails() -> str:
    result = run_capture(["fail2ban-client", "status"])
    if result is None or result.returncode != 0: return "unknown"
    for line in result.stdout.splitlines():
        if "Jail list:" in line: return line.split(":", 1)[1].strip() or "none"
    return "none"
def enable_service(name: str) -> None: systemctl("enable", "--now", name)
def disable_service(name: str) -> None: systemctl("disable", "--now", name, check=False)
def configure_fail2ban() -> None:
    install_packages(["fail2ban"])
    if not cmd_exists("fail2ban-client"): raise SystemExit("error: fail2ban-client not found after install")

    changed = write_text_if_changed(FAIL2BAN_JAIL, fail2ban_jail_text())
    chown_root(FAIL2BAN_JAIL)
    chmod(FAIL2BAN_JAIL, 0o644)

    if ENABLE_FAIL2BAN:
        if changed and service_is_active("fail2ban") == "yes": systemctl("restart", "fail2ban")
        enable_service("fail2ban")
        log(f"fail2ban active jails: {fail2ban_active_jails()}")
    else:
        disable_service("fail2ban")
        log("fail2ban configured but intentionally inactive")

APT_AUTO_UPGRADES = Path("/etc/apt/apt.conf.d/20auto-upgrades")
APT_AUTO_UPGRADES_TEXT = """\
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
"""
def configure_unattended_upgrades() -> None:
    install_packages(["unattended-upgrades"])
    if not cmd_exists("unattended-upgrade"): raise SystemExit("error: unattended-upgrade not found after install")

    changed = write_text_if_changed(APT_AUTO_UPGRADES, APT_AUTO_UPGRADES_TEXT)
    chown_root(APT_AUTO_UPGRADES)
    chmod(APT_AUTO_UPGRADES, 0o644)

    enable_service("apt-daily.timer")
    enable_service("apt-daily-upgrade.timer")
    log(f"unattended upgrades periodic config: {'updated' if changed else 'unchanged'}")
    log("unattended upgrades automatic reboot: unmanaged/disabled by default")
ENABLE_CADDY = True
CADDYFILE = Path("/etc/caddy/Caddyfile")
CADDY_SITES = Path("/etc/caddy/sites.d")
CADDY_KEYRING = Path("/usr/share/keyrings/caddy-stable-archive-keyring.gpg")
CADDY_APT_SOURCE = Path("/etc/apt/sources.list.d/caddy-stable.list")
CADDY_GPG_URL = "https://dl.cloudsmith.io/public/caddy/stable/gpg.key"
CADDY_DEB_URL = "https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt"
def install_url(url: str, path: Path, *, dearmor: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if dearmor:
        run(["sh", "-c", f"curl -1sLf {url!r} | gpg --dearmor -o {str(path)!r}"])
    else:
        run(["sh", "-c", f"curl -1sLf {url!r} > {str(path)!r}"])
    chmod(path, 0o644)
def ensure_caddy_repo() -> None:
    install_packages(["debian-keyring", "debian-archive-keyring", "apt-transport-https", "curl", "gpg"])
    if not CADDY_KEYRING.exists(): install_url(CADDY_GPG_URL, CADDY_KEYRING, dearmor=True)
    if not CADDY_APT_SOURCE.exists(): install_url(CADDY_DEB_URL, CADDY_APT_SOURCE)
    run_apt(["apt-get", "update"])
def caddyfile_text() -> str:
    return """\
# Managed by srvbox. Local changes may be overwritten.

import /etc/caddy/sites.d/*.caddy
"""
def caddy(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["caddy", *args], check=check)
def validate_caddy_config() -> None:
    if not cmd_exists("caddy"): raise SystemExit("error: caddy command not found")
    result = run_capture(["caddy", "validate", "--config", str(CADDYFILE)])
    if result is None or result.returncode != 0:
        err = "" if result is None else (result.stderr.strip() or result.stdout.strip())
        raise SystemExit(f"error: caddy config validation failed: {err}")
def reload_or_start_caddy(changed: bool) -> None:
    if service_is_active("caddy") == "yes" and changed:
        systemctl("reload", "caddy")
        log("reloaded Caddy")
    else:
        enable_service("caddy")
        log("enabled/started Caddy")
def configure_caddy() -> None:
    if not ENABLE_CADDY:
        ufw("delete", "allow", "80/tcp", check=False)
        ufw("delete", "allow", "443/tcp", check=False)
        if cmd_exists("systemctl") and service_is_active("caddy") == "yes": disable_service("caddy")
        log("Caddy ingress disabled by policy")
        return

    ensure_caddy_repo()
    install_packages(["caddy"])
    if not cmd_exists("caddy"): raise SystemExit("error: caddy command not found after install")

    CADDY_SITES.mkdir(parents=True, exist_ok=True)
    chown_root(CADDY_SITES)
    chmod(CADDY_SITES, 0o755)

    previous = read_text(CADDYFILE)
    changed = write_text_if_changed(CADDYFILE, caddyfile_text())
    chown_root(CADDYFILE)
    chmod(CADDYFILE, 0o644)

    try:
        validate_caddy_config()
    except SystemExit:
        restore_file(CADDYFILE, previous)
        validate_caddy_config()
        raise

    ufw("allow", "80/tcp")
    ufw("allow", "443/tcp")
    reload_or_start_caddy(changed)
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
def ufw_status(verbose: bool = False) -> str:
    args = ["ufw", "status", "verbose"] if verbose else ["ufw", "status"]
    if not cmd_exists("ufw") or (r := run_capture(args)) is None or r.returncode != 0: return "unknown"
    return r.stdout.strip() or "unknown"
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

        ("fail2ban policy enabled",            yesno(ENABLE_FAIL2BAN)),
        ("fail2ban-client",                   cmd_path("fail2ban-client")),
        ("fail2ban active",                   service_is_active("fail2ban")),
        ("fail2ban enabled",                  service_is_enabled("fail2ban")),
        ("fail2ban managed jail",             yesno(file_exists(FAIL2BAN_JAIL))),
        ("fail2ban active jails",             fail2ban_active_jails() if service_is_active("fail2ban") == "yes" else "inactive"),

        ("unattended-upgrade",                cmd_path("unattended-upgrade")),
        ("unattended-upgrades",               unattended_upgrades_status()),

        ("caddy policy enabled",              yesno(ENABLE_CADDY)),
        ("caddy",                             cmd_path("caddy")),
        ("caddy active",                      service_is_active("caddy")),
        ("caddy enabled",                     service_is_enabled("caddy")),
        ("caddyfile",                         yesno(file_exists(CADDYFILE))),
        ("caddy sites.d",                     yesno(dir_exists(CADDY_SITES))),
    ]
    for key, value in facts: log(f"{key}: {value}")
    log("status check complete")
STEPS = [
    Step("base directories", ensure_base_dirs),
    Step("access policy", check_access_policy),
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
