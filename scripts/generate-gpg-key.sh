#!/usr/bin/env bash
set -euo pipefail
mkdir -p keys
GNUPGHOME="$(pwd)/keys/gnupg"
mkdir -p "$GNUPGHOME"
chmod 700 "$GNUPGHOME"
export GNUPGHOME
KEY_NAME="${GPG_KEY_ID:-DebZip Signing Key}"
KEY_EMAIL="${GPG_KEY_EMAIL:-debzip@example.com}"
if ! gpg --list-secret-keys "$KEY_NAME" >/dev/null 2>&1; then
  gpg --batch --passphrase '' --quick-generate-key "$KEY_NAME <$KEY_EMAIL>" ed25519 sign 2y
fi
gpg --armor --export "$KEY_NAME" > keys/debzip-public-key.asc
cat > keys/README.md <<EOF
# DebZip keys

This directory contains the public key and local GnuPG home used for signing manifests.
Back up the private key securely if this service is used in production.
EOF
printf 'Generated public key: keys/debzip-public-key.asc
'
