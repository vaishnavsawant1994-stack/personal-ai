from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLOUD_URL = "https://personal-ai-runtime-production.up.railway.app/iphone/"


def test_android_release_surface_uses_secure_cloud_and_custom_tabs():
    activity = (
        ROOT
        / "android-companion/app/src/main/java/ai/personal/companion/MainActivity.kt"
    ).read_text()
    gradle = (ROOT / "android-companion/app/build.gradle.kts").read_text()
    assert CLOUD_URL in activity
    assert "CustomTabsIntent" in activity
    assert "androidx.browser:browser" in gradle
    assert "WebView" not in activity


def test_android_workflow_retains_installable_apk():
    workflow = (ROOT / ".github/workflows/android.yml").read_text()
    assert "app-debug.apk" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "SHA256SUMS.txt" in workflow


def test_windows_and_ios_offer_same_cloud_surface():
    desktop = (ROOT / "ui/main_window.py").read_text()
    ios = (
        ROOT / "ios-companion/PersonalAICompanion/PersonalAICompanionApp.swift"
    ).read_text()
    assert CLOUD_URL in desktop
    assert "QDesktopServices.openUrl" in desktop
    assert CLOUD_URL in ios
    assert "Link(destination:" in ios


def test_ios_ci_builds_unsigned_artifact_without_claiming_distribution():
    workflow = (ROOT / ".github/workflows/ios.yml").read_text()
    assert "CODE_SIGNING_ALLOWED=NO" in workflow
    assert "personal-ai-iOS-unsigned-simulator" in workflow
