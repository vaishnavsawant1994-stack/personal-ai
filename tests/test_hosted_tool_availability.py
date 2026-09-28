from types import SimpleNamespace

from memory.store import MemoryStore
from tools.builtins import register_builtin_tools
from tools.registry import ToolRegistry


def settings(tmp_path, hosted):
    return SimpleNamespace(
        autonomy_mode='ask', data_dir=tmp_path, file_roots=(tmp_path / 'files',),
        hosted_runtime=hosted, browser_headless=True,
    )


def test_hosted_runtime_does_not_advertise_physical_screen_tool(tmp_path):
    config = settings(tmp_path, True)
    registry = ToolRegistry(config)
    register_builtin_tools(registry, MemoryStore(tmp_path / 'memory.sqlite3'), config)
    assert 'screenshot' not in {tool.name for tool in registry.all()}


def test_desktop_runtime_keeps_physical_screen_tool(tmp_path):
    config = settings(tmp_path, False)
    registry = ToolRegistry(config)
    register_builtin_tools(registry, MemoryStore(tmp_path / 'memory.sqlite3'), config)
    assert 'screenshot' in {tool.name for tool in registry.all()}
