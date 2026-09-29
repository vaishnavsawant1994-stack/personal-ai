"""The waiting note must not open Stage 12 or pass a physical row."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pre_physical_note_keeps_the_gates_closed():
    waiting = (ROOT / 'docs' / 'PRE_PHYSICAL_WAITING.md').read_text(encoding='utf-8')
    prep = (ROOT / 'docs' / 'STAGE12_PREPARATION.md').read_text(encoding='utf-8')
    assert '08b2616c11d1433760eb711db4ca7f82e5a01a2c' in waiting
    assert 'not a Stage 11 freeze' in waiting
    assert 'Stage 12 is not open' in prep
    assert 'NOT RUN' in prep
    assert 'not deployed' in prep or 'does not have that host' in prep
    register = json.loads((ROOT / 'docs' / 'stage11_register.json').read_text(encoding='utf-8'))
    assert register['frozen'] is False
    assert register['production_ready'] is False
    assert all(row['status'].startswith('PENDING_') and row['actual'] is None for row in register['cases'])
