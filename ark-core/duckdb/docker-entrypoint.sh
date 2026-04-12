#!/bin/sh
set -e
if [ "$(id -u)" = "0" ]; then
  chown -R ark:ark /data 2>/dev/null || true
  exec gosu ark "$@"
fi
exec "$@"
