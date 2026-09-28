"""Checks for a separate Stage 11 qualification process.

Does not start a server and does not write a Stage 11 result.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.storage import _is_within, _linux_mount_points
from qualification.stage11_identity import PRODUCTION_HOST, QUALIFICATION, SHA

DEFAULT_DATA_NAME = '.stage11-qualification-data'
EPHEMERAL_ROOTS = (
    Path('/tmp'),
    Path('/var/tmp'),
    Path('/dev'),
    Path('/dev/shm'),
    Path('/run'),
    Path('/proc'),
    Path('/sys'),
)


def assert_separate_from_production(host: str) -> None:
    name = host.split(',')[0].strip().split('://')[-1].split('/')[0].lower()
    if name.startswith('['):
        name = name.split(']')[0].strip('[')
    elif name.count(':') == 1:
        name = name.split(':', 1)[0]
    if name == PRODUCTION_HOST:
        raise ValueError('refusing_production_host')
    if name.endswith('.trycloudflare.com'):
        raise ValueError('refusing_unqualified_host')


def qualification_process(*, source_sha: str, data_dir: Path, host: str) -> dict[str, str]:
    assert_separate_from_production(host)
    source_sha = source_sha.strip().lower()
    if not SHA.fullmatch(source_sha):
        raise ValueError('source_sha_not_exact')
    resolved = data_dir.expanduser().resolve()
    if resolved == (Path.home() / '.personal_ai').resolve():
        raise ValueError('refusing_default_owner_data_dir')
    if resolved == Path.home().resolve():
        raise ValueError('refusing_home_directory')
    return {
        'PERSONAL_AI_ENVIRONMENT': QUALIFICATION,
        'PERSONAL_AI_SOURCE_SHA': source_sha,
        'PERSONAL_AI_DATA_DIR': str(resolved),
        'PERSONAL_AI_PRODUCTION': 'false',
        'MODEL_EVALUATION_ON_STARTUP': 'false',
    }


def qualification_durability(
    data_dir: Path,
    durable_root: Path,
    mount_points,
) -> dict:
    """Production stays a separate flag. Durable means a non-ephemeral mount."""
    data_dir = data_dir.expanduser().resolve()
    durable_root = durable_root.expanduser().resolve()
    if durable_root == Path('/') or any(durable_root == root or _is_within(durable_root, root) for root in EPHEMERAL_ROOTS):
        return {'durable': False, 'reason': 'durable_root_is_ephemeral', 'mount_point': None}
    if not _is_within(data_dir, durable_root):
        return {'durable': False, 'reason': 'data_dir_outside_durable_root', 'mount_point': None}
    owner_default = (Path.home() / '.personal_ai').resolve()
    if data_dir == owner_default or _is_within(data_dir, owner_default):
        return {'durable': False, 'reason': 'refusing_default_owner_data_dir', 'mount_point': None}
    if any(data_dir == root or _is_within(data_dir, root) for root in EPHEMERAL_ROOTS):
        return {'durable': False, 'reason': 'data_dir_is_ephemeral', 'mount_point': None}
    points = [Path(point).expanduser().resolve() for point in mount_points]
    qualifying = [
        point
        for point in points
        if point != Path('/')
        and point not in EPHEMERAL_ROOTS
        and not any(_is_within(point, root) for root in EPHEMERAL_ROOTS)
        and _is_within(point, durable_root)
        and _is_within(data_dir, point)
    ]
    if not qualifying:
        return {'durable': False, 'reason': 'no_durable_mount', 'mount_point': None}
    mount_point = max(qualifying, key=lambda item: len(item.parts))
    return {'durable': True, 'reason': 'mounted', 'mount_point': str(mount_point)}


def durability_from_environ(environ: dict | None = None, mount_points=None) -> dict:
    env = os.environ if environ is None else environ
    raw_root = str(env.get('PERSONAL_AI_QUALIFICATION_DURABLE_ROOT', '')).strip()
    raw_data = str(env.get('PERSONAL_AI_DATA_DIR', '')).strip()
    if not raw_root or not raw_data:
        return {'durable': False, 'reason': 'durable_root_missing', 'mount_point': None}
    points = _linux_mount_points() if mount_points is None else mount_points
    return qualification_durability(Path(raw_data), Path(raw_root), points)


def model_configured(environ: dict | None = None) -> bool:
    env = os.environ if environ is None else environ
    return any(str(env.get(name, '')).strip() for name in (
        'GEMINI_API_KEY',
        'OPENAI_API_KEY',
        'OPENROUTER_API_KEY',
        'SELF_HOSTED_AI_API_KEY',
    ))


def stable_endpoint(environ: dict | None = None) -> bool:
    env = os.environ if environ is None else environ
    host = str(env.get('PERSONAL_AI_QUALIFICATION_PUBLIC_HOST', '')).strip().lower()
    if not host or 'trycloudflare.com' in host or host == PRODUCTION_HOST:
        return False
    return True
