# MQTT Security Baseline

## Goals

- TLS 1.3 only
- mutual TLS for machine clients when possible
- explicit ACLs
- local-network or VPN exposure only
- immediate visibility on auth or broker anomalies

## Minimal Mosquitto TLS configuration

Create `mosquitto.conf` on the host path mounted to `/mosquitto/config/mosquitto.conf`.

```conf
per_listener_settings true
persistence true
persistence_location /mosquitto/data/
log_dest stdout
allow_anonymous false

listener 8883 0.0.0.0
protocol mqtt
tls_version tlsv1.3
cafile /mosquitto/certs/ca.crt
certfile /mosquitto/certs/server.crt
keyfile /mosquitto/certs/server.key
require_certificate true
use_identity_as_username true
password_file /mosquitto/config/passwd
acl_file /mosquitto/config/aclfile
```

## ACL example

Create `aclfile` on the mounted config path.

```conf
user ark_homeassistant
topic write ark/edge/homeassistant/#
topic read ark/control/homeassistant/#

user ark_unifi
topic write ark/edge/unifi/#
topic read ark/control/unifi/#

user ark_jellyfin
topic write ark/edge/jellyfin/#
topic read ark/control/jellyfin/#

pattern read $SYS/broker/clients/connected
pattern read $SYS/broker/messages/sent
```

## Password file

Generate the password file on the host before starting the stack:

```bash
mosquitto_passwd -c ./mqtt/config/passwd ark_homeassistant
mosquitto_passwd ./mqtt/config/passwd ark_unifi
mosquitto_passwd ./mqtt/config/passwd ark_jellyfin
```

## Certificate layout

The mounted cert directory should contain at least:

- `ca.crt`
- `server.crt`
- `server.key`

Optional client cert pairs:

- `homeassistant.crt` and `homeassistant.key`
- `unifi.crt` and `unifi.key`
- `jellyfin.crt` and `jellyfin.key`

## fail2ban sketch

Monitor the Docker host or reverse proxy logs for repeated failures.

```conf
[mosquitto-auth]
enabled = true
port = 8883
filter = mosquitto-auth
logpath = /var/lib/docker/containers/*/*.log
maxretry = 5
findtime = 10m
bantime = 1h
```

Example filter:

```conf
[Definition]
failregex = .*Client <HOST> disconnected, not authorised.*
            .*OpenSSL Error.*<HOST>.*
ignoreregex =
```

## VPN recommendation

Expose the broker only on a trusted LAN or over WireGuard/Tailscale. Do not publish MQTT directly to the public internet for Phase 0. If a client cannot live on the same private network, put it behind the VPN first and keep broker listeners strict and minimal.
