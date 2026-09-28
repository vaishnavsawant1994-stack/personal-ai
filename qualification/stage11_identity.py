"""Public identity for a Stage 11 qualification process.

This is not a pass, not a freeze, and not production.
"""

from __future__ import annotations

import os
import re

SHA = re.compile(r'^[0-9a-f]{40}$')
QUALIFICATION = 'stage11-qualification'
RECOVERY_CHECKPOINT = 'b22fbb58179aa3f1974ded4cb4c881f92f972d31'
STAGE8_FREEZE = 'b17c5051772b5e82b7a6a208903bb0300bf1e405'
STAGE9_FREEZE = 'ddd53d17d60db2e5e5438cf29e2d704a9ba69af0'
STAGE10_FREEZE = 'cd558936276aece705fa46032e3bab6453c7f014'
PRODUCTION_HOST = 'personal-ai-runtime-production.up.railway.app'

_CLOSED = {
    'ok': False,
    'production': False,
    'stage11_freeze': False,
    'stage12_open': False,
    'source_sha': None,
    'rows_passed': 0,
}


def public_identity() -> tuple[dict, int]:
    environment = os.getenv('PERSONAL_AI_ENVIRONMENT', '').strip()
    production_flag = os.getenv('PERSONAL_AI_PRODUCTION', '').strip().lower()
    if production_flag in {'1', 'true', 'yes'} or environment in {'production', 'prod'}:
        return {**_CLOSED, 'error': 'production_is_not_a_stage11_environment'}, 404
    if environment != QUALIFICATION:
        return {**_CLOSED, 'error': 'not_stage11_qualification', 'environment': environment or 'unset'}, 404
    source_sha = os.getenv('PERSONAL_AI_SOURCE_SHA', '').strip().lower()
    if not SHA.fullmatch(source_sha):
        return {**_CLOSED, 'error': 'source_sha_not_exact', 'environment': QUALIFICATION}, 503
    return {
        'ok': True,
        'environment': QUALIFICATION,
        'production': False,
        'stage11_freeze': False,
        'stage12_open': False,
        'source_sha': source_sha,
        'recovery_checkpoint': RECOVERY_CHECKPOINT,
        'stage8_freeze': STAGE8_FREEZE,
        'stage9_freeze': STAGE9_FREEZE,
        'stage10_freeze': STAGE10_FREEZE,
        'pwa_path': '/iphone/',
        'public_p2_is_this_environment': False,
        'rows_passed': 0,
        'candidate_only': True,
    }, 200
