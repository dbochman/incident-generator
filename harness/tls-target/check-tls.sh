#!/usr/bin/env bash
set -euo pipefail

HOSTNAME="${1:?hostname is required}"
NAMESPACE="${2:-default}"
SERVICE="${3:-}"
PROBE_NAME="${4:-sre-agent-dns-tls-probe}"
PORT="${5:-443}"

command -v kubectl >/dev/null 2>&1 || { echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=kubectl_missing"; exit 0; }

if [[ -z "$SERVICE" ]]; then
  echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=service_missing"
  exit 0
fi
if ! kubectl -n "$NAMESPACE" get pod "$PROBE_NAME" >/dev/null 2>&1; then
  echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=probe_unavailable"
  exit 0
fi

# Run the entire openssl + cert-parsing pipeline INSIDE the probe pod so the
# host doesn't need GNU date / openssl / sed compatibility. The probe image
# (netshoot) ships GNU coreutils and openssl. Output is a single key=value
# line on stdout. If anything inside fails, the inner script still emits a
# structured error= line with a non-zero exit only on truly unexpected
# kubectl-side failures (which the predicate then surfaces).
TARGET="${SERVICE}.${NAMESPACE}.svc.cluster.local:${PORT}"

INNER_SCRIPT='
set -u
TARGET="$1"
HOSTNAME="$2"
TMP=$(mktemp -d)
trap "rm -rf \"$TMP\"" EXIT

if ! command -v openssl >/dev/null 2>&1; then
  echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=openssl_missing_in_probe"
  exit 0
fi

if ! echo | timeout 8 openssl s_client -connect "$TARGET" -servername "$HOSTNAME" -showcerts > "$TMP/s_client.out" 2> "$TMP/s_client.err"; then
  STDERR_HEAD=$(head -c 200 "$TMP/s_client.err" | tr "\n" " " | tr "=" " ")
  echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=s_client_failed s_client_stderr=${STDERR_HEAD}"
  exit 0
fi

sed -n "/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p" "$TMP/s_client.out" > "$TMP/tls.crt"
if [ ! -s "$TMP/tls.crt" ]; then
  echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=no_certificate"
  exit 0
fi

SUBJECT=$(openssl x509 -in "$TMP/tls.crt" -noout -subject -nameopt RFC2253 | sed "s/^subject=//" | tr " =" "__")
ISSUER=$(openssl x509 -in "$TMP/tls.crt" -noout -issuer -nameopt RFC2253 | sed "s/^issuer=//" | tr " =" "__")
# Try iso_8601 first (OpenSSL 3+; netshoot:v0.13 ships OpenSSL 3 on Alpine).
# Output format: notAfter=2026-04-28T12:34:56Z. Normalize to a string busybox
# date can parse (drop the T separator and the Z suffix).
NOT_AFTER_RAW=$(openssl x509 -in "$TMP/tls.crt" -dateopt iso_8601 -noout -enddate 2>/dev/null | sed "s/^notAfter=//")
if [ -z "$NOT_AFTER_RAW" ]; then
  NOT_AFTER_RAW=$(openssl x509 -in "$TMP/tls.crt" -noout -enddate | sed "s/^notAfter=//")
fi
NOT_AFTER_NORMALIZED=$(echo "$NOT_AFTER_RAW" | sed "s/T/ /" | sed "s/Z\$//")
NOT_AFTER_EPOCH=$(date -u -d "$NOT_AFTER_NORMALIZED" +%s 2>/dev/null || echo 0)
NOW_EPOCH=$(date -u +%s)
DAYS_REMAINING=$(( (NOT_AFTER_EPOCH - NOW_EPOCH) / 86400 ))
SAN_TEXT=$(openssl x509 -in "$TMP/tls.crt" -noout -ext subjectAltName 2>/dev/null | tr "\n" " ")

HOSTNAME_MATCH=false
if echo "$SAN_TEXT" | grep -q "DNS:${HOSTNAME}"; then
  HOSTNAME_MATCH=true
fi
# Restore the subject we mangled above for the CN-fallback check.
SUBJECT_RAW=$(openssl x509 -in "$TMP/tls.crt" -noout -subject -nameopt RFC2253 | sed "s/^subject=//")
case "$SUBJECT_RAW" in
  "CN=${HOSTNAME}"|*",CN=${HOSTNAME}") HOSTNAME_MATCH=true ;;
esac

VALID=false
ERROR=none
if [ "$DAYS_REMAINING" -lt 0 ]; then
  ERROR=certificate_expired
elif [ "$HOSTNAME_MATCH" != "true" ]; then
  ERROR=hostname_mismatch
elif [ "$DAYS_REMAINING" -ge 0 ] && [ "$HOSTNAME_MATCH" = "true" ]; then
  VALID=true
fi

printf "valid=%s days_remaining=%s subject=%s issuer=%s hostname_match=%s not_after_epoch=%s error=%s\n" \
  "$VALID" "$DAYS_REMAINING" "$SUBJECT" "$ISSUER" "$HOSTNAME_MATCH" "$NOT_AFTER_EPOCH" "$ERROR"
'

if ! kubectl -n "$NAMESPACE" exec -i "$PROBE_NAME" -- sh -s "$TARGET" "$HOSTNAME" <<<"$INNER_SCRIPT" 2>/tmp/sre-tls-kubectl.err; then
  STDERR_HEAD=$(head -c 200 /tmp/sre-tls-kubectl.err 2>/dev/null | tr '\n' ' ' | tr '=' ' ' || true)
  rm -f /tmp/sre-tls-kubectl.err
  echo "valid=false days_remaining=0 subject= issuer= hostname_match=false error=kubectl_exec_failed kubectl_stderr=${STDERR_HEAD}"
  exit 0
fi
rm -f /tmp/sre-tls-kubectl.err
