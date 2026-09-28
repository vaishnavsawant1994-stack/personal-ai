from pathlib import Path

RELEASE_VERSION = "0.6.0"


def test_release_version_is_consistent_across_build_targets():
    assert f'version = "{RELEASE_VERSION}"' in Path("pyproject.toml").read_text(encoding="utf-8")
    assert f"version='{RELEASE_VERSION}'" in Path("packaging/setup_cxfreeze.py").read_text(encoding="utf-8")
    assert f"Version=\"{RELEASE_VERSION}\"" in Path("packaging/PersonalAI.wxs").read_text(encoding="utf-8")
    assert f"PERSONAL_AI_VERSION','{RELEASE_VERSION}'" in Path("packaging/build_installer.py").read_text(encoding="utf-8")
    assert f"MARKETING_VERSION: {RELEASE_VERSION}" in Path("ios-companion/project.yml").read_text(encoding="utf-8")
    assert f'versionName="{RELEASE_VERSION}"' in Path("android-companion/app/build.gradle.kts").read_text(encoding="utf-8")


def test_google_drive_md5_is_explicitly_non_security_checksum():
    source = Path("integrations/google_write.py").read_text(encoding="utf-8")
    assert "hashlib.md5(data, usedforsecurity=False)" in source
