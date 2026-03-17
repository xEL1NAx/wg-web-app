#!/bin/sh
set -eu

SERVICE_UNIT="${WG_SYSTEMD_UNIT:-wg-quick@wg0}"

# Preferred path inside Docker: enter host namespaces and call host systemd.
if command -v nsenter >/dev/null 2>&1; then
  if nsenter -t 1 -m -u -i -n -p -- sh -c 'test "$(cat /proc/1/comm 2>/dev/null)" = "systemd"' >/dev/null 2>&1; then
    exec nsenter -t 1 -m -u -i -n -p -- systemctl restart --now "$SERVICE_UNIT"
  fi
fi

# Local/non-container fallback when running directly on a systemd host.
if command -v systemctl >/dev/null 2>&1; then
  if [ "$(cat /proc/1/comm 2>/dev/null || true)" = "systemd" ]; then
    exec systemctl restart --now "$SERVICE_UNIT"
  fi
fi

echo "Unable to run systemctl for ${SERVICE_UNIT}. Run the container with pid: host and privileged: true, or set WG_RESTART_COMMAND to a custom host restart command." >&2
exit 1
