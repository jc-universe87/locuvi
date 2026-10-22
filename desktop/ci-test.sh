#!/usr/bin/env bash
# Checks a built desktop app (run by .github/workflows/release.yml on Windows and macOS).
#
#   desktop/ci-test.sh path/to/Locuvi(.exe) work-dir
#
# Starts it with fresh records and no windows, then runs desktop/selftest.py (signs in by
# itself, file types, desktop settings) and the full UI smoke test e2e/smoke.mjs against it.
# Needs Python, and Node with playwright + Chromium installed globally.
set -euo pipefail
APP=$1
WORK=$2
HERE=$(cd "$(dirname "$0")" && pwd)
rm -rf "$WORK" && mkdir -p "$WORK"
printf "e2e-pass" > "$WORK/pw"

"$APP" --headless --data-dir "$WORK/root" --password-file "$WORK/pw" \
  --info-file "$WORK/info.json" > "$WORK/app.out" 2>&1 &
PID=$!
stop() {
  kill "$PID" 2>/dev/null || true
  if command -v taskkill >/dev/null; then taskkill //F //IM Locuvi.exe >/dev/null 2>&1 || true; fi
}
trap stop EXIT

for _ in $(seq 120); do test -s "$WORK/info.json" && break; sleep 1; done
if ! test -s "$WORK/info.json"; then
  echo "FAIL Locuvi did not start"; cat "$WORK/app.out"; cat "$WORK/root/logs/"*.log 2>/dev/null || true
  exit 1
fi
cat "$WORK/info.json"; echo

python "$HERE/selftest.py" "$WORK/info.json"

URL=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['url'])" "$WORK/info.json")
NODE_PATH=$(npm root -g) BASE_URL=$URL LOCUVI_PASSWORD=e2e-pass SHOTS="$WORK/shots" \
  node "$HERE/../e2e/smoke.mjs"

if grep -i traceback "$WORK/root/logs/"*.log; then
  echo "FAIL errors in the log"; exit 1
fi
echo "PASS desktop app"
