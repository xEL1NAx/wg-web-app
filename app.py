from __future__ import annotations

from dataclasses import dataclass
import io
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import time
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file, session

from services.config_service import (
    ConfigError,
    ConfigValidationError,
    WireGuardConfigService,
)

BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    active_config_path: Path
    preset_dir: Path
    backup_dir: Path
    secret_key: str
    restart_command: str
    auth_username: str | None
    auth_password: str | None


APPLY_RESTART_DELAY_SECONDS = 3


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    active_path = Path(os.getenv("WG_ACTIVE_CONFIG_PATH", "/etc/wireguard/wg0.conf"))
    preset_dir = Path(os.getenv("WG_PRESET_DIR", str(BASE_DIR / "configs")))
    backup_dir = Path(os.getenv("WG_BACKUP_DIR", str(BASE_DIR / "backups")))

    secret_key = os.getenv("WG_APP_SECRET") or secrets.token_hex(32)

    return Settings(
        active_config_path=active_path,
        preset_dir=preset_dir,
        backup_dir=backup_dir,
        secret_key=secret_key,
        restart_command=os.getenv("WG_RESTART_COMMAND", "systemctl restart wg-quick@wg0"),
        auth_username=os.getenv("WG_BASIC_AUTH_USER") or None,
        auth_password=os.getenv("WG_BASIC_AUTH_PASSWORD") or None,
    )


