#!/bin/sh
# Fetch Docker Hub images before the build needs them: Google's mirror first, then Docker Hub,
# retrying with growing pauses. Each image ends up under its usual name in the local image
# store, so later steps use it without contacting Docker Hub. Usage: pull-retry.sh IMAGE...
set -u
for img in "$@"; do
  case "$img" in */*) path="$img" ;; *) path="library/$img" ;; esac
  for attempt in 1 2 3 4 5; do
    if docker pull -q "mirror.gcr.io/$path" && docker tag "mirror.gcr.io/$path" "$img"; then
      break
    fi
    if docker pull -q "$img"; then
      break
    fi
    if [ "$attempt" = 5 ]; then
      echo "Could not fetch $img from the mirror or Docker Hub" >&2
      exit 1
    fi
    echo "Fetching $img failed (attempt $attempt); retrying in $((attempt * 20)) s" >&2
    sleep $((attempt * 20))
  done
done
