plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "io.github.serkenn.suicaviewer"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.serkenn.suicaviewer"
        minSdk = 26
        targetSdk = 35
        versionCode = 5
        versionName = "1.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    // Release signing is driven by environment variables so the keystore never
    // lives in the repo. On CI they come from GitHub Secrets; locally they are
    // absent, in which case the release build stays unsigned (debug builds are
    // unaffected and keep using the default debug keystore).
    val keystorePath = System.getenv("ANDROID_KEYSTORE_PATH")
    val releaseSigning = if (keystorePath != null) {
        signingConfigs.create("release") {
            storeFile = file(keystorePath)
            storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
            keyAlias = System.getenv("ANDROID_KEY_ALIAS")
            // The PKCS12 keystore uses a single password for the store and key.
            keyPassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
            storeType = "PKCS12"
        }
    } else {
        null
    }

    buildTypes {
        release {
            signingConfig = releaseSigning
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
    lint {
        // lintVitalRelease crashes inside AGP's bundled
        // NonNullableMutableLiveDataDetector (IncompatibleClassChangeError),
        // which is a lint bug, not a project issue. Skip lint during the
        // release assembly so the APK build is not blocked by it.
        checkReleaseBuilds = false
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.16.0")
    // Provides the Theme.Material3.* XML themes referenced by res/values/themes.xml.
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.2")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation(platform("androidx.compose:compose-bom:2025.06.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
