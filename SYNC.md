# Syncing ViMento

The authoritative copy of the backend is the **production tree on the VPS**, at
`root@31.97.180.251:/opt/vibe-trading`. It is not a git checkout. This repo and
that tree have drifted apart before, so sync deliberately, with these tools.

## Quick reference

| Task | Command |
|---|---|
| See what differs | `./scripts/sync-vps.sh status` |
| Bring VPS code down | `./scripts/sync-vps.sh pull --yes` |
| Send local code up | `./scripts/sync-vps.sh push --yes` |
| Run the backend locally | `./scripts/dev-local.sh` |
| Stop it | `./scripts/dev-local.sh --stop` |
| From Windows | double-click `sync.bat` |

`pull` and `push` are **dry-run without `--yes`**. Run them bare first and read
the file list.

## Run it from WSL, not Windows

The VPS SSH key lives in the WSL home directory. From Windows, `cmd.exe` git and
ssh will fail with `Permission denied (publickey)`.

```bash
wsl -d Ubuntu-24.04 -- bash -c 'cd /home/idona/MoStar/_apps/ViMento && ./scripts/sync-vps.sh status'
```

`sync.bat` just wraps that call.

## Commit from Windows git, never from WSL

Windows git has `core.autocrlf=true`; WSL git has it unset. The same clean tree
looks like **93 modified files and a 21,033-line diff** from WSL. Nothing is
actually wrong — but committing from WSL bakes that churn into history.

```
# Windows -> clean
$ git status --porcelain
?? .venv/
```

## The two trees are not mirrors

Neither side is a superset, so **`rsync --delete` is never used** in either
direction, and the scripts will not do it.

| Exists only in the repo | Exists only on the VPS |
|---|---|
| `server/`, `src/`, `package.json` | `backend/scripts/docker-compose.yml` |
| `deploy.sh`, `Dockerfile.prod` | `cutover_manifest.sql` |
| `docker-compose.prod.yml`, `nginx/` | `paper_certification_report.sql` |

`backend/scripts/docker-compose.yml` defines all 13 running containers and is
**not in git**. `deploy.sh remote` runs `rsync --delete` and would delete it —
do not use `deploy.sh remote` against this host.

`paper_sessions/` (~700 MB of runtime state) is excluded from both directions.

## Pushing code does not deploy it

`push` copies files. The containers keep running the image they were built from.
To actually roll out:

```bash
ssh root@31.97.180.251 'cd /opt/vibe-trading/backend/scripts && docker compose up -d --build'
```

That **restarts live paper-trading agents** and interrupts open sessions. `push`
snapshots the remote to `/root/vibe-trading-backup-<timestamp>.tar.gz` first; roll
back by untarring it over `/opt/vibe-trading`.

## Known repo faults

These are real and still unfixed — `dev-local.sh` works around them:

1. **`pip install -e .` fails**: `error in 'egg_base' option: 'agent' does not exist`.
   `pyproject.toml` declares `package-dir = {"" = "agent"}` and `where = ["agent"]`,
   but the tree is `backend/agent/`. Install `backend/agent/requirements.txt`
   instead and put `backend/agent` on `sys.path`.
2. **`backend/agent/cli/_version.py` has gone missing before.** `api_server.py`
   imports it at module scope, so its absence is a hard crash. Restore with
   `./scripts/sync-vps.sh pull --yes`.
3. **`backend/frontend` must be a symlink to `../frontend`.** `api_server.py`
   resolves the UI as `__file__/../../frontend/dist`; Docker flattens `agent/`
   to `/app/agent` so it lands on `/app/frontend`, but a checkout needs the link.

## About the AI Studio builder URL

Bundles served from `ais-dev-*.run.app` **cannot be fetched by a script**. The
URL 302-redirects to `/__cookie_check.html` and returns a ~10 KB HTML page to any
non-browser client:

```
$ curl -sL -o /dev/null -w '%{http_code} %{content_type}\n' https://ais-dev-....run.app/vibe-trading.zip
200 text/html
```

`curl | tar` therefore unpacks an HTML error page, which is the cause of
`tar.exe: Unrecognized archive format`. The host is also ephemeral and dies with
the AI Studio session. Do not build sync automation — and especially not a
GitHub Action that auto-commits to `main` — on top of that URL.
