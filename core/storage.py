from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Mapping


class StorageUnavailable(RuntimeError):
    """Raised when hosted Personal AI cannot prove it is using durable storage."""


def _decode_mount_path(value: str) -> str:
    # Linux mountinfo escapes whitespace and backslashes with octal sequences.
    return (
        value.replace('\\040', ' ')
        .replace('\\011', '\t')
        .replace('\\012', '\n')
        .replace('\\134', '\\')
    )


def _linux_mount_points() -> set[Path]:
    mountinfo = Path('/proc/self/mountinfo')
    if not mountinfo.exists():
        return set()
    points: set[Path] = set()
    try:
        for line in mountinfo.read_text(encoding='utf-8', errors='replace').splitlines():
            fields = line.split()
            if len(fields) < 5:
                continue
            points.add(Path(_decode_mount_path(fields[4])).resolve())
    except OSError:
        return set()
    return points


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _write_probe(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    probe = data_dir / f'.personal-ai-storage-probe-{os.getpid()}-{os.urandom(6).hex()}'
    payload = os.urandom(32)
    try:
        with probe.open('wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if probe.read_bytes() != payload:
            raise StorageUnavailable('Hosted Personal AI storage probe could not be read back correctly')
    except StorageUnavailable:
        raise
    except OSError as exc:
        raise StorageUnavailable('Hosted Personal AI durable storage is not writable') from exc
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def validate_runtime_storage(
    settings,
    *,
    environ: Mapping[str, str] | None = None,
    mount_points: Iterable[Path | str] | None = None,
) -> dict:
    """Validate the runtime data root before any hosted database is opened.

    Hosted Personal AI must resolve its data directory beneath a non-root mount
    rooted at ``PERSONAL_AI_DURABLE_ROOT`` (``/data`` by default). This prevents
    Railway or another hosted runtime from silently falling back to ephemeral
    container storage. Local/desktop use remains unchanged.

    ``mount_points`` is injectable for deterministic tests. In production it is
    derived from Linux ``/proc/self/mountinfo``.
    """

    env = os.environ if environ is None else environ
    hosted = bool(
        getattr(settings, 'hosted_runtime', False)
        or getattr(settings, 'cloud_runtime_enabled', False)
    )
    data_dir = Path(getattr(settings, 'data_dir')).expanduser().resolve()

    if not hosted:
        data_dir.mkdir(parents=True, exist_ok=True)
        return {
            'state': 'local',
            'hosted': False,
            'data_dir': str(data_dir),
            'durable': False,
            'mount_point': None,
        }

    durable_root = Path(env.get('PERSONAL_AI_DURABLE_ROOT', '/data')).expanduser().resolve()
    if not _is_within(data_dir, durable_root):
        raise StorageUnavailable(
            'Hosted Personal AI refuses ephemeral storage: PERSONAL_AI_DATA_DIR '
            f'must resolve beneath {durable_root}'
        )

    raw_points = _linux_mount_points() if mount_points is None else mount_points
    points = {Path(point).expanduser().resolve() for point in raw_points}
    qualifying = [
        point
        for point in points
        if point != Path('/')
        and _is_within(point, durable_root)
        and _is_within(data_dir, point)
    ]
    if not qualifying:
        raise StorageUnavailable(
            'Hosted Personal AI cannot prove that its data directory is backed by '
            f'a durable mount beneath {durable_root}'
        )

    # Prefer the most specific qualifying mount when nested mounts exist.
    mount_point = max(qualifying, key=lambda item: len(item.parts))
    _write_probe(data_dir)
    return {
        'state': 'ready',
        'hosted': True,
        'data_dir': str(data_dir),
        'durable_root': str(durable_root),
        'durable': True,
        'mount_point': str(mount_point),
    }
