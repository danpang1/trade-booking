#!/usr/bin/env bash
# tokka-mo end-to-end smoke against an MO environment.
# Usage:
#   ./smoke.sh --base-url https://test-jp-tms.internal.tokkalabs.com --username <u> --password <p>
# (UAT URL; both UAT and PROD require Tokka VPN.)

set -e

BASE_URL=""
USERNAME=""
PASSWORD=""

while [ $# -gt 0 ]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    --username) USERNAME="$2"; shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$BASE_URL" ] || [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
  echo "usage: ./smoke.sh --base-url URL --username USER --password PASS" >&2
  exit 2
fi

TOKKA_MO="$(cd "$(dirname "$0")" && pwd)/bin/tokka-mo"
[ -x "$TOKKA_MO" ] || chmod +x "$TOKKA_MO"

fail() { echo "FAIL $1: $2" >&2; exit 1; }
ok()   { echo "ok   $1"; }

# 1. Login (two lines on stdin: username, password)
printf '%s\n%s\n' "$USERNAME" "$PASSWORD" \
  | $TOKKA_MO --api-url "$BASE_URL" login --non-interactive >/dev/null \
  || fail "login" "auth failed (check creds + URL)"
ok "login"

# 2. whoami
out=$($TOKKA_MO whoami) || fail "whoami" "$out"
ok "whoami: $out"

# 3. refdata refresh
out=$($TOKKA_MO refdata refresh) || fail "refdata refresh" "$out"
ok "refdata refresh: $out"

# 4. single book
TS=$(date -u +"%Y-%m-%dT%H:%M:%S+00:00")
cat <<EOF | $TOKKA_MO book > /tmp/single_out.txt || fail "single book" "$(cat /tmp/single_out.txt)"
{
  "cashflow_type": "OPEX",
  "direction": "OUTGOING",
  "entity": "TOKKA LABS PTE LTD",
  "portfolio_id": 8006,
  "portfolio_name": "CDA",
  "counterparty": "TOKKA TREASURY",
  "account": "TOKKA TREASURY WALLET",
  "account_type": "WALLET",
  "asset": "USDC",
  "amount": "1",
  "trade_date": "${TS}",
  "value_date": "${TS}",
  "user_id": "${USERNAME}",
  "status": "PENDING"
}
EOF
SINGLE_ID=$(grep -oE 'Draft #[0-9]+' /tmp/single_out.txt | head -1 | tr -dc 0-9)
[ -n "$SINGLE_ID" ] || fail "single book" "no draft id in output"
ok "single book -> draft #${SINGLE_ID}"

# 5. batch book (2 rows)
cat <<EOF | $TOKKA_MO book-batch > /tmp/batch_out.txt || fail "batch book" "$(cat /tmp/batch_out.txt)"
{"trades":[
 {"payload":{"cashflow_type":"OPEX","direction":"OUTGOING","entity":"TOKKA LABS PTE LTD","portfolio_id":8006,"portfolio_name":"CDA","counterparty":"TOKKA TREASURY","account":"TOKKA TREASURY WALLET","account_type":"WALLET","asset":"USDC","amount":"2","trade_date":"${TS}","value_date":"${TS}","user_id":"${USERNAME}","status":"PENDING"}},
 {"payload":{"cashflow_type":"OPEX","direction":"OUTGOING","entity":"TOKKA LABS PTE LTD","portfolio_id":8006,"portfolio_name":"CDA","counterparty":"TOKKA TREASURY","account":"TOKKA TREASURY WALLET","account_type":"WALLET","asset":"USDC","amount":"3","trade_date":"${TS}","value_date":"${TS}","user_id":"${USERNAME}","status":"PENDING"}}
]}
EOF
BATCH_OUT=$(cat /tmp/batch_out.txt)
[[ "$BATCH_OUT" == *"2 drafts created"* ]] || fail "batch book" "$BATCH_OUT"
ok "batch book: $BATCH_OUT"

# 6. drafts list
out=$($TOKKA_MO drafts list --status PENDING_REVIEW) || fail "drafts list" "$out"
[ -n "$out" ] || fail "drafts list" "empty output"
ok "drafts list (PENDING_REVIEW shown)"

# 7. logout
$TOKKA_MO logout >/dev/null || fail "logout" "(see stderr)"
ok "logout"

echo
echo "PASS"
echo
echo "Test drafts on ${BASE_URL}:"
echo "  - single: #${SINGLE_ID}"
echo "  - batch:  $(echo "$BATCH_OUT" | grep -oE '#[0-9]+' | tr '\n' ' ')"
echo "Reject them in the /pending UI to keep UAT clean."
