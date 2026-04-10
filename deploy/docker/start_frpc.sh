#!/usr/bin/env sh
set -eu

required_vars="FRP_SERVER_ADDR FRP_SERVER_PORT FRP_AUTH_TOKEN FRP_REMOTE_PORT FRP_PROXY_NAME"

for var_name in $required_vars; do
  eval "var_value=\${$var_name:-}"
  if [ -z "$var_value" ]; then
    echo "Missing required FRP setting: $var_name" >&2
    exit 1
  fi
done

echo "Starting FRP client: ${FRP_PROXY_NAME} -> ${FRP_SERVER_ADDR}:${FRP_REMOTE_PORT}"

exec /usr/local/bin/frpc -c /etc/frp/frpc.toml
