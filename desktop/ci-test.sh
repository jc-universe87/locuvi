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
MORE=()
stop() {
  kill "$PID" ${MORE[@]+"${MORE[@]}"} 2>/dev/null || true  # empty array: fine on the Mac's old bash too
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

# Sync: two copies of the app on this computer, both seeing a "Dropbox" folder (standing for
# any folder a cloud app keeps in step), set up through Settings like a person would.
H="$WORK/home"
mkdir -p "$H/Dropbox"
for n in laptop phone; do
  printf "e2e-pass" > "$WORK/pw-$n"
  HOME="$H" USERPROFILE="$H" "$APP" --headless --data-dir "$WORK/$n" --password-file "$WORK/pw-$n" \
    --info-file "$WORK/$n.json" > "$WORK/$n.out" 2>&1 &
  MORE+=("$!")
done
for _ in $(seq 120); do test -s "$WORK/laptop.json" && test -s "$WORK/phone.json" && break; sleep 1; done
open_link() { python -c "import json,sys; print(json.load(open(sys.argv[1]))['open'])" "$1"; }
NODE_PATH=$(npm root -g) OPEN_A=$(open_link "$WORK/laptop.json") OPEN_B=$(open_link "$WORK/phone.json") \
  SHOTS="$WORK/shots" node "$HERE/../e2e/sync.mjs"

if grep -i traceback "$WORK"/*/logs/*.log; then
  echo "FAIL errors in the log"; exit 1
fi
echo "PASS desktop app"
