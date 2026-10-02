from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


class InstanceIdentityError(RuntimeError):
    """Raised when persistent data is bound to a different installation."""


_IDENTITY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_IDENTITY_FILE = ".personal-ai-instance.json"


def bind_instance_identity(data_dir: Path, instance_id: str) -> dict[str, str]:
    """Bind a persistent data directory to one immutable, non-secret identity.

    The marker is created once and never silently replaced. On existing data
    directories it adds only this small metadata file; it does not rewrite
    databases, vaults, keys, or user records.
    """
    identity = str(instance_id or "").strip()
    if not _IDENTITY_RE.fullmatch(identity):
        raise InstanceIdentityError(
            "PERSONAL_AI_INSTANCE_ID is required and must contain 1-64 lowercase letters, digits, or hyphens"
        )

    root = Path(data_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / _IDENTITY_FILE

    if marker.exists():
        return _verify_marker(marker, identity)

    payload = json.dumps(
        {"instance_id": identity, "created_at": datetime.now(timezone.utc).isoformat()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Another startup may have initialized it between the check and create.
        return _verify_marker(marker, identity)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        # Keep an incomplete marker fail-closed for explicit operator review.
        raise
    return {"instance_id": identity, "marker": str(marker), "created": "true"}


def _verify_marker(marker: Path, expected: str) -> dict[str, str]:
    try:
        stored = json.loads(marker.read_text(encoding="utf-8"))
        actual = stored.get("instance_id") if isinstance(stored, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstanceIdentityError("persistent installation identity marker is unreadable; refusing startup") from exc
    if actual != expected:
        raise InstanceIdentityError(
            "persistent data belongs to a different PERSONAL_AI_INSTANCE_ID; refusing startup"
        )
    return {"instance_id": expected, "marker": str(marker), "created": "false"}
