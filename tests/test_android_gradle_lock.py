from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_android_app_locks_transitive_dependencies():
    gradle = (ROOT / "android-companion/app/build.gradle.kts").read_text(encoding="utf-8")
    lock = (ROOT / "android-companion/app/gradle.lockfile").read_text(encoding="utf-8")
    assert "lockAllConfigurations()" in gradle
    assert "com.squareup.okio" not in gradle
    assert "com.squareup.okhttp3:okhttp:4.12.0=" in lock
    assert "com.squareup.okio:okio:3.6.0=" in lock
    assert "\nempty=" in lock
