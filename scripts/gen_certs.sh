#!/usr/bin/env bash
# gen_certs.sh — Generate a self-signed TLS certificate for local Docker development.
#
# Usage:
#   ./scripts/gen_certs.sh
#
# Generates:
#   docker/certs/nginx.crt  — self-signed X.509 certificate (valid 365 days)
#   docker/certs/nginx.key  — private key (RSA 2048-bit, no passphrase)
#
# Requirements:
#   openssl (pre-installed on macOS, Linux, and WSL2)
#
# The certificate includes Subject Alternative Names (SAN) for:
#   DNS:localhost, IP:127.0.0.1
# SAN is required by modern browsers (Chrome, Firefox) to avoid HSTS errors.
#
# The certs/ directory is gitignored. Run this script once per dev machine.
# The script is idempotent — it skips generation if certs already exist.

set -euo pipefail

CERT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docker/certs"
CERT_FILE="${CERT_DIR}/nginx.crt"
KEY_FILE="${CERT_DIR}/nginx.key"

mkdir -p "${CERT_DIR}"

if [[ -f "${CERT_FILE}" && -f "${KEY_FILE}" ]]; then
    echo "✓ Certs already exist at ${CERT_DIR} — skipping generation."
    echo "  Delete docker/certs/nginx.{crt,key} and re-run to regenerate."
    exit 0
fi

echo "Generating self-signed TLS certificate for localhost..."

openssl req -x509 \
    -nodes \
    -days 365 \
    -newkey rsa:2048 \
    -keyout "${KEY_FILE}" \
    -out "${CERT_FILE}" \
    -subj "/C=US/ST=Local/L=Local/O=StreamerAdvisor/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

chmod 600 "${KEY_FILE}"
chmod 644 "${CERT_FILE}"

echo ""
echo "✓ Certificate: ${CERT_FILE}"
echo "✓ Private key: ${KEY_FILE}"
echo ""
echo "Next steps:"
echo "  docker compose up --build"
echo "  Open https://localhost in your browser"
echo "  Click 'Advanced → Proceed to localhost' to accept the self-signed cert."
echo ""
echo "Note: Your browser may show a security warning on first visit."
echo "This is expected for self-signed certificates and safe for local development."
