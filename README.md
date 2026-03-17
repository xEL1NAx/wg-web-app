# WireGuard Config Console

A Flask-based admin UI to view, validate, edit, and apply WireGuard config changes safely.

## What This App Does

- Manages active config at `/etc/wireguard/wg0.conf` (or a custom path)
- Creates timestamped backups before writes (keeps latest 3)
- Supports preset configs from `./configs` and one-time pasted configs
- Provides dry-run preview, validation, and side-by-side diff before apply
- Supports backup restore and config download
- Optionally protects access with HTTP Basic Auth

## Requirements

- Python 3.11+ (for local run)
- Docker + Docker Compose (for container run)
- Access to `/etc/wireguard/wg0.conf` on the host

## Quick Start

### Option A: Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: <http://127.0.0.1:5000>

### Option B: Run with Docker Compose

1. Ensure host path exists: `/etc/wireguard/wg0.conf`
2. Ensure the host uses `systemd` (`systemctl` must manage `wg-quick@wg0`)
3. Start services:

```bash
docker compose up -d --build
```

4. Open: <http://127.0.0.1:5000>

Stop:

```bash
docker compose down
```

If port 5000 is busy:

```bash
WG_APP_PORT_HOST=5001 docker compose up -d --build
```

## Docker Image

Default compose image is built locally from this repo:

```bash
docker compose build
```

Published image (optional):

```bash
docker pull ghcr.io/xel1nax/wg-web-app:latest
```

If GitHub Container Registry pull returns `403`, authenticate first:

```bash
docker logout ghcr.io
echo "$GHCR_PAT" | docker login ghcr.io -u xEL1NAx --password-stdin
```

`GHCR_PAT` should include at least `read:packages` (and `repo` for private package access).

## Docker Compose Reference

Current compose file (`docker-compose.yml`):

```yaml
name: wg-web-app
services:
  wg-web-app:
    container_name: wg-web-app
    image: wg-web-app:local
    build:
      context: .
    environment:
      - WG_APP_HOST=0.0.0.0
      - WG_APP_PORT=5000
      - WG_ACTIVE_CONFIG_PATH=/etc/wireguard/wg0.conf
      - WG_PRESET_DIR=/app/configs
      - WG_BACKUP_DIR=/app/backups
      - WG_RESTART_COMMAND=/usr/local/bin/restart-wireguard
      - WG_SYSTEMD_UNIT=wg-quick@wg0
    ports:
      - target: 5000
        published: "${WG_APP_PORT_HOST:-5000}"
        protocol: tcp
    pid: host
    privileged: true
    volumes:
      - type: bind
        source: /etc/wireguard
        target: /etc/wireguard
      - type: bind
        source: /proc
        target: /host/proc
        read_only: true
      - type: bind
        source: ./configs
        target: /app/configs
      - type: bind
        source: ./backups
        target: /app/backups
    restart: unless-stopped
```

### CasaOS Example (Confirmed Working)

If you deploy with CasaOS and host paths under `/DATA`, use this pattern:

```yaml
services:
  wg-web-app:
    image: ghcr.io/xel1nax/wg-web-app:latest
    network_mode: host
    pid: host
    privileged: true
    environment:
      - WG_ACTIVE_CONFIG_PATH=/etc/wireguard/wg0.conf
      - WG_PRESET_DIR=/app/configs
      - WG_BACKUP_DIR=/app/backups
      - WG_RESTART_COMMAND=/usr/local/bin/restart-wireguard
      - WG_SYSTEMD_UNIT=wg-quick@wg0
    volumes:
      - /etc/wireguard:/etc/wireguard
      - /proc:/host/proc:ro
      - /DATA/AppData/wg-web-app/configs:/app/configs
      - /DATA/AppData/wg-web-app/backups:/app/backups
```

## Configuration

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `WG_ACTIVE_CONFIG_PATH` | `/etc/wireguard/wg0.conf` | Active WireGuard config file path |
| `WG_PRESET_DIR` | `./configs` | Directory for preset `.conf` files |
| `WG_BACKUP_DIR` | `./backups` | Directory for automatic backups |
| `WG_APP_HOST` | `127.0.0.1` | Flask bind host |
| `WG_APP_PORT` | `5000` | Flask listen port |
| `WG_APP_DEBUG` | `false` | Flask debug mode |
| `WG_APP_SECRET` | generated random | Flask session/CSRF secret |
| `WG_RESTART_COMMAND` | `systemctl restart --now wg-quick@wg0` | Command used after apply/save/restore (Docker image default: `/usr/local/bin/restart-wireguard`) |
| `WG_SYSTEMD_UNIT` | `wg-quick@wg0` | WireGuard systemd unit name used by `/usr/local/bin/restart-wireguard` |
| `WG_NSENTER_TARGET_PID` | `1` | PID target used by restart helper for namespace entry (`nsenter -t`) |
| `WG_BASIC_AUTH_USER` | unset | Enables Basic Auth when set with password |
| `WG_BASIC_AUTH_PASSWORD` | unset | Enables Basic Auth when set with username |

Example:

```bash
export WG_ACTIVE_CONFIG_PATH="/tmp/wg0.conf"
python app.py
```

## Usage Notes

### Presets (`./configs`)

- Drop `.conf` files in `./configs` (subfolders supported)
- Load for preview, then apply to active config if valid
- Preset files are never modified by apply actions

### One-time Paste

- Paste/upload config text for temporary editing
- Content stays in browser memory only
- Nothing is saved as a preset unless you explicitly do so

### Restarting `wg-quick@wg0` from Docker

- The image includes `/usr/local/bin/restart-wireguard`
- It restarts WireGuard through host `systemd` using `nsenter`:
  - `systemctl restart --now wg-quick@wg0`
- For this to work, the container must run with:
  - `pid: host`
  - `privileged: true`
- The helper also tries `/host/proc/1/ns/*` namespace entry as a fallback.
- If you prefer another method, override `WG_RESTART_COMMAND`

### Restart Troubleshooting

- If you see `Configured restart command is a no-op`, your runtime still uses `WG_RESTART_COMMAND=true` or another no-op value.
- Ensure all three are present together:
  - `pid: host`
  - `privileged: true`
  - `/proc:/host/proc:ro`
- Quick checks:

```bash
docker compose exec wg-web-app sh -lc 'echo "$WG_RESTART_COMMAND"; cat /host/proc/1/comm'
docker inspect wg-web-app --format 'Privileged={{.HostConfig.Privileged}} PidMode={{.HostConfig.PidMode}}'
docker compose exec wg-web-app /usr/local/bin/restart-wireguard
```

## Security and Permissions

- Writes are restricted to configured active config path
- Preset and backup operations are path-scoped and traversal-protected
- CSRF protection is enabled on mutating API calls
- Optional HTTP Basic Auth is supported via env vars
- Host service restart requires elevated container privileges (`pid: host` + `privileged: true`)

For `/etc/wireguard/wg0.conf`, run with an account/container that has required write permissions.

## Keyboard Shortcuts

- `Ctrl/Cmd + Enter`: Preview dry run
- `Ctrl/Cmd + S`: Save active config

## Project Structure

```text
wg-web-app/
├── app.py
├── services/
├── templates/
├── static/
├── configs/
├── backups/
├── scripts/
│   └── restart-wireguard.sh
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```
