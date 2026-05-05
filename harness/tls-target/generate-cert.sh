#!/usr/bin/env bash
set -euo pipefail

DAYS="${1:?validity days is required}"
COMMON_NAME="${2:?common name is required}"
SUBJECT_ALT_NAMES="${3:?subjectAltName value is required, for example DNS:api.example.com}"
SECRET_NAME="${4:?secret name is required}"
NAMESPACE="${5:-default}"
OUT_DIR="${6:-/tmp/sre-agent-tls-target}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 127; }

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

cat > "$OUT_DIR/leaf.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = ${COMMON_NAME}

[v3_req]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = ${SUBJECT_ALT_NAMES}
EOF

openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout "$OUT_DIR/ca.key" \
  -out "$OUT_DIR/ca.crt" \
  -subj "/CN=sre-agent-test-ca" >/dev/null 2>&1

openssl req -new -newkey rsa:2048 -nodes \
  -keyout "$OUT_DIR/tls.key" \
  -out "$OUT_DIR/tls.csr" \
  -subj "/CN=${COMMON_NAME}" \
  -config "$OUT_DIR/leaf.cnf" >/dev/null 2>&1

if [[ "$DAYS" -gt 0 ]]; then
  openssl x509 -req -in "$OUT_DIR/tls.csr" \
    -CA "$OUT_DIR/ca.crt" \
    -CAkey "$OUT_DIR/ca.key" \
    -CAcreateserial \
    -out "$OUT_DIR/tls.crt" \
    -days "$DAYS" \
    -sha256 \
    -extfile "$OUT_DIR/leaf.cnf" \
    -extensions v3_req >/dev/null 2>&1
else
  mkdir -p "$OUT_DIR/ca"
  touch "$OUT_DIR/ca/index.txt"
  echo "1000" > "$OUT_DIR/ca/serial"
  cat > "$OUT_DIR/ca.cnf" <<EOF
[ca]
default_ca = CA_default

[CA_default]
dir = ${OUT_DIR}/ca
database = \$dir/index.txt
serial = \$dir/serial
new_certs_dir = \$dir
certificate = ${OUT_DIR}/ca.crt
private_key = ${OUT_DIR}/ca.key
default_md = sha256
policy = policy_any
copy_extensions = copy

[policy_any]
commonName = supplied

[v3_req]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = ${SUBJECT_ALT_NAMES}
EOF
  read -r START_DATE END_DATE < <(python3 - <<'PY'
from __future__ import annotations

from datetime import datetime, timedelta, timezone

end = datetime.now(timezone.utc) - timedelta(days=2)
start = end - timedelta(days=1)
print(start.strftime("%y%m%d%H%M%SZ"), end.strftime("%y%m%d%H%M%SZ"))
PY
)
  openssl ca -batch -config "$OUT_DIR/ca.cnf" \
    -in "$OUT_DIR/tls.csr" \
    -out "$OUT_DIR/tls.crt" \
    -startdate "$START_DATE" \
    -enddate "$END_DATE" \
    -extensions v3_req \
    -notext >/dev/null 2>&1
fi

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NAMESPACE" create secret tls "$SECRET_NAME" \
  --cert="$OUT_DIR/tls.crt" \
  --key="$OUT_DIR/tls.key" \
  --dry-run=client -o yaml | kubectl apply -f -
