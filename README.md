# WireGuard Config Console

A local Flask web app for managing WireGuard `wg0.conf` with a polished dashboard.

## Features

- View, edit, validate, preview, and write active WireGuard config
- Configurable active config path (default: `/etc/wireguard/wg0.conf`)
- Timestamped backups before each write (keeps newest 3, auto-deletes older backups)
- Preset library from `./configs/` (including nested subfolders) with preview and apply
- One-time pasted config workflow (memory only, never saved as preset)
- Tailscale relay policy-routing block is enabled by default:
  - added exactly once
  - avoids duplicates
  - inserted inside `[Interface]`
- Validation checks (`[Interface]` required before write)
- Side-by-side diff preview (current vs result)
- Dry-run preview mode
- Backup browser with restore
- Download generated config
- Parse test action
- Auto-restart `wg-quick@wg0` 3 seconds after apply/save/restore plus manual restart button
- Dark, responsive, custom UI with keyboard shortcuts

## Project Structure

```text
wg-web-app/
├── app.py
├── services/
│   ├── __init__.py
│   └── config_service.py
├── templates/
│   └── index.html
├── static/
│   ├── css/
│   │   └── styles.css
│   └── js/
│       └── app.js
├── configs/
│   ├── .gitkeep
│   └── sample-client.conf
├── backups/
│   └── .gitkeep
├── data/
│   └── .gitkeep
├── Dockerfile
├── .dockerignore
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Setup

1. Create and activate a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Run the app.

```bash
python app.py
```

4. Open:

- [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Docker

### Build and run with Docker

```bash
docker build -t wg-web-app .
docker run --rm -p 5000:5000 \
  -v "$(pwd)/configs:/app/configs" \
  -v "$(pwd)/backups:/app/backups" \
  -v "$(pwd)/data:/data" \
  wg-web-app
```

Then open:

- [http://127.0.0.1:5000](http://127.0.0.1:5000)

Published image (GitHub Container Registry):

```bash
docker pull ghcr.io/xel1nax/wg-web-app:latest
```

### Run with Docker Compose

Sample `docker-compose.yml`:

```yaml
services:
  wg-web-app:
    image: ghcr.io/xel1nax/wg-web-app:latest
    container_name: wg-web-app
    ports:
      - "${WG_APP_PORT_HOST:-5000}:5000"
    environment:
      WG_APP_HOST: 0.0.0.0
      WG_APP_PORT: 5000
      WG_ACTIVE_CONFIG_PATH: /data/wg0.conf
      WG_PRESET_DIR: /app/configs
      WG_BACKUP_DIR: /app/backups
      WG_RESTART_COMMAND: "true"
    volumes:
      - ./configs:/app/configs
      - ./backups:/app/backups
      - ./data:/data
    restart: unless-stopped
```

Start:

```bash
docker compose up -d
```

If port `5000` is already in use on your host:

```bash
WG_APP_PORT_HOST=5001 docker compose up -d
```

Stop:

```bash
docker compose down
```

Container defaults:

- `WG_APP_PORT_HOST=5000` (compose host port mapping)
- `WG_APP_HOST=0.0.0.0`
- `WG_APP_PORT=5000`
- `WG_ACTIVE_CONFIG_PATH=/data/wg0.conf`
- `WG_PRESET_DIR=/app/configs`
- `WG_BACKUP_DIR=/app/backups`
- `WG_RESTART_COMMAND=true`

You can override any env var in `docker-compose.yml` or with `docker run -e ...`.

## Configuration

The app is configured via environment variables.

- `WG_ACTIVE_CONFIG_PATH` (default: `/etc/wireguard/wg0.conf`)
- `WG_PRESET_DIR` (default: `./configs`)
- `WG_BACKUP_DIR` (default: `./backups`)
- `WG_APP_HOST` (default: `127.0.0.1`)
- `WG_APP_PORT` (default: `5000`)
- `WG_APP_DEBUG` (default: `false`)
- `WG_APP_SECRET` (optional Flask secret key)
- `WG_RESTART_COMMAND` (default: `systemctl restart wg-quick@wg0`)
- `WG_BASIC_AUTH_USER` (optional)
- `WG_BASIC_AUTH_PASSWORD` (optional)

### Example: change active config path

```bash
export WG_ACTIVE_CONFIG_PATH="/tmp/wg0.conf"
python app.py
```

## Preset Configs (`./configs`)

- Drop `.conf` files into the preset directory (subfolders are supported).
- Open the **Presets** tab in the dashboard.
- Subfolder entries are shown with their folder path in the preset list.
- Use **Load For Preview** to inspect/edit before writing.
- Use **Apply To Active** to write directly to active config.
- Original preset files are never modified during apply.

## One-Time Pasted Config Behavior

- The **One-time paste** tab accepts full config text.
- You can upload a config file to extract its content into the editor.
- Pasted text is only held in browser memory.
- Uploaded file content is only held in browser memory.
- It is not written to preset files automatically.
- You can preview/transform/validate it and then explicitly write to active config.
- Refreshing the page may discard the pasted text.

## Permissions Notes (`/etc/wireguard/wg0.conf`)

Writing to `/etc/wireguard/wg0.conf` usually requires elevated privileges.

Options:

- Run app with permissions that can write the target file
- Use a non-system path during development (`WG_ACTIVE_CONFIG_PATH=/tmp/wg0.conf`)
- Configure appropriate filesystem permissions/ACLs for a dedicated admin user

Keep this tool on a trusted private admin machine.

## Security Notes

- Writes are restricted to the configured active config path only
- Backups/restores are restricted to configured backup directory
- Preset loading is restricted to configured preset directory
- Path traversal is blocked on preset and backup path operations
- CSRF protection is enforced on mutating API calls
- Optional HTTP Basic Auth is available via env vars

## Keyboard Shortcuts

- `Ctrl/Cmd + Enter`: preview dry run
- `Ctrl/Cmd + S`: write active config

## Development Tips

- Start with `WG_ACTIVE_CONFIG_PATH=/tmp/wg0.conf` for safe local testing.
- Check the **Backups** panel after writes and use restore if needed.
