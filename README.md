# srvbox

> A small production server baseline, in Python.

`srvbox` turns a fresh Ubuntu/Debian-like host into a boring, hardened server substrate.

## Quick start

```sh
./scripts/deploy.sh -d user@host
```

This builds a local artifact, uploads it over SSH, installs a root-owned release under `/opt/1iis/srvbox/releases/`, updates `/opt/1iis/srvbox/current`, then runs the host reconciler.

## What it sets up

- root-owned timestamped releases
- base `/opt/1iis`, `/etc/1iis`, `/var/lib/1iis`, `/var/log/1iis` directories
- SSH hardening via `/etc/ssh/sshd_config.d/`
- `ufw` firewall baseline
- unattended security upgrades
- fail2ban installed/configured, policy-controlled
- optional Caddy ingress with `/etc/caddy/sites.d/*.caddy` fragments

## Map

- [`scripts/`](scripts/) — deploy, setup, and smoke-check scripts
- [`scripts/README.md`](scripts/README.md) — deployment path and operational notes
- [`host/sync.py`](host/sync.py) — stdlib-only host reconciler
- [`host/sync.ipynb`](host/sync.ipynb) — literate source for the reconciler
- [`docs/mvp-roadmap.md`](docs/mvp-roadmap.md) — roadmap notes
- [`templates/`](templates/) — example host/app configuration shapes

## Commands

```sh
./scripts/check.sh
python3 host/sync.py status
sudo python3 host/sync.py apply
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
