// Download links for the apps, always the newest release (.github/workflows/release.yml).
const LATEST = "https://github.com/jc-universe87/locuvi/releases/latest/download";
export const DOWNLOADS = {
  windows: `${LATEST}/Locuvi-Windows-Setup.exe`,
  mac: `${LATEST}/Locuvi-macOS.dmg`,
  android: `${LATEST}/Locuvi-Android.apk`,
  // the phone build, published by .github/workflows/ci.yml (open in Safari, Add to Home Screen)
  iphone: "https://jc-universe87.github.io/locuvi/",
};
export const APPS_GUIDE = "https://github.com/jc-universe87/locuvi/blob/main/docs/APPS.md";
