#!/usr/bin/env bash
# Feature 2 chat verification on paperclip (verification deploy, not production sign-off).
set -euo pipefail

cd /opt/stack/ai_tribe
ADMIN_PASS="${ADMIN_PASS:?set ADMIN_PASS}"
BASE="${BASE:-http://127.0.0.1:8001}"

echo "=== Prepare claim 26/34 images ==="
IMG_DIR=/tmp/e2e_chat_images
rm -rf "$IMG_DIR"
mkdir -p "$IMG_DIR"
# Prefer claim 26 images; fall back to 34
for CID in 26 34; do
  UPLOAD_ROOT=$(docker exec ai_tribe_app_ml python3 -c "from app.core.config import get_settings; print(get_settings().upload_path)" 2>/dev/null || echo "")
  if [ -n "$UPLOAD_ROOT" ]; then
  docker exec ai_tribe_app_ml bash -c "ls ${UPLOAD_ROOT}/${CID}/*.jpg 2>/dev/null | head -4" | while read -r f; do
    bn=$(basename "$f")
    docker cp "ai_tribe_app_ml:$f" "$IMG_DIR/$bn" 2>/dev/null || true
  done
  fi
  COUNT=$(ls -1 "$IMG_DIR"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
  if [ "${COUNT:-0}" -ge 2 ]; then
    echo "Using images from claim $CID ($COUNT files)"
    break
  fi
done
ls -la "$IMG_DIR" || true

echo "=== Run chat API verification ==="
export ADMIN_PASS
python3 scripts/e2e_verify_chat.py "$BASE" "$ADMIN_PASS" "$IMG_DIR" | tee /tmp/e2e_chat_verify.log

echo "=== Accident date DB check (latest chat claim) ==="
LAST_ID=$(docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -tAc \
  "SELECT id FROM claims WHERE garage_id IN (SELECT id FROM garages WHERE name ILIKE '%Chat E2E%') ORDER BY id DESC LIMIT 1;")
echo "Latest Chat E2E claim id: $LAST_ID"
if [ -n "$LAST_ID" ]; then
  docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -c \
    "SELECT id, claim_reference, accident_date, status FROM claims WHERE id=$LAST_ID;"
fi

echo "=== created_by isolation (DB + API) ==="
docker exec ai_tribe_db psql -U ai_tribe -d ai_tribe -c \
  "SELECT c.id, c.claim_reference, c.created_by, u.username FROM claims c JOIN users u ON u.id=c.created_by ORDER BY c.id DESC LIMIT 8;"

echo "=== Draft restart test ==="
COOKIE=/tmp/chat_draft_cookie.txt
rm -f "$COOKIE"
curl -sS -c "$COOKIE" -b "$COOKIE" "$BASE/login" >/dev/null
curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/auth/login" -d "username=admin&password=$ADMIN_PASS" -o /dev/null

curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/api/chat/message" \
  -H 'Content-Type: application/json' -d '{"text":"Submit a claim"}' | python3 -m json.tool | head -8

for f in "$IMG_DIR"/*.jpg; do
  [ -f "$f" ] || continue
  curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/api/chat/upload" -F "images=@$f" >/dev/null
  break
done

curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/api/chat/message" \
  -H 'Content-Type: application/json' -d '{"text":"garage is Draft Restart Test Garage"}' | python3 -m json.tool | head -10

echo "Restarting ai_tribe_app_ml..."
docker restart ai_tribe_app_ml
sleep 25
curl -sS "$BASE/health" | python3 -m json.tool || true

echo "After restart — same session, say done:"
curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/api/chat/message" \
  -H 'Content-Type: application/json' -d '{"text":"done"}' | python3 -m json.tool

echo "After restart — fresh submit attempt:"
curl -sS -c "$COOKIE" -b "$COOKIE" -X POST "$BASE/api/chat/message" \
  -H 'Content-Type: application/json' -d '{"text":"Submit a claim"}' | python3 -m json.tool | head -8

echo "=== DONE ==="
