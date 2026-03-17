FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WG_APP_HOST=0.0.0.0 \
    WG_APP_PORT=5000 \
    WG_ACTIVE_CONFIG_PATH=/data/wg0.conf \
    WG_PRESET_DIR=/app/configs \
    WG_BACKUP_DIR=/app/backups \
    WG_RESTART_COMMAND=true

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data /app/configs /app/backups \
    && touch /data/wg0.conf \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 5000

CMD ["python", "app.py"]