def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__)
    cfg = settings or load_settings()
    app.config["SECRET_KEY"] = cfg.secret_key

    service = WireGuardConfigService(
        active_path=cfg.active_config_path,
        preset_dir=cfg.preset_dir,
        backup_dir=cfg.backup_dir,
    )

    def api_error(message: str, status: int = 400, **extra: Any):
        payload = {"ok": False, "error": message}
        payload.update(extra)
        return jsonify(payload), status

    def api_ok(**extra: Any):
        payload = {"ok": True}
        payload.update(extra)
        return jsonify(payload)

    def is_auth_enabled() -> bool:
        return bool(cfg.auth_username and cfg.auth_password)

    def verify_auth() -> bool:
        if not is_auth_enabled():
            return True

        auth = request.authorization
        if auth is None:
            return False

        return (
            secrets.compare_digest(auth.username or "", cfg.auth_username or "")
            and secrets.compare_digest(auth.password or "", cfg.auth_password or "")
        )

    def ensure_csrf_token() -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    def normalize_policy_mode(raw: str | None) -> str:
        if raw is None:
            return "enable"
        mode = raw.strip().lower()
        if mode not in {"enable", "disable", "keep"}:
            return "enable"
        return mode

    def transform_and_validate(content: str, policy_mode: str) -> dict[str, Any]:
        transform_notes: list[str] = []
        try:
            transform = service.apply_policy_mode(content, policy_mode)
            transformed = transform["content"]
        except ConfigValidationError as exc:
            transform = {
                "content": content,
                "changed": False,
                "mode": policy_mode,
                "added": 0,
                "removed": 0,
            }
            transformed = content
            transform_notes.extend(exc.errors)

        validation = service.validate_config_structure(transformed)
        for err in transform_notes:
            if err not in validation["errors"]:
                validation["errors"].append(err)

        validation["valid"] = len(validation["errors"]) == 0

        return {
            "content": transformed,
            "transform": transform,
            "validation": validation,
        }

    def run_restart_command(delay_seconds: int = 0) -> dict[str, Any]:
        args = shlex.split(cfg.restart_command)
        if not args:
            return {
                "attempted": False,
                "success": False,
                "message": "Restart command is empty.",
                "delay_seconds": 0,
            }

        if delay_seconds > 0:
            time.sleep(delay_seconds)

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        return {
            "attempted": True,
            "success": result.returncode == 0,
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": cfg.restart_command,
            "delay_seconds": max(delay_seconds, 0),
        }

    @app.before_request
    def enforce_security_layers():
        if request.endpoint == "static":
            return None

        if not verify_auth():
            return Response(
                "Authentication required",
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="WireGuard Admin"'},
            )

        ensure_csrf_token()

        if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            header_token = request.headers.get("X-CSRF-Token", "")
            if not header_token or not secrets.compare_digest(
                header_token, session.get("csrf_token", "")
            ):
                return api_error(
                    "Invalid CSRF token. Refresh the page and try again.",
                    status=403,
                )

        return None

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            active_config_path=str(cfg.active_config_path),
            preset_dir=str(cfg.preset_dir),
            backup_dir=str(cfg.backup_dir),
            restart_enabled=True,
            auth_enabled=is_auth_enabled(),
        )

    @app.get("/api/bootstrap")
    def bootstrap():
        return api_ok(
            csrf_token=session.get("csrf_token"),
            settings={
                "active_config_path": str(cfg.active_config_path),
                "preset_dir": str(cfg.preset_dir),
                "backup_dir": str(cfg.backup_dir),
                "restart_enabled": True,
            },
        )

    @app.get("/api/active")
    def active_config():
        active = service.read_active_config()
        validation = service.validate_config_structure(active["content"])
        active["validation"] = validation
        active["has_tailscale_policy"] = validation["has_tailscale_policy"]
        return api_ok(active=active)

    @app.get("/api/presets")
    def presets():
        return api_ok(presets=service.list_presets())

    @app.get("/api/presets/<path:filename>")
    def preset_detail(filename: str):
        preset = service.load_preset(filename)
        preset["validation"] = service.validate_config_structure(preset["content"])
        return api_ok(preset=preset)

    @app.post("/api/apply-preset")
    def apply_preset():
        payload = request.get_json(silent=True) or {}
        preset_name = payload.get("preset_name", "")
        if not isinstance(preset_name, str) or not preset_name.strip():
            return api_error("preset_name is required.")

        policy_mode = normalize_policy_mode(payload.get("policy_mode"))

        preset = service.load_preset(preset_name.strip())
        transformed = transform_and_validate(preset["content"], policy_mode)

        if not transformed["validation"]["valid"]:
            return api_error(
                "Preset config failed validation; file was not written.",
                status=422,
                validation=transformed["validation"],
                transformed_content=transformed["content"],
            )

        write_meta = service.write_active_config(transformed["content"])
        restart_meta = run_restart_command(delay_seconds=APPLY_RESTART_DELAY_SECONDS)

        return api_ok(
            message=f"Applied preset '{preset_name}' to active config.",
            write=write_meta,
            validation=transformed["validation"],
            transform=transformed["transform"],
            restart=restart_meta,
        )

    @app.post("/api/preview")
    def preview():
        payload = request.get_json(silent=True) or {}
        content = payload.get("content")
        if not isinstance(content, str):
            return api_error("content must be a string.")

        policy_mode = normalize_policy_mode(payload.get("policy_mode"))

        transformed = transform_and_validate(content, policy_mode)
        active = service.read_active_config()
        diff_rows = service.build_side_by_side_diff(
            active.get("content", ""), transformed["content"]
        )

        return api_ok(
            preview={
                "transformed_content": transformed["content"],
                "validation": transformed["validation"],
                "transform": transformed["transform"],
                "diff_rows": diff_rows,
                "changed_from_active": active.get("content", "")
                != transformed["content"],
            }
        )

    @app.post("/api/save")
    def save_active():
        payload = request.get_json(silent=True) or {}
        content = payload.get("content")
        if not isinstance(content, str):
            return api_error("content must be a string.")

        policy_mode = normalize_policy_mode(payload.get("policy_mode"))

        transformed = transform_and_validate(content, policy_mode)
        if not transformed["validation"]["valid"]:
            return api_error(
                "Config failed validation; file was not written.",
                status=422,
                validation=transformed["validation"],
                transformed_content=transformed["content"],
                transform=transformed["transform"],
            )

        write_meta = service.write_active_config(transformed["content"])
        restart_meta = run_restart_command(delay_seconds=APPLY_RESTART_DELAY_SECONDS)

        return api_ok(
            message="Active config updated successfully.",
            write=write_meta,
            validation=transformed["validation"],
            transform=transformed["transform"],
            transformed_content=transformed["content"],
            restart=restart_meta,
        )

    @app.post("/api/parse-test")
    def parse_test():
        payload = request.get_json(silent=True) or {}
        content = payload.get("content")
        if not isinstance(content, str):
            return api_error("content must be a string.")

        validation = service.validate_config_structure(content)
        return api_ok(validation=validation)

    @app.post("/api/download")
    def download_config():
        payload = request.get_json(silent=True) or {}
        content = payload.get("content")
        if not isinstance(content, str):
            return api_error("content must be a string.")

        filename = payload.get("filename", "wg0-generated.conf")
        if not isinstance(filename, str):
            filename = "wg0-generated.conf"

        safe_name = Path(filename).name
        if not safe_name.endswith(".conf"):
            safe_name = f"{safe_name}.conf"

        stream = io.BytesIO(content.encode("utf-8"))
        return send_file(
            stream,
            mimetype="text/plain",
            as_attachment=True,
            download_name=safe_name,
        )

    @app.get("/api/backups")
    def backup_list():
        return api_ok(backups=service.list_backups())

    @app.post("/api/restore-backup")
    def restore_backup():
        payload = request.get_json(silent=True) or {}
        backup_name = payload.get("backup_name", "")
        if not isinstance(backup_name, str) or not backup_name.strip():
            return api_error("backup_name is required.")

        result = service.restore_backup(backup_name.strip())
        restart_meta = run_restart_command(delay_seconds=APPLY_RESTART_DELAY_SECONDS)
        return api_ok(
            message=f"Restored backup '{backup_name}'.",
            restore=result,
            restart=restart_meta,
        )

    @app.post("/api/restart")
    def restart_wg():
        result = run_restart_command()
        if result["attempted"] and not result["success"]:
            return api_error(
                "Restart command failed.",
                status=500,
                restart=result,
            )

        if not result["attempted"]:
            return api_error(result["message"], status=400, restart=result)

        return api_ok(message="WireGuard service restarted.", restart=result)

    @app.errorhandler(ConfigError)
    def handle_config_error(exc: ConfigError):
        if request.path.startswith("/api/"):
            return api_error(str(exc), status=400)
        return Response(str(exc), status=400, mimetype="text/plain")

    @app.errorhandler(FileNotFoundError)
    def handle_not_found(exc: FileNotFoundError):
        if request.path.startswith("/api/"):
            return api_error(str(exc), status=404)
        return Response(str(exc), status=404, mimetype="text/plain")

    @app.errorhandler(PermissionError)
    def handle_permission_error(exc: PermissionError):
        if request.path.startswith("/api/"):
            return api_error(
                f"Permission denied: {exc}. Try running with elevated permissions.",
                status=403,
            )
        return Response(str(exc), status=403, mimetype="text/plain")

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        app.logger.exception("Unhandled exception", exc_info=exc)
        if request.path.startswith("/api/"):
            return api_error("Unexpected server error.", status=500)
        return Response("Unexpected server error.", status=500, mimetype="text/plain")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("WG_APP_HOST", "127.0.0.1"),
        port=int(os.getenv("WG_APP_PORT", "5000")),
        debug=env_bool("WG_APP_DEBUG", False),
    )
