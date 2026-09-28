from tools.registry import Tool, Risk


def _disabled(_params):
    raise PermissionError('legacy browser controller is disabled; use the governed browser/computer authority')


def register(reg):
    # Compatibility-only names retained for old metadata. These legacy tools
    # must never provide a parallel execution path beside the governed W7
    # operator/runtime.
    reg.register(Tool(
        "browser_navigate", "Legacy browser navigation (disabled)", _disabled,
        Risk.EXTERNAL_SIDE_EFFECT, prohibited=True,
    ))
    reg.register(Tool(
        "browser_extract_text", "Legacy browser extraction (disabled)", _disabled,
        Risk.READ_ONLY, prohibited=True,
    ))
    reg.register(Tool(
        "browser_click_text", "Legacy browser click (disabled)", _disabled,
        Risk.EXTERNAL_SIDE_EFFECT, prohibited=True,
    ))
