#!/usr/bin/env bash
set -euo pipefail

if [[ $(id -u) -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

repo_dir=/home/wazeer/agents-class-2026/class-agent
site_conf=/etc/nginx/sites-available/cognitive-agents
preview_unit=/etc/systemd/system/class-agent-grade-preview.service
preview_snippet=/etc/nginx/snippets/class-agent-grade-preview.conf
preview_file="$repo_dir/var/grades/test-student2-preview.json"
backup="$site_conf.before-grade-preview-$(date -u +%Y%m%dT%H%M%SZ)"

if [[ -e $preview_unit || -e $preview_snippet ]]; then
  echo "The grading preview is already installed; inspect it before retrying." >&2
  exit 1
fi
if [[ ! -f $preview_file || ! -f /home/wazeer/grade-preview-site/dist/index.html ]]; then
  echo "Preview data or frontend assets are missing." >&2
  exit 1
fi
if ss -ltn '( sport = :8002 )' | grep -q '127.0.0.1:8002'; then
  echo "Port 8002 is occupied; stop the temporary test process first." >&2
  exit 1
fi

cp -a "$site_conf" "$backup"
rollback() {
  trap - ERR
  cp -a "$backup" "$site_conf"
  systemctl disable --now class-agent-grade-preview.service >/dev/null 2>&1 || true
  rm -f "$preview_unit" "$preview_snippet"
  systemctl daemon-reload || true
  nginx -t && systemctl reload nginx || true
  echo "Preview installation failed; restored $site_conf from $backup." >&2
}
trap rollback ERR

install -m 0644 "$repo_dir/deploy/class-agent-grade-preview.service" "$preview_unit"
install -m 0644 "$repo_dir/deploy/cognitive-agents-grade-preview-location.conf" "$preview_snippet"
python3 - "$site_conf" <<'PY'
import os
import stat
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
anchor = "    include /etc/nginx/snippets/class-agent-mcp.conf;\n"
addition = "    include /etc/nginx/snippets/class-agent-grade-preview.conf;\n"
content = path.read_text(encoding="utf-8")
if content.count(anchor) != 1 or addition in content:
    raise SystemExit("Unexpected nginx configuration; no changes applied")
descriptor, temporary_name = tempfile.mkstemp(prefix=".cognitive-agents-", dir=path.parent)
try:
    os.fchmod(descriptor, stat.S_IMODE(path.stat().st_mode))
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content.replace(anchor, anchor + addition))
    os.replace(temporary_name, path)
finally:
    Path(temporary_name).unlink(missing_ok=True)
PY

nginx -t
systemctl daemon-reload
systemctl enable --now class-agent-grade-preview.service
for attempt in {1..30}; do
  if curl -fsS --max-time 2 http://127.0.0.1:8002/api/v1/health >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS --max-time 2 http://127.0.0.1:8002/api/v1/health >/dev/null
systemctl reload nginx
trap - ERR
echo "Preview ready at https://cognitive-agents.media.mit.edu/grade-preview/"
echo "Nginx backup: $backup"
