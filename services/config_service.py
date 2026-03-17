from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import difflib
import os
from pathlib import Path
import tempfile
from typing import Any

REQUIRED_POLICY_LINES = [
    "Table = off",
    "PostUp = ip -4 rule add iif tailscale0 table 51820 priority 100",
    "PostUp = ip -4 route add default dev %i table 51820",
    "PreDown = ip -4 rule del iif tailscale0 table 51820 priority 100",
    "PreDown = ip -4 route del default dev %i table 51820",
]


class ConfigError(Exception):
    """Base exception for config workflow failures."""


class ConfigValidationError(ConfigError):
    """Raised when a config fails required structure checks."""

    def __init__(self, errors: list[str], warnings: list[str] | None = None) -> None:
        self.errors = errors
        self.warnings = warnings or []
        message = "; ".join(errors) if errors else "Configuration validation failed."
        super().__init__(message)


@dataclass(frozen=True)
class SectionRange:
    name: str
    start: int
    end: int


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone().isoformat()


def _detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _section_name(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]") and len(stripped) > 2:
        return stripped[1:-1].strip()
    return None


def _normalize_policy_line(line: str) -> str:
    stripped = line.strip()
    if "=" not in stripped:
        return stripped
    key, _, value = stripped.partition("=")
    return f"{key.strip()}={value.strip()}"


REQUIRED_POLICY_NORMALIZED = {_normalize_policy_line(line) for line in REQUIRED_POLICY_LINES}
MAX_BACKUP_FILES = 3


