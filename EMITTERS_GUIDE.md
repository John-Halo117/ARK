# ARK Emitters - Home Assistant, Jellyfin, UniFi Integration

This guide explains how to configure and use the three main data source emitters integrated into ARK.

---

## Overview

### What Are Emitters?

Emitters are services that:
1. **Monitor external systems** (Home Assistant, Jellyfin, UniFi)
2. **Emit events to NATS** when state changes occur
3. **Register capabilities** in the ARK mesh
4. **Respond to queries** from agents

They act as bridges between external systems and ARK's event-driven architecture.

---

## 1. Home Assistant Emitter

### What It Does

- Monitors Home Assistant entity state changes
- Emits state change events when devices change
- Exposes HA devices as queryable capabilities
- Allows agents to read sensor values and toggle devices

### Configuration

#### Set Home Assistant Token

1. Log into Home Assistant at http://localhost:8123
2. Go to Profile → Create Long-Lived Access Token
3. Copy the token

#### Set Environment Variables

```bash
export HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
export HA_URL=http://homeassistant:8123  # Default if local
```

#### Start Home Assistant Emitter

```bash
docker-compose build ha-emitter
docker-compose up -d ha-emitter
```

### Capabilities Exposed

| Capability | Description | Returns |
|-----------|-------------|---------|
| `event.home_assistant` | List recent events | Entity states |
| `state.device_update` | Update device state | Success status |
| `climate.temperature` | Get temperature reading | Current temp |
| `light.toggle` | Toggle light on/off | New state |
| `sensor.reading` | Get sensor value | Current reading |

### Example Usage

**Query temperature:**
```bash
docker exec ark-nats nats pub "ark.call.homeassistant.climate.temperature" \
'{"request_id":"temp-001","params":{"entity_id":"climate.living_room"}}'
```

**Toggle light:**
```bash
docker exec ark-nats nats pub "ark.call.homeassistant.light.toggle" \
'{"request_id":"light-001","params":{"entity_id":"light.bedroom"}}'
```

### Events Emitted

Home Assistant emits to these topics:

- `ark.event.climate.temperature` - Temperature readings
- `ark.event.light.toggle` - Light state changes
- `ark.event.sensor.reading` - Sensor readings
- `ark.event.state.change` - Generic state changes
- `ark.metrics.temperature` - Temperature metrics for anomaly detection

---

## 2. Jellyfin Emitter

### What It Does

- Monitors media playback in Jellyfin
- Detects when playback starts/stops/changes
- Emits media events for consumption by agents
- Allows agents to search library and check playback status

### Configuration

#### Get Jellyfin API Token

1. Log into Jellyfin at http://localhost:8096
2. Go to Dashboard → Users (admin)
3. Create a new access token
4. Copy the token and user ID

#### Set Environment Variables

```bash
export JELLYFIN_TOKEN=your_api_token_here
export JELLYFIN_USER_ID=your_user_id_here
export JELLYFIN_URL=http://jellyfin:8096  # Default if local
```

#### Start Jellyfin and Emitter

```bash
docker-compose up -d jellyfin jellyfin-emitter
```

### Capabilities Exposed

| Capability | Description | Returns |
|-----------|-------------|---------|
| `media.playback` | Get active playback | Active sessions |
| `media.library` | Get media folders | Library structure |
| `media.search` | Search media | Matching items |
| `playback.status` | Current playback state | Session details |
| `library.items` | Get library items | Item list |

### Example Usage

**Check what's playing:**
```bash
docker exec ark-nats nats pub "ark.call.jellyfin.playback.status" \
'{"request_id":"playback-001","params":{}}'
```

**Search library:**
```bash
docker exec ark-nats nats pub "ark.call.jellyfin.media.search" \
'{"request_id":"search-001","params":{"query":"Breaking Bad"}}'
```

### Events Emitted

Jellyfin emits to these topics:

- `ark.event.media.playback` - Playback start/stop/change
- `ark.metrics.media_duration` - Media duration metrics

