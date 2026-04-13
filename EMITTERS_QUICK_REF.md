# ARK Emitters - Quick Reference

## Deploy All Three Emitters

```bash
# Set credentials
export HA_TOKEN=your_ha_token
export JELLYFIN_TOKEN=your_jellyfin_token
export JELLYFIN_USER_ID=your_user_id
export UNIFI_USERNAME=ubnt
export UNIFI_PASSWORD=password

# Build
docker-compose build ha-emitter jellyfin-emitter unifi-emitter

# Start
docker-compose up -d ha-emitter jellyfin-emitter unifi-emitter

# Verify
curl http://localhost:7000/api/mesh | jq '.service_details | keys'
```

---

## Monitor Events

```bash
# Home Assistant state changes
docker exec ark-nats nats sub "ark.event.state.change"

# Jellyfin playback events
docker exec ark-nats nats sub "ark.event.media.playback"

# UniFi device events
docker exec ark-nats nats sub "ark.event.network.device"

# All metrics
docker exec ark-nats nats sub "ark.metrics.*"

# All events
docker exec ark-nats nats sub "ark.event.*"
```

---

## Query Capabilities

### Home Assistant

```bash
# Get temperature
docker exec ark-nats nats pub "ark.call.homeassistant.climate.temperature" \
'{"request_id":"t1","params":{"entity_id":"climate.living_room"}}'

# Toggle light
docker exec ark-nats nats pub "ark.call.homeassistant.light.toggle" \
'{"request_id":"l1","params":{"entity_id":"light.bedroom"}}'

# Get sensor
docker exec ark-nats nats pub "ark.call.homeassistant.sensor.reading" \
'{"request_id":"s1","params":{"entity_id":"sensor.humidity"}}'

# Get events
docker exec ark-nats nats pub "ark.call.homeassistant.event.home_assistant" \
'{"request_id":"e1","params":{}}'
```

### Jellyfin

```bash
# Check playback status
docker exec ark-nats nats pub "ark.call.jellyfin.playback.status" \
'{"request_id":"p1","params":{}}'

# Search media
docker exec ark-nats nats pub "ark.call.jellyfin.media.search" \
'{"request_id":"m1","params":{"query":"Breaking Bad"}}'

# Get library
docker exec ark-nats nats pub "ark.call.jellyfin.media.library" \
'{"request_id":"l1","params":{}}'

# Get library items
docker exec ark-nats nats pub "ark.call.jellyfin.library.items" \
'{"request_id":"i1","params":{}}'
```

### UniFi

```bash
# Check network health
docker exec ark-nats nats pub "ark.call.unifi.network.health" \
'{"request_id":"h1","params":{}}'

# Get devices
docker exec ark-nats nats pub "ark.call.unifi.network.devices" \
'{"request_id":"d1","params":{}}'

# Get wireless clients
docker exec ark-nats nats pub "ark.call.unifi.wireless.clients" \
'{"request_id":"w1","params":{}}'

# Get device status
docker exec ark-nats nats pub "ark.call.unifi.device.status" \
'{"request_id":"ds1","params":{"device_id":"device-uuid"}}'

# Get network stats
docker exec ark-nats nats pub "ark.call.unifi.network.stats" \
'{"request_id":"ns1","params":{}}'
```

---

## View Logs

```bash
# HA emitter
docker logs -f ark-ha-emitter

# Jellyfin emitter
docker logs -f ark-jellyfin-emitter

# UniFi emitter
docker logs -f ark-unifi-emitter

# All at once
docker-compose logs -f ha-emitter jellyfin-emitter unifi-emitter
```

---

## Test Events (Simulate)

```bash
# Simulate HA state change
docker exec ark-nats nats pub "ark.event.state.change" \
'{"entity_id":"light.living_room","old_state":"off","new_state":"on"}'

# Simulate Jellyfin playback
docker exec ark-nats nats pub "ark.event.media.playback" \
'{"event":"playback_start","device":"Living Room","title":"Breaking Bad"}'

# Simulate UniFi device offline
docker exec ark-nats nats pub "ark.event.network.device" \
'{"event":"device_status_changed","device_name":"Main AP","old_status":"connected","new_status":"offline"}'
```

---

## Troubleshoot

### HA Emitter Not Connecting

```bash
# Check token is set
echo $HA_TOKEN

# Check HA is accessible
curl http://homeassistant:8123/api/states -H "Authorization: Bearer $HA_TOKEN"

# Restart
docker-compose restart ha-emitter

# Check logs
docker logs ark-ha-emitter | grep -i "error\|connected"
```

### Jellyfin Not Emitting

```bash
# Check credentials
echo $JELLYFIN_TOKEN $JELLYFIN_USER_ID

# Test API
curl http://jellyfin:8096/Users/$JELLYFIN_USER_ID/Items?api_key=$JELLYFIN_TOKEN

# Restart
docker-compose restart jellyfin-emitter

# Check playback
docker logs ark-jellyfin-emitter | tail -20
```

### UniFi Emitter Not Registering

