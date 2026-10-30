# NEOCARE Android app

This Android 8.0+ application opens the existing NEOCARE service at
`https://umito.pythonanywhere.com/`. It uses the same cloud accounts and records
as the Firebase-hosted website. The direct API-host address gives Android
WebView first-party login cookies without relying on third-party cookies.
An internet connection and the existing backend are required; this app does not
run the Python server or local AI on the phone.

The interface retains the website's English/Arabic language selection, dark
mode, clinic/parent workflows, and report views. Report PDF downloads use the
Android save dialog, and the report print button opens Android's print service.
The native PDF bridge accepts only the configured HTTPS origin and main frame,
limits reports to 8 MiB, and never chooses a storage path itself. The app requests
only Internet permission. It does not bundle credentials or patient data.

A report awaiting the system save dialog is held temporarily in the app's private
cache, so Android can recreate the screen without losing the export. Only an
opaque file identifier is kept in saved instance state. The temporary report is
deleted after saving, cancellation, or normal activity completion. Abandoned
exports older than 24 hours are removed on the next app launch; the currently
restored export is preserved until its save dialog returns.

## Build

The repository's **Actions > Build Android APK > Run workflow** builds the app,
runs unit tests and Android 16 emulator checks, and uploads a signed APK artifact.
The workflow uses standard public-repository runners and the encrypted
`NEOCARE_ANDROID_KEYSTORE_BASE64`, `NEOCARE_ANDROID_KEYSTORE_PASSWORD`,
`NEOCARE_ANDROID_KEY_ALIAS`, and `NEOCARE_ANDROID_KEY_PASSWORD` repository secrets.
It does not publish a release automatically.

Use JDK 17, Android SDK 36 and the checked-in Gradle 8.13 wrapper:

```sh
./gradlew testDebugUnitTest lintRelease assembleRelease
```

On Windows, use `gradlew.bat`. Set `ANDROID_HOME` or a private `local.properties`
file to your SDK directory. Release signing reads these environment variables:

```text
NEOCARE_KEYSTORE_PATH
NEOCARE_KEYSTORE_PASSWORD
NEOCARE_KEY_ALIAS
NEOCARE_KEY_PASSWORD
```

Keep the signing keystore and passwords private and backed up. Future APK updates
must use the same signing key and a higher versionCode. Configure all four signing
variables before building a release. For a local development build without the
release key, run `./gradlew testDebugUnitTest assembleDebug`.
The published APK is release-signed.

The initial private signing backup is kept locally in
`deployment-artifacts/android-signing/`. Back up that directory securely;
never put it in a public repository or attach it to a release.

## Install

Download the APK from this repository's GitHub Releases page. Open it on the
Android device and allow installation from that downloader/browser if Android
asks. No Play Store account or paid domain is required. Sign in using an existing
cloud account; laptop-only accounts are separate until migrated.

Keep Android System WebView or Chrome updated. When required report APIs are
unavailable, the app offers the website in the browser. The backend's existing
hosting capacity, renewal requirements and feature availability still apply.
