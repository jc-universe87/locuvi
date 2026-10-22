#!/usr/bin/env bash
# Checks the built APK on an Android emulator (run by .github/workflows/release.yml).
#
#   emulator-test.sh Locuvi-Android.apk server-access.log out-dir
#
# A Locuvi is already running on the host at :8000 with its access log in server-access.log;
# the emulator reaches the host as 10.0.2.2. Passes when the app, opened with a connect link,
# loads Locuvi (page, scripts and the sign-in check reach the server) and, opened again from
# the launcher, still remembers the address.
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

if adb logcat -d | grep -E "FATAL EXCEPTION|AndroidRuntime: .*uk.locuvi" ; then
  echo "FAIL the app crashed"; exit 1
fi
echo "PASS no crashes"
