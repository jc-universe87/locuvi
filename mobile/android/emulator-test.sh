#!/usr/bin/env bash
# Checks the built APK on an Android emulator (run by .github/workflows/release.yml).
#
#   emulator-test.sh Locuvi-Android.apk server-access.log out-dir
#
# 1. Opened from the launcher, the app runs the whole of Locuvi on the phone (no server):
#    the engine starts and the web app reports it is ready.
# 2. A Locuvi is also running on the host at :8000 with its access log in server-access.log
#    (the emulator reaches the host as 10.0.2.2). Opened with a connect link, the app loads
#    that Locuvi instead, and opened again from the launcher, still remembers the address.
# 3. With TEST_APK (the same app as a test build, whose screens can be driven): the phone
#    joins sync through a stand-in Nextcloud on the host (:8791, no CORS, plain http:// as a
#    home network address) and a Locuvi on the "computer" (:8793), by e2e/pocket-sync.mjs.
set -euo pipefail
APK=$1
LOG=$2
OUT=$3
mkdir -p "$OUT"

wait_for() { # pattern, minimum count
  for _ in $(seq 90); do
    if [ "$(grep -c "$1" "$LOG" || true)" -ge "$2" ]; then return 0; fi
    sleep 2
  done
  echo "FAIL: '$1' did not reach the server $2 time(s)"; tail -30 "$LOG"; return 1
}

adb install -r "$APK"
served=$(grep -c 'GET /' "$LOG" || true)
adb logcat -c
adb shell monkey -p uk.locuvi.app -c android.intent.category.LAUNCHER 1 >/dev/null
for _ in $(seq 120); do
  if adb logcat -d -s Locuvi | grep -q "Locuvi is ready on this device"; then break; fi
  sleep 2
done
adb logcat -d -s Locuvi > "$OUT/phone-log.txt" || true
if ! grep -q "Locuvi is ready on this device" "$OUT/phone-log.txt"; then
  adb exec-out screencap -p > "$OUT/android-on-phone.png" || true
  adb logcat -d > "$OUT/logcat.txt" || true
  echo "FAIL Locuvi did not start on the phone"; tail -40 "$OUT/phone-log.txt"
  grep -iE "chromium|webview|console|locuvi|AndroidRuntime" "$OUT/logcat.txt" | tail -60
  adb shell dumpsys package com.google.android.webview | grep -m2 versionName || true
  exit 1
fi
grep -Eq "Locuvi [0-9.]+ started" "$OUT/phone-log.txt" || { echo "FAIL the engine did not report its start"; exit 1; }
sleep 4
adb exec-out screencap -p > "$OUT/android-on-phone.png"
if [ "$(grep -c 'GET /' "$LOG" || true)" -ne "$served" ]; then
  echo "FAIL the phone app reached the server, it should run on its own"; exit 1
fi
echo "PASS Locuvi runs on the phone by itself"

adb shell am force-stop uk.locuvi.app
adb shell am start -W -a android.intent.action.VIEW -d "locuvi://connect?server=10.0.2.2:8000" uk.locuvi.app
wait_for 'GET /assets/.*\.js' 1
wait_for 'GET /api/v1/auth/session' 1
sleep 5
adb exec-out screencap -p > "$OUT/android-connected.png"
adb shell uiautomator dump /sdcard/ui.xml >/dev/null && adb pull /sdcard/ui.xml "$OUT/ui.xml" >/dev/null || true
echo "PASS connect link opens Locuvi"

before=$(grep -c 'GET /api/v1/auth/session' "$LOG")
adb shell am force-stop uk.locuvi.app
adb shell monkey -p uk.locuvi.app -c android.intent.category.LAUNCHER 1 >/dev/null
wait_for 'GET /api/v1/auth/session' $((before + 1))
sleep 3
adb exec-out screencap -p > "$OUT/android-reopened.png"
echo "PASS reopening remembers the address"

if [ -n "${TEST_APK:-}" ]; then
  adb uninstall uk.locuvi.app >/dev/null
  adb install "$TEST_APK"
  adb shell monkey -p uk.locuvi.app -c android.intent.category.LAUNCHER 1 >/dev/null
  for _ in $(seq 120); do
    if adb logcat -d -s Locuvi | grep -q "Locuvi is ready on this device"; then break; fi
    sleep 2
  done
  HERE=$(cd "$(dirname "$0")" && pwd)
  # the usual address doesn't answer from here, so sync uses the home network one
  NODE_PATH=$(npm root -g) ANDROID=1 DESKTOP_URL=http://127.0.0.1:8793 NC_DESKTOP=http://127.0.0.1:8791 \
    NC_PHONE=https://nextcloud.example.invalid NC_PHONE_HOME=http://10.0.2.2:8791 SHOTS="$OUT" \
    node "$HERE/../../e2e/pocket-sync.mjs" || {
      adb exec-out screencap -p > "$OUT/android-sync-failed.png" || true
      adb logcat -d -s Locuvi | tail -40
      exit 1
    }
  echo "PASS the phone syncs through Nextcloud"
fi

if adb logcat -d | grep -E "FATAL EXCEPTION|AndroidRuntime: .*uk.locuvi" ; then
  echo "FAIL the app crashed"; exit 1
fi
echo "PASS no crashes"