---

## 3. UniFi Emitter

### What It Does

- Monitors UniFi network devices (APs, switches, etc.)
- Detects when devices come online/go offline
- Emits device status change events
- Allows agents to query network health and device status

### Configuration

#### Get UniFi Credentials

UniFi runs on https://localhost:8443 by default (self-signed cert).

1. Create/get UniFi controller credentials
2. Note the site name (default: "default")

#### Set Environment Variables

```bash
export UNIFI_USERNAME=ubnt
export UNIFI_PASSWORD=ubnt_password
export UNIFI_SITE=default  # Change if using non-default site
export UNIFI_URL=https://unifi:8443  # Default if local
```

#### Start UniFi and Emitter

```bash
docker-compose up -d unifi unifi-emitter
```

### Capabilities Exposed

| Capability | Description | Returns |
|-----------|-------------|---------|
| `network.devices` | List all devices | Device inventory |
| `network.events` | Recent network events | Event log |
| `network.stats` | Network statistics | Device/client counts |
| `device.status` | Status of specific device | Device details |
| `wireless.clients` | List WiFi clients | Connected clients |
| `network.health` | Overall network health | Health score, status |

### Example Usage

**Check network health:**
```bash
docker exec ark-nats nats pub "ark.call.unifi.network.health" \
'{"request_id":"health-001","params":{}}'
```

**Get device status:**
```bash
docker exec ark-nats nats pub "ark.call.unifi.device.status" \
'{"request_id":"device-001","params":{"device_id":"device-uuid"}}'
```

**List wireless clients:**
```bash
docker exec ark-nats nats pub "ark.call.unifi.wireless.clients" \
'{"request_id":"clients-001","params":{}}'
```

### Events Emitted

UniFi emits to these topics:

- `ark.event.network.device` - Device online/status changed
- `ark.metrics.network` - Network metrics (device count, client count)

---

## Integration Workflows

### Example 1: Monitor Home Temperature, Trigger Jellyfin Pause on Anomaly

**n8n Workflow:**

```
1. Trigger: ark.metrics.temperature topic
2. OpenWolf checks: Analyze temperature anomaly
3. If ASHI < 70 (degraded):
   - Query Jellyfin playback status
   - If playing:
     - Compose pause command
     - Send to Home Assistant
```

**NATS flow:**
```
HA → metrics.temperature
  ↓
OpenWolf → anomaly.detect
  ↓
Jellyfin → playback.status
  ↓
HA → light.toggle / pause
```

### Example 2: Monitor Network, Alert on Device Offline

**Workflow:**

```
1. UniFi emits: device_status_changed (online → offline)
2. Trigger n8n on ark.event.network.device
3. Send Composio email alert
4. Log to DuckDB
```

### Example 3: Track Media Activity, Trigger Climate Adjustment

**Workflow:**

```
1. Jellyfin emits: playback_start event
2. Query Home Assistant climate
3. If playing movie:
   - Dim lights
   - Lower temperature by 1°C
   - Mute audio in other rooms
```

---

## Monitoring Emitters

### Check Registration

```bash
curl http://localhost:7000/api/mesh | jq '.service_details'
```

Expected output includes:
```json
{
  "homeassistant": {
    "instance_count": 1,
    "healthy_count": 1
  },
  "jellyfin": {
    "instance_count": 1,
    "healthy_count": 1
  },
  "unifi": {
    "instance_count": 1,
    "healthy_count": 1
  }
}
```

### View Emitter Logs

```bash
# Home Assistant emitter
docker logs -f ark-ha-emitter

# Jellyfin emitter
docker logs -f ark-jellyfin-emitter

# UniFi emitter
docker logs -f ark-unifi-emitter
```

### Subscribe to Events in Real-Time

**Monitor HA state changes:**
```bash
docker exec ark-nats nats sub "ark.event.state.change" --raw
```

