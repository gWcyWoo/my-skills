plugins {
    id("com.android.application")
}

android {
    namespace = "dev.icp.visualgate"
    compileSdk = 37

    defaultConfig {
        applicationId = "dev.icp.visualgate"
        minSdk = 24
        targetSdk = 28
        versionCode = 1
        versionName = "1.0"
    }
}