```bash
# Check credentials
echo $UNIFI_USERNAME $UNIFI_PASSWORD

# Test connectivity (ignore SSL warnings)
curl -k https://unifi:8443/api/self -d "{\"username\":\"$UNIFI_USERNAME\",\"password\":\"$UNIFI_PASSWORD\"}" \
  -H "Content-Type: application/json"

# Restart
docker-compose restart unifi-emitter

# Check auth
docker logs ark-unifi-emitter | grep -i "auth\|connect"
```

---

## View Emitter Status

```bash
# Full mesh status
curl http://localhost:7000/api/mesh | jq

# Just emitters
curl http://localhost:7000/api/mesh | jq '.service_details | with_entries(select(.key | IN("homeassistant","jellyfin","unifi")))'

# Get specific emitter
curl http://localhost:7000/api/service/homeassistant | jq

# Route capability
curl http://localhost:7000/api/route/climate.temperature | jq
curl http://localhost:7000/api/route/media.playback | jq
curl http://localhost:7000/api/route/network.health | jq
```

---

## Event Schema

### HA Event
```json
{
  "entity_id": "light.living_room",
  "old_state": "off",
  "new_state": "on",
  "attributes": {"brightness": 254},
  "timestamp": "2024-01-15T10:30:00Z",
  "source": "homeassistant"
}
```

### Jellyfin Event
```json
{
  "event": "playback_start",
  "session_id": "s123",
  "device": "Living Room",
  "title": "Breaking Bad",
  "media_type": "Series",
  "timestamp": "2024-01-15T10:30:00Z",
  "source": "jellyfin"
}
```

### UniFi Event
```json
{
  "event": "device_status_changed",
  "device_id": "device-uuid",
  "device_name": "Main AP",
  "ip_address": "192.168.1.1",
  "old_status": "connected",
  "new_status": "offline",
  "timestamp": "2024-01-15T10:30:00Z",
  "source": "unifi"
}
```

---

## Environment Variables

```bash
# Home Assistant
HA_TOKEN=                  # Required: Long-lived access token
HA_URL=http://homeassistant:8123  # Optional: HA URL

# Jellyfin
JELLYFIN_TOKEN=            # Required: API token
JELLYFIN_USER_ID=          # Required: User ID
JELLYFIN_URL=http://jellyfin:8096  # Optional: Jellyfin URL

# UniFi
UNIFI_USERNAME=ubnt        # Required: UniFi username
UNIFI_PASSWORD=            # Required: UniFi password
UNIFI_SITE=default         # Optional: Site name
UNIFI_URL=https://unifi:8443  # Optional: UniFi URL

# All emitters
NATS_URL=nats://nats:4222  # Optional: NATS URL
INSTANCE_ID=               # Optional: Custom instance ID
```

---

## Service URLs

| Service | URL |
|---------|-----|
| Home Assistant | http://localhost:8123 |
| Jellyfin | http://localhost:8096 |
| UniFi | https://localhost:8443 |
| Mesh Registry | http://localhost:7000 |
| NATS | nats://localhost:4222 |

---

## Load & Performance

```bash
# Monitor event throughput
watch -n 1 "docker exec ark-nats nats stream info ark.events | grep -E 'Messages|Bytes'"

# Monitor emitter load
curl -s http://localhost:7000/api/mesh | jq '.service_details[] | {instance_count, total_load}'

# Monitor NATS memory
docker stats ark-nats --no-stream | grep -E "MEM\|ark"
```

---

## Workflow Commands

### Subscribe & Forward to n8n

```bash
# Get webhook URL from n8n, then:

docker exec ark-nats nats sub "ark.event.media.playback" | \
  while read msg; do
    curl -X POST http://localhost:5678/webhook/jellyfin-events \
      -H "Content-Type: application/json" \
      -d "$msg"
  done
```

### Filter Events

```bash
# Only HA state changes (not all events)
docker exec ark-nats nats sub "ark.event.state.change" --raw

# Only Jellyfin playback (not library)
docker exec ark-nats nats sub "ark.event.media.playback" --raw

# Only UniFi device changes (not health checks)
docker exec ark-nats nats sub "ark.event.network.device" --raw
```

---

## Integration Checklist

- [ ] Set HA_TOKEN environment variable
- [ ] Set JELLYFIN_TOKEN and JELLYFIN_USER_ID
- [ ] Set UNIFI_USERNAME and UNIFI_PASSWORD
- [ ] Build emitter images: `docker-compose build ha-emitter jellyfin-emitter unifi-emitter`
- [ ] Start emitters: `docker-compose up -d ha-emitter jellyfin-emitter unifi-emitter`
- [ ] Verify registration: `curl http://localhost:7000/api/mesh | jq`
- [ ] Subscribe to events: `docker exec ark-nats nats sub "ark.event.*"`
- [ ] Test capabilities: Query each emitter
- [ ] Set up n8n workflows
- [ ] Create custom agents if needed
- [ ] Monitor in production: `docker logs -f` + Grafana dashboards

---

**Emitters are now live. Your infrastructure feeds ARK. Intelligence emerges.**
