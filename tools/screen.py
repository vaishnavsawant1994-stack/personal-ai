from tools.registry import Tool, Risk


def register(reg, data_dir):
    def legacy_screenshot_disabled(_params):
        raise PermissionError(
            'legacy raw screenshot capture is disabled; use governed computer_observe evidence'
        )

    # Compatibility name only. Raw monitor capture must not bypass the Stage-7
    # observation/redaction/evidence authority.
    reg.register(Tool(
        'screenshot',
        'Legacy raw screenshot capture (disabled)',
        legacy_screenshot_disabled,
        Risk.READ_ONLY,
        prohibited=True,
    ))
