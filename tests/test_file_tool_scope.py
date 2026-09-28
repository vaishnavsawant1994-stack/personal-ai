from types import SimpleNamespace

import pytest

from tools.files import register
from tools.registry import Risk, ToolRegistry


def test_legacy_file_mutations_are_disabled_and_reads_remain_confined(tmp_path):
    root = tmp_path / 'approved'
    root.mkdir()
    (root / 'note.txt').write_text('one')
    registry = ToolRegistry(SimpleNamespace(autonomy_mode='ask'))
    register(registry, SimpleNamespace(file_roots=(root,), data_dir=tmp_path))

    assert registry.get('read_file').handler({'path': str(root / 'note.txt')}) == 'one'
    for name in ('write_file', 'overwrite_file', 'copy_file'):
        tool = registry.get(name)
        assert tool.prohibited is True
        assert registry.authorize(tool, confirmed=True).allowed is False
        with pytest.raises(PermissionError):
            tool.handler({})

    with pytest.raises(PermissionError):
        registry.get('read_file').handler({'path': str(tmp_path / 'outside.txt')})

def test_file_tools_hide_secret_bearing_paths(tmp_path):
    root = tmp_path / 'approved'
    root.mkdir()
    (root / '.env').write_text('SECRET=value')
    registry = ToolRegistry(SimpleNamespace(autonomy_mode='ask'))
    register(registry, SimpleNamespace(file_roots=(root,), data_dir=tmp_path))

    assert '.env' not in {row['name'] for row in registry.get('list_dir').handler({'path': str(root)})}
    with pytest.raises(PermissionError):
        registry.get('read_file').handler({'path': str(root / '.env')})