class WireGuardConfigService:
    """Encapsulates safe config file operations and policy-routing transforms."""

    def __init__(self, active_path: Path, preset_dir: Path, backup_dir: Path) -> None:
        self.active_path = active_path.resolve()
        self.preset_dir = preset_dir.resolve()
        self.backup_dir = backup_dir.resolve()

        self.preset_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._prune_backups(max_files=MAX_BACKUP_FILES)

    def read_active_config(self) -> dict[str, Any]:
        if not self.active_path.exists():
            return {
                "path": str(self.active_path),
                "exists": False,
                "content": "",
                "size": 0,
                "modified": None,
            }

        content = self.active_path.read_text(encoding="utf-8", errors="replace")
        stat = self.active_path.stat()
        return {
            "path": str(self.active_path),
            "exists": True,
            "content": content,
            "size": stat.st_size,
            "modified": _iso(datetime.fromtimestamp(stat.st_mtime)),
        }

    def list_presets(self) -> list[dict[str, Any]]:
        presets: list[dict[str, Any]] = []
        for path in sorted(self.preset_dir.rglob("*.conf")):
            if not path.is_file():
                continue
            stat = path.stat()
            relative_name = path.relative_to(self.preset_dir).as_posix()
            presets.append(
                {
                    "name": relative_name,
                    "size": stat.st_size,
                    "modified": _iso(datetime.fromtimestamp(stat.st_mtime)),
                }
            )
        return presets

    def load_preset(self, filename: str) -> dict[str, Any]:
        path = self._resolve_safe_child(
            self.preset_dir,
            filename,
            allow_subdirectories=True,
        )
        if not path.exists() or not path.is_file():
            raise ConfigError(f"Preset '{filename}' was not found.")

        content = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
        return {
            "name": path.relative_to(self.preset_dir).as_posix(),
            "path": str(path),
            "content": content,
            "size": stat.st_size,
            "modified": _iso(datetime.fromtimestamp(stat.st_mtime)),
        }

    def list_backups(self) -> list[dict[str, Any]]:
        self._prune_backups(max_files=MAX_BACKUP_FILES)
        backups: list[dict[str, Any]] = []
        candidates = self._sorted_backup_candidates()
        for path in candidates:
            stat = path.stat()
            backups.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": _iso(datetime.fromtimestamp(stat.st_mtime)),
                }
            )
        return backups

    def load_backup(self, filename: str) -> dict[str, Any]:
        path = self._resolve_safe_child(self.backup_dir, filename)
        if not path.exists() or not path.is_file():
            raise ConfigError(f"Backup '{filename}' was not found.")

        content = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
        return {
            "name": path.name,
            "path": str(path),
            "content": content,
            "size": stat.st_size,
            "modified": _iso(datetime.fromtimestamp(stat.st_mtime)),
        }

    def restore_backup(self, filename: str) -> dict[str, Any]:
        backup = self.load_backup(filename)
        write_meta = self.write_active_config(backup["content"])
        return {
            "restored_from": backup["name"],
            "backup_created": write_meta.get("backup_file"),
        }

    def validate_config_structure(self, content: str) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        lines = content.splitlines()
        current_section: str | None = None
        interface_count = 0
        peer_count = 0

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                continue

            section = _section_name(line)
            if section is not None:
                current_section = section
                if section.lower() == "interface":
                    interface_count += 1
                if section.lower() == "peer":
                    peer_count += 1
                continue

            if current_section is None:
                errors.append(f"Line {idx}: setting appears before any section header.")
                continue

            if "=" not in stripped:
                warnings.append(f"Line {idx}: expected key = value format.")

        if interface_count == 0:
            errors.append("Missing required [Interface] section.")
        elif interface_count > 1:
            warnings.append("Multiple [Interface] sections found; wg-quick usually expects one.")

        if peer_count == 0:
            warnings.append("No [Peer] section found.")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "has_interface": interface_count > 0,
            "has_tailscale_policy": self.has_tailscale_policy_block(content),
        }

    def has_tailscale_policy_block(self, content: str) -> bool:
        lines = content.splitlines()
        interface = self._find_interface_section(lines)
        if interface is None:
            return False

        existing = {
            _normalize_policy_line(lines[index])
            for index in range(interface.start + 1, interface.end)
        }
        return REQUIRED_POLICY_NORMALIZED.issubset(existing)

    def add_tailscale_policy_block(self, content: str) -> dict[str, Any]:
        lines = content.splitlines(keepends=True)
        interface = self._find_interface_section(lines)
        if interface is None:
            raise ConfigValidationError(["Missing required [Interface] section."])

        existing = {
            _normalize_policy_line(lines[index])
            for index in range(interface.start + 1, interface.end)
        }

        missing_lines = [
            line for line in REQUIRED_POLICY_LINES if _normalize_policy_line(line) not in existing
        ]

        if not missing_lines:
            return {"content": content, "changed": False, "added": 0}

        newline = _detect_newline(content)
        insertion_index = interface.end
        rendered_missing = [f"{line}{newline}" for line in missing_lines]
        lines[insertion_index:insertion_index] = rendered_missing

        return {
            "content": "".join(lines),
            "changed": True,
            "added": len(missing_lines),
        }

    def remove_tailscale_policy_block(self, content: str) -> dict[str, Any]:
        lines = content.splitlines(keepends=True)
        interface = self._find_interface_section(lines)
        if interface is None:
            raise ConfigValidationError(["Missing required [Interface] section."])

        kept: list[str] = []
        removed = 0
        for index, line in enumerate(lines):
            if interface.start < index < interface.end:
                if _normalize_policy_line(line) in REQUIRED_POLICY_NORMALIZED:
                    removed += 1
                    continue
            kept.append(line)

        return {
            "content": "".join(kept),
            "changed": removed > 0,
            "removed": removed,
        }

    def apply_policy_mode(self, content: str, mode: str) -> dict[str, Any]:
        if mode == "enable":
            result = self.add_tailscale_policy_block(content)
            result.update({"mode": mode})
            return result
        if mode == "disable":
            result = self.remove_tailscale_policy_block(content)
            result.update({"mode": mode})
            return result

        return {
            "content": content,
            "changed": False,
            "mode": "keep",
            "added": 0,
            "removed": 0,
        }

    def build_side_by_side_diff(self, left_text: str, right_text: str) -> list[dict[str, Any]]:
        left = left_text.splitlines()
        right = right_text.splitlines()

        rows: list[dict[str, Any]] = []
        matcher = difflib.SequenceMatcher(a=left, b=right)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(i2 - i1):
                    rows.append(
                        {
                            "type": "equal",
                            "left_no": i1 + offset + 1,
                            "right_no": j1 + offset + 1,
                            "left": left[i1 + offset],
                            "right": right[j1 + offset],
                        }
                    )
                continue

            if tag == "replace":
                span = max(i2 - i1, j2 - j1)
                for offset in range(span):
                    left_idx = i1 + offset
                    right_idx = j1 + offset
                    rows.append(
                        {
                            "type": "replace",
                            "left_no": left_idx + 1 if left_idx < i2 else None,
                            "right_no": right_idx + 1 if right_idx < j2 else None,
                            "left": left[left_idx] if left_idx < i2 else "",
                            "right": right[right_idx] if right_idx < j2 else "",
                        }
                    )
                continue

            if tag == "delete":
                for offset in range(i1, i2):
                    rows.append(
                        {
                            "type": "delete",
                            "left_no": offset + 1,
                            "right_no": None,
                            "left": left[offset],
                            "right": "",
                        }
                    )
                continue

            if tag == "insert":
                for offset in range(j1, j2):
                    rows.append(
                        {
                            "type": "insert",
                            "left_no": None,
                            "right_no": offset + 1,
                            "left": "",
                            "right": right[offset],
                        }
                    )

        return rows

    def write_active_config(self, content: str) -> dict[str, Any]:
        active_parent = self.active_path.parent
        if not active_parent.exists():
            raise ConfigError(
                f"Active config parent directory does not exist: {active_parent}"
            )

        backup_file = None
        if self.active_path.exists() and self.active_path.is_file():
            backup_name = f"{self.active_path.stem}-{_now_stamp()}{self.active_path.suffix}.bak"
            backup_path = self.backup_dir / backup_name
            backup_path.write_bytes(self.active_path.read_bytes())
            backup_file = backup_path.name

        # Atomic replace to avoid partial writes if the process is interrupted.
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{self.active_path.name}.", dir=str(active_parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
            os.replace(tmp_path, self.active_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        deleted_backups = self._prune_backups(max_files=MAX_BACKUP_FILES)
        stat = self.active_path.stat()
        return {
            "path": str(self.active_path),
            "size": stat.st_size,
            "modified": _iso(datetime.fromtimestamp(stat.st_mtime)),
            "backup_file": backup_file,
            "deleted_backups": deleted_backups,
        }

    def _find_interface_section(self, lines: list[str]) -> SectionRange | None:
        sections = self._find_sections(lines)
        for section in sections:
            if section.name.lower() == "interface":
                return section
        return None

    def _find_sections(self, lines: list[str]) -> list[SectionRange]:
        sections: list[SectionRange] = []
        current_name: str | None = None
        current_start = -1

        for idx, line in enumerate(lines):
            section = _section_name(line)
            if section is None:
                continue
            if current_name is not None:
                sections.append(SectionRange(name=current_name, start=current_start, end=idx))
            current_name = section
            current_start = idx

        if current_name is not None:
            sections.append(
                SectionRange(name=current_name, start=current_start, end=len(lines))
            )

        return sections

    def _sorted_backup_candidates(self) -> list[Path]:
        return sorted(
            [p for p in self.backup_dir.iterdir() if p.is_file() and p.suffix == ".bak"],
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )

    def _prune_backups(self, max_files: int) -> list[str]:
        if max_files < 0:
            return []

        deleted: list[str] = []
        candidates = self._sorted_backup_candidates()
        for path in candidates[max_files:]:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            deleted.append(path.name)
        return deleted

    def _resolve_safe_child(
        self,
        parent: Path,
        filename: str,
        *,
        allow_subdirectories: bool = False,
    ) -> Path:
        filename = filename.strip()
        candidate_input = Path(filename)
        if not filename or candidate_input.is_absolute():
            raise ConfigError("Invalid file name.")

        if not allow_subdirectories and candidate_input.name != filename:
            raise ConfigError("Invalid file name.")

        candidate = (parent / candidate_input).resolve()
        parent_resolved = parent.resolve()

        try:
            candidate.relative_to(parent_resolved)
        except ValueError:
            raise ConfigError("Invalid path traversal attempt.")

        return candidate
