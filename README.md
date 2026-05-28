# srvbox

> A small production server baseline, in Python.

`srvbox` turns a fresh Ubuntu/Debian-like host into a boring, hardened server substrate.

## Quick start

From a local repo, with `user@host` a valid `ssh` remote.
```sh
./scripts/deploy.sh -d user@host
```

This builds a local artifact, uploads it over SSH, installs a root-owned release under `/opt/1iis/srvbox/releases/`, updates a symlink to `/opt/1iis/srvbox/current`, then runs the host reconciler.

## Desired host state

- `root`-owned timestamped releases
- base directories:
    - `/opt/1iis`
    - `/etc/1iis`
    - `/var/lib/1iis`
    - `/var/log/1iis`
- SSH hardening via `/etc/ssh/sshd_config.d/`
- `ufw` firewall baseline
- unattended security upgrades
- fail2ban installed/configured, policy-controlled
- optional Caddy ingress with `/etc/caddy/sites.d/*.caddy` fragments

## Repo map

- [`scripts/`](scripts/) — `deploy`, `setup`, and `check` scripts
- [`scripts/README.md`](scripts/README.md) — deployment path and operational notes
- [`host/sync.ipynb`](host/sync.ipynb) — stdlib-only host reconciler (literate source)
- [`host/sync.py`](host/sync.py) — reconciler [export]

## Commands

```sh
./scripts/check.sh                  # local check
python3 host/sync.py status         # srvbox status
sudo python3 host/sync.py apply     # reconcile host with desired state
```

## Deployment model

Production hosts do not need `git` or repository credentials.

Local repo on workstation  
⤷ `tar` artifact  
⤷ `scp` + `ssh` + `sudo` to server  
⤷ `/opt/1iis/srvbox/releases/<timestamp>/`  
⤷ `/opt/1iis/srvbox/current` symlink  
⤷ `host/sync.py apply`  

## Ingress

Caddy support is built in and policy-controlled. When enabled, `srvbox` installs Caddy, owns the global Caddyfile, opens HTTP/HTTPS, and imports app-owned fragments from:

```text
/etc/caddy/sites.d/*.caddy
```

## License

MIT
