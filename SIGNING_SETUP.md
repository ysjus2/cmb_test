# Android fixed signing setup

This repository builds the installable Android release APK with a fixed signing key.

Required GitHub Actions repository secrets:

- ANDROID_KEYSTORE_BASE64
- ANDROID_KEYSTORE_PASSWORD
- ANDROID_KEY_ALIAS
- ANDROID_KEY_PASSWORD
- KAKAO_NATIVE_APP_KEY

The signing keystore itself must never be committed to this public repository.

Workflow:
- .github/workflows/build-apk.yml
- Build task: :app:assembleRelease
- Artifact: CAD-Network-signed-release-apk
- APK: app/build/outputs/apk/release/app-release.apk

After the four ANDROID_* secrets are configured once, future builds use the same signing identity and can be installed as updates over the previous fixed-signed build.
