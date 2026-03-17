#!/bin/sh
set -eu

SERVICE_UNIT="${WG_SYSTEMD_UNIT:-wg-quick@wg0}"
TARGET_PID="${WG_NSENTER_TARGET_PID:-1}"
NSENTER_ERROR=""

# Preferred path inside Docker: enter host namespaces and call host systemd.
if command -v nsenter >/dev/null 2>&1; then
  if [ -r "/proc/${TARGET_PID}/ns/mnt" ]; then
    if NSENTER_OUTPUT="$(nsenter -t "$TARGET_PID" -m -u -i -n -p -- systemctl restart --now "$SERVICE_UNIT" 2>&1)"; then
      exit 0
    fi
    NSENTER_ERROR="${NSENTER_ERROR}${NSENTER_ERROR:+ | }pid=${TARGET_PID}: ${NSENTER_OUTPUT:-nsenter failed without stderr output}"
  fi

  if [ -r "/host/proc/1/ns/mnt" ]; then
    if NSENTER_OUTPUT="$(
      nsenter \
        --mount=/host/proc/1/ns/mnt \
        --uts=/host/proc/1/ns/uts \
        --ipc=/host/proc/1/ns/ipc \
        --net=/host/proc/1/ns/net \
        --pid=/host/proc/1/ns/pid \
        -- systemctl restart --now "$SERVICE_UNIT" 2>&1
    )"; then
      exit 0
    fi
    NSENTER_ERROR="${NSENTER_ERROR}${NSENTER_ERROR:+ | }host-proc: ${NSENTER_OUTPUT:-nsenter via /host/proc failed without stderr output}"
  fi
fi

# Local/non-container fallback when running directly on a systemd host.
if command -v systemctl >/dev/null 2>&1; then
  if [ "$(cat /proc/1/comm 2>/dev/null || true)" = "systemd" ]; then
    exec systemctl restart --now "$SERVICE_UNIT"
  fi
fi

echo "Unable to restart ${SERVICE_UNIT} via systemctl." >&2
if [ -n "$NSENTER_ERROR" ]; then
  echo "nsenter error: $NSENTER_ERROR" >&2
fi
echo "Run the container with pid: host and privileged: true, or mount /proc to /host/proc and keep privileged mode, or set WG_RESTART_COMMAND to a host-specific command." >&2
exit 1
