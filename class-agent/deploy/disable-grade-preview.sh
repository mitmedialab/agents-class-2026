#!/usr/bin/env bash
set -euo pipefail

if [[ $(id -u) -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

site_conf=/etc/nginx/sites-available/cognitive-agents
preview_unit=/etc/systemd/system/class-agent-grade-preview.service
preview_snippet=/etc/nginx/snippets/class-agent-grade-preview.conf
addition="    include /etc/nginx/snippets/class-agent-grade-preview.conf;"

if grep -Fq "$addition" "$site_conf"; then
  cp -a "$site_conf" "$site_conf.before-grade-preview-removal-$(date -u +%Y%m%dT%H%M%SZ)"
  python3 - "$site_conf" <<'PY'
import os
import stat
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
line = "    include /etc/nginx/snippets/class-agent-grade-preview.conf;\n"
content = path.read_text(encoding="utf-8")
if content.count(line) != 1:
    raise SystemExit("Unexpected nginx preview include; no changes applied")
descriptor, temporary_name = tempfile.mkstemp(prefix=".cognitive-agents-", dir=path.parent)
try:
    os.fchmod(descriptor, stat.S_IMODE(path.stat().st_mode))
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content.replace(line, ""))
    os.replace(temporary_name, path)
finally:
    Path(temporary_name).unlink(missing_ok=True)
PY
fi

nginx -t
systemctl reload nginx
systemctl disable --now class-agent-grade-preview.service
rm -f "$preview_unit" "$preview_snippet"
systemctl daemon-reload
echo "Grading preview removed; the main site was not changed."
