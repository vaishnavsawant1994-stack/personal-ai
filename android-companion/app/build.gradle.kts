plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace="ai.personal.companion"; compileSdk=35
    defaultConfig { applicationId="ai.personal.companion"; minSdk=26; targetSdk=35; versionCode=1; versionName="0.5.0"; testInstrumentationRunner="androidx.test.runner.AndroidJUnitRunner" }
    compileOptions { sourceCompatibility=JavaVersion.VERSION_17; targetCompatibility=JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget="17" }
}
dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:core-ktx:1.7.0")
}
