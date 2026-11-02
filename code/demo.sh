#!/usr/bin/env bash
# Run a short end-to-end demonstration against a temporary database.
set -euo pipefail
cd "$(dirname "$0")"

WORK=$(mktemp -d)
export TICKET_DB="$WORK/demo.db"

run_case() {
    printf '%b' "$1" | python3 main.py
}

echo "=== 1. participant1 registers ==="
run_case 'participant1\n123456\n3\n1\n1\n1\nreq-demo-1\n0\n'

echo "=== 2. participant2 registers ==="
run_case 'participant2\n123456\n3\n1\n1\n1\nreq-demo-2\n0\n'

CODE=$(python3 - <<'PY'
import os
import sqlite3

conn = sqlite3.connect(os.environ["TICKET_DB"])
print(conn.execute("SELECT code FROM credentials ORDER BY id LIMIT 1").fetchone()[0])
PY
)

echo "=== 3. checker verifies $CODE ==="
run_case "checker1\n123456\n2\n$CODE\n0\n"

echo "=== 4. organizer statistics ==="
run_case 'organizer1\n123456\n9\n1\n0\n'

echo "=== 5. administrator summary ==="
run_case 'admin1\n123456\n4\n0\n'

echo "demo database: $WORK/demo.db"
