FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WG_APP_HOST=0.0.0.0 \
    WG_APP_PORT=5000 \
    WG_ACTIVE_CONFIG_PATH=/etc/wireguard/wg0.conf \
    WG_PRESET_DIR=/app/configs \
    WG_BACKUP_DIR=/app/backups \
    WG_RESTART_COMMAND=/usr/local/bin/restart-wireguard \
    WG_SYSTEMD_UNIT=wg-quick@wg0

RUN apt-get update \
    && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /etc/wireguard /app/configs /app/backups \
    && install -m 0755 /app/scripts/restart-wireguard.sh /usr/local/bin/restart-wireguard

EXPOSE 5000

CMD ["python", "app.py"]
