#!/usr/bin/env bash
# Live E2E verification on paperclip (run inside VM or via ssh).
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8001}"
IMG_A="${1:-/tmp/e2e_heavy_unique}"
IMG_B="${2:-/tmp/e2e_partb}"
COOKIE=/tmp/e2e_cookies.txt
ADMIN_PASS="${ADMIN_PASS:?set ADMIN_PASS}"

rm -f "$COOKIE"

login() {
  curl -sS -c "$COOKIE" -b "$COOKIE" "$BASE/login" >/dev/null
  curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/auth/login" \
    -d "username=admin&password=$ADMIN_PASS" -o /dev/null -w "login HTTP %{http_code}\n"
}

submit_claim() {
  local tag="$1" dir="$2"
  local args=()
  for f in "$dir"/*.jpg; do
    args+=(-F "images=@$f")
  done
  curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/claims" \
    "${args[@]}" \
    -F "garage_name=E2E $tag" \
    -F "surveyor_name=E2E $tag"
}

wait_status() {
  local cid="$1" want="$2" max="${3:-600}"
  local i=0
  while [ "$i" -lt "$max" ]; do
    st=$(docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -tAc "SELECT status FROM claims WHERE id=$cid;")
    if [ "$st" = "$want" ]; then
      echo "claim $cid status=$st (after ${i}s)"
      return 0
    fi
    sleep 3
    i=$((i + 3))
  done
  st=$(docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -tAc "SELECT status FROM claims WHERE id=$cid;")
  echo "TIMEOUT claim $cid wanted=$want got=$st"
  return 1
}

sse_capture() {
  local cid="$1" out="$2" max="${3:-120}"
  timeout "$max" curl -sS -N -c "$COOKIE" -b "$COOKIE" \
    "$BASE/api/pipeline/$cid/stream" >"$out" 2>/dev/null || true
  echo "SSE bytes: $(wc -c <"$out") events: $(grep -c '^data:' "$out" || true)"
}

echo "=== E2E Part A + C ==="
login
RESP=$(submit_claim "live-a" "$IMG_A")
CID=$(python3 -c "import json,sys; print(json.load(sys.stdin)['claim_id'])" <<<"$RESP")
REF=$(python3 -c "import json,sys; print(json.load(sys.stdin)['claim_reference'])" <<<"$RESP")
echo "Submitted claim $CID ($REF)"

sleep 2
HTML=$(curl -sS -c "$COOKIE" -b "$COOKIE" "$BASE/claims/$CID/processing")
STAGES_LEN=$(python3 -c "
import re,json,sys
m=re.search(r'pipeline-bootstrap\">(\{.*?\})</script>', sys.stdin.read(), re.S)
print(len(json.loads(m.group(1)).get('stages') or []))
" <<<"$HTML")
echo "Part C early bootstrap stages count: $STAGES_LEN"

SSE_FILE=/tmp/sse_a.txt
(sleep 1; sse_capture "$CID" "$SSE_FILE" 480) &
SSE_PID=$!

wait_status "$CID" "paused_awaiting_vehicle_confirmation" 480 || true
kill "$SSE_PID" 2>/dev/null || true
wait "$SSE_PID" 2>/dev/null || true

grep -q awaiting_vehicle_confirmation "$SSE_FILE" && echo "Part A SSE: awaiting_vehicle_confirmation seen" || echo "Part A SSE: pause flag NOT in stream"
grep -c vehicle_confirmation "$SSE_FILE" | xargs -I{} echo "Part A SSE vehicle_confirmation mentions: {}"

HTML=$(curl -sS -c "$COOKIE" -b "$COOKIE" "$BASE/claims/$CID/processing")
echo "$HTML" | grep -q 'id="confirm_make"' && echo "Part A inline confirm form: YES" || echo "Part A inline confirm form: NO"
echo "$HTML" | grep -q 'Confirm vehicle</p>' && echo "Part A separate banner: STILL PRESENT" || echo "Part A separate banner: removed OK"

ST=$(docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -tAc "SELECT status FROM claims WHERE id=$CID;")
if [ "$ST" != "paused_awaiting_vehicle_confirmation" ]; then
  echo "FAIL Part A: status=$ST"
  docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -c "SELECT stage_key,status,left(detail,80) FROM pipeline_events WHERE claim_id=$CID ORDER BY id;"
  exit 2
fi

# Resume stages before pause
docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -c "SELECT stage_key,status FROM pipeline_events WHERE claim_id=$CID ORDER BY id;"

curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/api/pipeline/$CID/confirm-vehicle" \
  -H 'Content-Type: application/json' \
  -d '{"make":"Toyota","model":"Innova"}' | python3 -m json.tool

SSE_FILE2=/tmp/sse_a2.txt
(sleep 1; sse_capture "$CID" "$SSE_FILE2" 480) &
SSE2=$!
wait_status "$CID" "estimate_ready" 480
kill "$SSE2" 2>/dev/null || true

echo "Part A resume SSE tail:"
tail -5 "$SSE_FILE2"
echo "Part A post-resume stages (should include fraud/parts/estimate, no second intake):"
docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -tAc \
  "SELECT stage_key,status FROM pipeline_events WHERE claim_id=$CID ORDER BY id;" | tr '\n' ' '
echo

echo "Part A vehicle identity:"
docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -c \
  "SELECT make,model,identity_confirmed,pricing_basis,identity_source FROM vehicles WHERE source_claim_id=$CID;"

echo "Part A correction queue:"
docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -c \
  "SELECT id,claim_id,confirmed_make,confirmed_model,used_in_training,array_length(scratch_image_paths,1) FROM vmmr_correction_queue WHERE claim_id=$CID;"
echo "Part A scratch files:"
docker exec ai_tribe_app_ml ls -la "/mnt/ml-scratch/vmmr_corrections/$CID/" 2>&1 || echo "scratch dir missing"

echo "=== E2E Part B ==="
login
RESPB=$(submit_claim "live-b" "$IMG_B")
BID=$(python3 -c "import json,sys; print(json.load(sys.stdin)['claim_id'])" <<<"$RESPB")
echo "Submitted claim $BID"
wait_status "$BID" "paused_awaiting_vehicle_confirmation" 480
curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/api/pipeline/$BID/confirm-vehicle" \
  -H 'Content-Type: application/json' \
  -d '{"make":"E2ETest","model":"NoCatalogVehicle"}' >/dev/null
wait_status "$BID" "estimate_ready" 480

EST=$(curl -sS -c "$COOKIE" -b "$COOKIE" "$BASE/claims/$BID/estimate")
echo "$EST" | grep -q 'placeholder="Enter ₹"' && echo "Part B unpriced inputs: YES" || echo "Part B unpriced inputs: NO"
echo "$EST" | grep -q 'Enter prices below' && echo "Part B locked total: YES" || echo "Part B locked total: NO"

curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/api/claims/$BID/estimate/prices" \
  -H 'Content-Type: application/json' \
  -d '{"prices":[{"part_name":"Front Bumper","damage_type":"dent","unit_price":8500},{"part_name":"Windshield","damage_type":"glass_shatter","unit_price":12000}]}' \
  | python3 -m json.tool | head -20

EST2=$(curl -sS -c "$COOKIE" -b "$COOKIE" "$BASE/claims/$BID/estimate")
echo "$EST2" | grep -q '(manual)' && echo "Part B (manual) label: YES" || echo "Part B (manual) label: NO"
echo "$EST2" | grep -oP 'Grand total|Enter prices below|Total pending' | head -3

echo "=== Co-located stacks ==="
docker ps --filter name=paperclip --format "{{.Names}} {{.Status}}"
docker ps --filter name=twcto --format "{{.Names}} {{.Status}}" | head -4

echo "=== DONE ==="
