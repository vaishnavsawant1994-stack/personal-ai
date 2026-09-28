from types import SimpleNamespace
from tools.registry import ToolRegistry,Tool,Risk
from tools import browser as legacy_browser_tools
from tools import advanced_control, files as legacy_files, screen as legacy_screen, web

def test_ask_mode():
    r=ToolRegistry(SimpleNamespace(autonomy_mode="ask")); assert r.automatic(Tool("r","",lambda p:None,Risk.READ_ONLY)); assert not r.automatic(Tool("w","",lambda p:None,Risk.REVERSIBLE))

def test_emergency_stop_persists_and_blocks_all_tools(tmp_path):
    settings=SimpleNamespace(autonomy_mode='act',data_dir=tmp_path);tool=Tool('read','',lambda p:True,Risk.READ_ONLY)
    first=ToolRegistry(settings);assert first.authorize(tool).allowed
    first.set_emergency_stop(True);assert not first.authorize(tool,confirmed=True).allowed
    restarted=ToolRegistry(settings);assert restarted.emergency_stop is True
    restarted.set_emergency_stop(False);assert ToolRegistry(settings).authorize(tool).allowed


def test_stage8_open_url_rejects_unsafe_schemes(tmp_path):
    reg = ToolRegistry(SimpleNamespace(autonomy_mode='ask', data_dir=tmp_path))
    web.register(reg)
    handler = reg.get('open_url').handler
    for value in ('javascript:alert(1)', 'file:///etc/passwd', 'data:text/html,boom', 'https://user:pw@example.com/'):
        try:
            handler({'url': value})
            assert False, value
        except ValueError:
            pass


def test_stage8_legacy_browser_and_desktop_authorities_are_compatibility_disabled(tmp_path):
    reg = ToolRegistry(SimpleNamespace(autonomy_mode='ask', data_dir=tmp_path, browser_headless=True))
    legacy_browser_tools.register(reg)
    advanced_control.register(reg, SimpleNamespace(data_dir=tmp_path, browser_headless=True))
    legacy_names = {
        'browser_navigate','browser_extract_text','browser_click_text',
        'browser_goto','browser_snapshot','browser_click','browser_fill','browser_verify',
        'desktop_position','desktop_move','desktop_click','desktop_type','desktop_hotkey',
    }
    for name in legacy_names:
        tool = reg.get(name)
        assert tool.prohibited is True
        assert reg.authorize(tool, confirmed=True).allowed is False
        try:
            tool.handler({})
            assert False, name
        except PermissionError:
            pass


def test_stage8_legacy_file_mutations_are_disabled(tmp_path):
    reg = ToolRegistry(SimpleNamespace(autonomy_mode='ask', data_dir=tmp_path, file_roots=(str(tmp_path),)))
    legacy_files.register(reg, SimpleNamespace(data_dir=tmp_path, file_roots=(str(tmp_path),)))
    assert reg.get('read_file').prohibited is False
    for name in ('write_file', 'overwrite_file', 'copy_file'):
        tool = reg.get(name)
        assert tool.prohibited is True
        assert reg.authorize(tool, confirmed=True).allowed is False
        try:
            tool.handler({})
            assert False, name
        except PermissionError:
            pass


def test_stage8_raw_screenshot_compatibility_path_is_disabled(tmp_path):
    reg = ToolRegistry(SimpleNamespace(autonomy_mode='ask', data_dir=tmp_path))
    legacy_screen.register(reg, tmp_path)
    tool = reg.get('screenshot')
    assert tool.prohibited is True
    assert reg.authorize(tool, confirmed=True).allowed is False
    try:
        tool.handler({'path': str(tmp_path / 'leak.png')})
        assert False, 'legacy raw screenshot must not execute'
    except PermissionError:
        pass
    assert not (tmp_path / 'leak.png').exists()
