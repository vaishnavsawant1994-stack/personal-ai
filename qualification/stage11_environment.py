"""Checks for a separate Stage 11 qualification process.

Does not start a server and does not write a Stage 11 result.
"""

from __future__ import annotations

from pathlib import Path

from qualification.stage11_identity import PRODUCTION_HOST, QUALIFICATION, SHA

DEFAULT_DATA_NAME = '.stage11-qualification-data'


def assert_separate_from_production(host: str) -> None:
    name = host.split(',')[0].strip().split('://')[-1].split('/')[0].lower()
    if name.startswith('['):
        name = name.split(']')[0].strip('[')
    elif name.count(':') == 1:
        name = name.split(':', 1)[0]
    if name == PRODUCTION_HOST:
        raise ValueError('refusing_production_host')


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