**Monitor Jellyfin playback:**
```bash
docker exec ark-nats nats sub "ark.event.media.playback" --raw
```

**Monitor UniFi devices:**
```bash
docker exec ark-nats nats sub "ark.event.network.device" --raw
```

---

## Troubleshooting

### HA Emitter Not Connecting

**Problem:** `HA_TOKEN` not set or invalid

**Solution:**
```bash
# Verify token in Home Assistant
# Go to Profile → Create Long-Lived Access Token (if none exists)
export HA_TOKEN=your_token
docker-compose restart ha-emitter
docker logs ark-ha-emitter | grep "Connected"
```

### Jellyfin Emitter Not Getting Playback Events

**Problem:** Token or user ID invalid

**Solution:**
```bash
# Check Jellyfin is accessible
curl http://localhost:8096/web
# Verify API key in Jellyfin
export JELLYFIN_TOKEN=new_token
docker-compose restart jellyfin-emitter
```

### UniFi Emitter SSL Certificate Error

**Problem:** Self-signed certificate rejected

**Solution:** Already handled in code (SSL verification disabled)

```bash
# Verify UniFi is accessible
curl -k https://localhost:8443
# Check credentials
export UNIFI_USERNAME=correct_user
export UNIFI_PASSWORD=correct_pass
docker-compose restart unifi-emitter
```

### No Events Appearing in NATS

**Problem:** Emitter running but not emitting

**Solution:**
```bash
# Check emitter is registered
curl http://localhost:7000/api/service/homeassistant

# Check heartbeats
docker exec ark-nats nats sub "ark.mesh.heartbeat" --raw

# Tail logs for errors
docker logs ark-ha-emitter | tail -20
```

---

## Advanced Configuration

### Scale Emitters for High Load

Create multiple emitter instances in docker-compose.yml:

```yaml
ha-emitter-0:
  # ... config

ha-emitter-1:
  # ... config with different INSTANCE_ID
```

Both register into mesh with different capabilities.

### Connect to Remote Home Assistant

```bash
export HA_URL=https://ha.example.com
export HA_TOKEN=your_long_lived_token
```

### Connect to Remote Jellyfin

```bash
export JELLYFIN_URL=https://jellyfin.example.com
export JELLYFIN_TOKEN=remote_token
```

### Custom Event Topics

Edit emitter source code to change topics:

```python
# In homeassistant_emitter.py, line ~180
await self.js.publish("ark.event.custom.topic", ...)
```

Then agents can subscribe:
```bash
docker exec ark-nats nats sub "ark.event.custom.topic"
```

---

## Event Schema Reference

### Home Assistant Events

```json
{
  "entity_id": "climate.living_room",
  "old_state": "22.5",
  "new_state": "23.1",
  "attributes": {
    "current_temperature": 23.1,
    "target_temperature": 22
  },
  "timestamp": "2024-01-15T10:30:00Z",
  "source": "homeassistant"
}
```

### Jellyfin Events

```json
{
  "event": "playback_start",
  "session_id": "session-123",
  "device": "Living Room",
  "title": "Breaking Bad",
  "media_type": "Series",
  "item": { "Id": "item-456", "Name": "Breaking Bad" },
  "timestamp": "2024-01-15T10:30:00Z",
  "source": "jellyfin"
}
```

### UniFi Events

```json
{
  "event": "device_status_changed",
  "device_id": "device-uuid",
  "device_name": "Living Room AP",
  "ip_address": "192.168.1.100",
  "old_status": "disconnected",
  "new_status": "connected",
  "timestamp": "2024-01-15T10:30:00Z",
  "source": "unifi"
}
```

---

## Next Steps

1. **Configure all three emitters** with your credentials
2. **Verify registration** in mesh registry
3. **Subscribe to event topics** and confirm events flowing
4. **Build n8n workflows** that respond to emitter events
5. **Create custom agents** that process emitter data

---

**Emitters are now live. Your infrastructure is speaking to ARK.**
