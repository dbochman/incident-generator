#!/usr/bin/env bash
set -euo pipefail

HOSTNAME="${1:?hostname is required}"
NAMESPACE="${2:-default}"
SERVICE="${3:-}"
PROBE_NAME="${4:-sre-agent-dns-tls-probe}"
PORT="${5:-443}"

command -v kubectl >/dev/null 2>&1 || { echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=kubectl_missing"; exit 0; }
command -v openssl >/dev/null 2>&1 || { echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=openssl_missing"; exit 0; }

if [[ -z "$SERVICE" ]]; then
  echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=service_missing"
  exit 0
fi
if ! kubectl -n "$NAMESPACE" get pod "$PROBE_NAME" >/dev/null 2>&1; then
  echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=probe_unavailable"
  exit 0
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
TARGET="${SERVICE}.${NAMESPACE}.svc.cluster.local:${PORT}"

kubectl -n "$NAMESPACE" exec "$PROBE_NAME" -- sh -lc \
  "echo | timeout 8 openssl s_client -connect '$TARGET' -servername '$HOSTNAME' -showcerts 2>/dev/null" \
  > "$TMP_DIR/s_client.out" 2>"$TMP_DIR/kubectl.err" || true

sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' "$TMP_DIR/s_client.out" > "$TMP_DIR/tls.crt"
if [[ ! -s "$TMP_DIR/tls.crt" ]]; then
  echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=no_certificate"
  exit 0
fi

SUBJECT="$(openssl x509 -in "$TMP_DIR/tls.crt" -noout -subject -nameopt RFC2253 | sed 's/^subject=//')"
ISSUER="$(openssl x509 -in "$TMP_DIR/tls.crt" -noout -issuer -nameopt RFC2253 | sed 's/^issuer=//')"
NOT_AFTER_RAW="$(openssl x509 -in "$TMP_DIR/tls.crt" -noout -enddate | sed 's/^notAfter=//')"
NOT_AFTER_EPOCH="$(date -u -d "$NOT_AFTER_RAW" +%s 2>/dev/null || echo 0)"
NOW_EPOCH="$(date -u +%s)"
DAYS_REMAINING=$(( (NOT_AFTER_EPOCH - NOW_EPOCH) / 86400 ))
SAN_TEXT="$(openssl x509 -in "$TMP_DIR/tls.crt" -noout -ext subjectAltName 2>/dev/null | tr '\n' ' ')"

HOSTNAME_MATCH=false
if [[ "$SAN_TEXT" == *"DNS:${HOSTNAME}"* || "$SUBJECT" == "CN=${HOSTNAME}" || "$SUBJECT" == *",CN=${HOSTNAME}"* ]]; then
  HOSTNAME_MATCH=true
fi

VALID=false
if [[ "$DAYS_REMAINING" -ge 0 && "$HOSTNAME_MATCH" == "true" ]]; then
  VALID=true
fi

ERROR="none"
if [[ "$DAYS_REMAINING" -lt 0 ]]; then
  ERROR="certificate_expired"
elif [[ "$HOSTNAME_MATCH" != "true" ]]; then
  ERROR="hostname_mismatch"
fi

printf 'valid=%s days_remaining=%s subject=%s issuer=%s hostname_match=%s not_after_epoch=%s error=%s\n' \
  "$VALID" "$DAYS_REMAINING" "$SUBJECT" "$ISSUER" "$HOSTNAME_MATCH" "$NOT_AFTER_EPOCH" "$ERROR"
