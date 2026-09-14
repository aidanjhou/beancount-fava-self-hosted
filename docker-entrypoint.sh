#!/bin/sh
set -e

# Determine data directory
DATA_DIR="/data"
mkdir -p "$DATA_DIR/imports"

export BEANCOUNT_FILE="${BEANCOUNT_FILE:-$DATA_DIR/main.beancount}"

# If running default fava command and BEANCOUNT_FILE doesn't exist, create initial ledger for online import
if [ "$1" = "fava" ] || [ -z "$1" ]; then
    if [ ! -f "$BEANCOUNT_FILE" ]; then
        echo "[entrypoint] Creating initial ledger at '$BEANCOUNT_FILE'..."
        mkdir -p "$(dirname "$BEANCOUNT_FILE")"
        cat << 'EOF' > "$BEANCOUNT_FILE"
option "title" "Personal Finances"
option "operating_currency" "CNY"

; Automatically declare accounts when new transactions are imported
plugin "beancount.plugins.auto_accounts"

; Primary folder for uploading and importing statement files via Fava UI
2026-01-01 custom "fava-option" "import-dirs" "imports"
EOF
        echo "[entrypoint] Initial ledger created. Users can initialize accounts via online import."
    fi
    [ -z "$1" ] && set -- fava
    exec "$@"
fi

exec "$@"
