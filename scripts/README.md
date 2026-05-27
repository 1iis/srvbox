# `scripts/`

> Workstation-to-server deployment and remote bootstrapping.

## Philosophy
> Why artifact deployment?

A production server should not need `git` or GitHub credentials, let alone write access to source repositories.  
Instead, the workstation sends a complete artifact `/tmp/deploy/1iis/srvbox.tar.gz` which the server unpacks and installs.  

This gives us a small, inspectable deployment path: `tar`, `scp`, `ssh`, `sudo`, `sh`.

```text
Workstation
   🠋
  tar repo              /tmp/deploy/1iis/srvbox.tar.gz
  cat > runner script   /tmp/deploy/1iis/srvbox.run.sh
   🠋
  scp tarball + runner
   🠋
  ssh -t "sudo sh runner"
   🠋
Server (as root)
   🠋 runner extracts tarball
/tmp/deploy/1iis/srvbox/
   🠋 setup.sh
/opt/1iis/srvbox/releases/<stamp>/
   🠋 sync.py apply
Hardened host
```

## `deploy.sh`
> Workstation side

```text
./scripts/deploy.sh -s /path/to/repo -d user@host
```

1. Two files:
    - `$REPO.tar.gz`: clean tarball of the repo (excludes `.git`, `__pycache__`, temporary files).
    - `$REPO.run.sh`: temporary runner script.
3. `scp` uploads both in a single transaction to `/tmp/deploy/1iis/$REPO/`
4. `ssh -t` executes the runner remotely, so `sudo` has a TTY for the password prompt.

## `srvbox.run.sh`
> Runner script

### SSH and `sudo` TTY trap

To execute our setup on a remote host, we need to run an installation script with `sudo`. The naive approach is to use a here-doc over SSH:

```bash
# ANTI-PATTERN: Do not do this
ssh -t user@host "sudo sh -s" <<'EOF'
  echo "Doing root things"
  ./scripts/setup.sh
EOF
```

This fails disastrously if the remote user requires a password for `sudo`.

When `ssh -t` allocates a pseudo-terminal (TTY), `sudo` uses it to prompt for the user's password. However, because we are piping the script into `stdin` via the here-doc, `sudo` reads **from that same `stdin` stream**. It consumes the literal text of the deployment script and interprets it as the user's password attempt, printing it in cleartext to the terminal (which may leak into logs) and obviously fails authentication.

We also cannot rely on caching `sudo` credentials across multiple SSH calls, that cache is tied to the specific TTY session.

### Solution: Generated Runner

To safely elevate privileges without `stdin` collisions, the execution environment (TTY) and the script payload (file content) must be separated. We generate a tiny "runner" script locally, upload it alongside the tarball artifact, and execute it over a single interactive SSH session:

```bash
# 1. Generate runner locally
write_runner "$runner_file"

# 2. Upload both artifact and runner
scp "$artifact" "$runner_file" "$DST:/tmp/deploy/1iis/"

# 3. Execute interactively
ssh -t "$DST" "sudo env REPO='$repo' sh '/tmp/deploy/1iis/$remote_runner'"
```

By placing the commands in a remote file, `sudo` prompts securely via the TTY, and `sh` reads the commands safely from the filesystem. They do not fight over `stdin`.

### Why `ssh -t`?

`sudo` without a TTY refuses to prompt for a password in some configurations.  
Thus we need the terminal: `ssh -t` forces pseudo-terminal allocation.

> [!NOTE]
> This pretty much requires a human in the loop, gatekeeping deployment to production servers.
>
> **Good.**

> [!TIP]
> If you don't like it, use `sudo visudo` or a drop‑in file under `/etc/sudoers.d/`. For the deploy user `onei`, you’d add a line like:
> ```
> onei ALL=(root) NOPASSWD: /opt/1iis/srvbox/current/host/sync.py
> ```
> 
> Or whitelist the entire pipeline for broader deployment needs.
> ```
> onei ALL=(root) NOPASSWD: /opt/1iis/srvbox/current/host/sync.py, /bin/systemctl
> ```

---

## `setup.sh`
> Server side

`setup.sh` is executed by the runner inside the unpacked artifact at `/tmp/deploy/1iis/$REPO/`.

It expects to run as `root`.

### What it does

1. Ensures `python3` and `ca-certificates` are installed (`apt-get`).
2. Copies the unpacked source into a **timestamped release directory**:

   ```text
   /opt/1iis/srvbox/releases/20260527T034606Z/
   ```

3. Atomically updates the `current` symlink:

   ```text
   /opt/1iis/srvbox/current -> releases/20260527T034606Z/
   ```

4. Hands off to the reconciler:

   ```bash
   /opt/1iis/srvbox/current/host/sync.py apply
   ```

### Why `releases/current`?

- Rollback is just changing a symlink.
- The old release remains on disk until cleaned.
- The `sync.py` reconciler always runs from a stable, known path.

---

## `check.sh` — validation

Placeholder. Eventually: lint bash, `py_compile` Python, and dry-run checks that can be executed locally before `deploy.sh` is called.

---

## Design decisions and scars

**No `git` on the server.**  
Git is a development tool. Production hosts should not need repository access, SSH deploy keys, or internet reachability to GitHub.

**One upload, then `sudo`.**  
We initially tried to refresh `sudo` credentials in a separate `ssh` connection, then run the script in a second connection. `sudo` credential caching is session-local; the second `ssh` connection could not see the first. We merged auth and execution into a single `ssh -t` call.

**No inline here-docs with `sudo`.**  
Sending the script body through `stdin` works fine until `sudo` steals `stdin` for the password. A physical runner file eliminates the race entirely.

**Minimal server-side dependencies.**  
The only things the server must have before the first deploy are: `sh`, `sudo`, `mkdir`, `rm`, `tar`, `ln`, `date`, and an `apt-get` based system. `python3` is installed by `setup.sh` if missing.
