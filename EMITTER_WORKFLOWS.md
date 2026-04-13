# ARK Emitter-Driven Workflows

Real-world examples of using emitter events with ARK agents and n8n.

---

## Pattern 1: Anomaly Detection → Action

### Detect Temperature Anomaly, Adjust Climate

**NATS Event Flow:**
```
Home Assistant emits temperature metric
  ↓
OpenWolf detects anomaly (temp spike/drop)
  ↓
Triggers alert event
  ↓
n8n listens on ark.anomaly.detected
  ↓
Queries Home Assistant climate
  ↓
Adjusts temperature setpoint or turns on fan
```

**Implementation:**

n8n Webhook Trigger:
```json
{
  "topic": "ark.anomaly.detected",
  "condition": "metric contains temperature"
}
```

Process Node:
```javascript
// Analyze severity
const isCold = msg.value < 15;
const isHot = msg.value > 30;

return {
  metric: msg.metric,
  value: msg.value,
  action: isCold ? "increase_heat" : isHot ? "increase_cooling" : "normal"
}
```

Action Node:
```bash
# Call Home Assistant capability to adjust climate
ark.call.homeassistant.state.device_update
{
  "entity_id": "climate.living_room",
  "state": "heat" or "cool"
}
```

---

## Pattern 2: Media Event → Automation

### Jellyfin Playback → Home Automation

**NATS Event Flow:**
```
Jellyfin emits playback_start
  ↓
n8n webhook triggers
  ↓
Query Home Assistant for current state
  ↓
Dim lights
  ↓
Close blinds
  ↓
Pause other media
```

**n8n Configuration:**

Trigger: Webhook
```json
POST /webhook/jellyfin-playback
{
  "event": "playback_start",
  "title": "Breaking Bad",
  "device": "Living Room"
}
```

Actions:
```bash
1. Query HA lights status
   ark.call.homeassistant.sensor.reading {
     "entity_id": "light.living_room"
   }

2. Dim lights
   ark.call.homeassistant.state.device_update {
     "entity_id": "light.living_room",
     "state": "50"  # 50% brightness
   }

3. Close blinds
   ark.call.homeassistant.state.device_update {
     "entity_id": "cover.living_room_blinds",
     "state": "closed"
   }

4. Pause other speakers
   ark.call.homeassistant.state.device_update {
     "entity_id": "media_player.kitchen",
     "state": "paused"
   }
```

---

## Pattern 3: Network Event → Alert

### UniFi Device Offline → Notification

**NATS Event Flow:**
```
UniFi emits device_offline
  ↓
OpenWolf checks network health
  ↓
If critical device: ASHI drops
  ↓
Triggers escalation
  ↓
Composio sends email/Slack alert
```

**n8n Workflow:**

Trigger: NATS subscription
```
Topic: ark.event.network.device
Filter: event == "device_status_changed" AND new_status == "offline"
```

Lookup: Is this device critical?
```javascript
const criticalDevices = ["Main_AP", "WAN_Gateway"];
const isCritical = criticalDevices.includes(msg.device_name);

return {
  device: msg.device_name,
  severity: isCritical ? "critical" : "warning"
}
```

Action: Send Alert
```bash
# If critical, send via Composio
ark.call.composio.external.email {
  "to": "admin@example.com",
  "subject": "CRITICAL: Network device offline - " + device,
  "body": "Device has been offline for 5+ minutes"
}

# Also send Slack
ark.call.composio.external.slack {
  "channel": "#network-alerts",
  "message": "⚠️ OFFLINE: " + device
}
```

---

## Pattern 4: Multi-Source Correlation

### Combine HA + Jellyfin + UniFi Events

**Complex Workflow:**

Detect presence + media activity + network health simultaneously:

```
Trigger: Check every minute
  ↓
1. Query HA: Any motion sensors triggered?
2. Query Jellyfin: Is media playing?
3. Query UniFi: Network quality OK?
  ↓
If (presence == true) AND (playback == active) AND (network == good):
  ↓
  Set "Movie Time" mode:
  - Dim lights
  - Set climate to comfort
  - Disable notifications
  ↓
Log correlation to DuckDB for pattern analysis
```

**n8n Config:**

```javascript
// Fetch all three data sources in parallel
const [haState, jellyfinPlayback, unifiHealth] = await Promise.all([
  queryCapability("homeassistant.sensor.reading", "motion_sensor"),
  queryCapability("jellyfin.playback.status", {}),
  queryCapability("unifi.network.health", {})
]);

// Correlate
const isMovieTime = 
  haState.state === "on" && 
  jellyfinPlayback.active_sessions > 0 &&
  unifiHealth.health_score > 85;

// Take action
if (isMovieTime) {
  await homeAssistant.setScene("movie_mode");
  await duckdb.log({
    event: "movie_time_activated",
    sources: ["ha", "jellyfin", "unifi"],
    timestamp: now()
  });
}
```

---

## Pattern 5: Learning & Adaptation

### Track Patterns, Optimize Automatically

**Workflow:**

```
1. Log every state change to DuckDB
   - What changed
   - When
   - What was playing (Jellyfin)
   - Network conditions (UniFi)
   - Climate state (HA)

2. OpenWolf analyzes patterns
   - When does network degrade?
   - When do anomalies happen?
   - Correlations between events

3. Generate recommendations
   - "Network degrades when X plays"
   - "Temperature anomalies happen at Y time"
   - "Device goes offline when Z happens"

4. Implement learnings
   - Auto-switch to better quality when network good
   - Pre-cool house before hot times
   - Optimize device settings
```

**DuckDB Queries:**

```sql
-- Find patterns: when does network get congested?
SELECT 
  HOUR(timestamp) as hour,
  AVG(device_count) as avg_devices,
  AVG(client_count) as avg_clients
FROM network_metrics
GROUP BY HOUR(timestamp)
ORDER BY avg_clients DESC;

-- Correlate playback with network quality
SELECT 
  j.media_type,
  AVG(u.health_score) as avg_network_health
FROM jellyfin_events j
JOIN unifi_metrics u ON DATE(j.timestamp) = DATE(u.timestamp)
WHERE j.event = 'playback_start'
GROUP BY j.media_type;

-- Find anomaly causes
SELECT 
  h.entity_id,
  h.old_state,
  h.new_state,
  o.anomaly_type,
  o.severity
FROM homeassistant_events h
JOIN openwolf_anomalies o ON DATEDIFF(second, h.timestamp, o.timestamp) < 60
WHERE o.is_anomaly = true
ORDER BY o.severity DESC;
```

---

## Pattern 6: Real-Time Correlation Agent

### Custom Agent to Correlate Events

Create `/agents/correlator/agent.py`:

```python
#!/usr/bin/env python3
import asyncio
import json
import nats
from collections import defaultdict
from datetime import datetime, timedelta

class CorrelatorAgent:
    def __init__(self):
        self.service_name = "correlator"
        self.capabilities = ["events.correlate", "patterns.detect"]
        self.recent_events = defaultdict(list)
        self.nats_url = "nats://nats:4222"
    
    async def subscribe_all_events(self):
        """Subscribe to all event topics"""
        nc = await nats.connect(self.nats_url)
        
        # Subscribe to all sources
        sub = await nc.subscribe("ark.event.*")
        
        async for msg in sub.messages:
            event = json.loads(msg.data.decode())
            source = event.get('source', 'unknown')
            
            # Store event with 5-minute TTL
            self.recent_events[source].append({
                "event": event,
                "timestamp": datetime.utcnow()
            })
            
            # Clean old events
            cutoff = datetime.utcnow() - timedelta(minutes=5)
            self.recent_events[source] = [
                e for e in self.recent_events[source]
                if e['timestamp'] > cutoff
            ]
            
            # Check for correlations
            await self.check_correlations()
    
    async def check_correlations(self):
        """Detect correlations between events"""
        ha_events = self.recent_events.get('homeassistant', [])
        jellyfin_events = self.recent_events.get('jellyfin', [])
        unifi_events = self.recent_events.get('unifi', [])
        
        # Find events within 2 minutes of each other
        if ha_events and jellyfin_events:
            for ha in ha_events:
                for jf in jellyfin_events:
                    diff = abs(
                        (ha['timestamp'] - jf['timestamp']).total_seconds()
                    )
                    if diff < 120:  # Within 2 minutes
                        # Correlation found
                        correlation = {
                            "type": "ha_jellyfin_correlation",
                            "ha_event": ha['event'],
                            "jellyfin_event": jf['event'],
                            "time_diff_seconds": diff,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        
                        # Emit correlation for other agents
                        await js.publish(
                            "ark.correlation.detected",
                            json.dumps(correlation).encode()
                        )
```

---

## Pattern 7: Reactive Home

### "Home Is Alive" - Emergent Behavior

**The system should feel alive:**

```
1. Person arrives home (UniFi detects new client)
   ↓
2. Home Assistant detects motion
   ↓
3. Lights gradually brighten
   ↓
4. Climate adjusts to comfort zone
   ↓
5. Media server wakes up
   ↓
6. Greetings play on speaker
   ↓
7. Home is ready

---

Person starts watching movie (Jellyfin emits playback_start)
   ↓
Home enters "Movie Mode"
   ↓
Lights dim progressively
   ↓
Temperature set to cool
   ↓
Network optimizes for streaming
   ↓
Notifications muted
   ↓
Experience is seamless

---

Person leaves (UniFi: no more clients)
   ↓
HA detects no motion for 10 minutes
   ↓
Home enters "Away Mode"
   ↓
Lights off
   ↓
Climate set to away temp
   ↓
Media paused
   ↓
Security armed
```

**n8n Implementation:**

Multi-node workflow that:
1. Subscribes to all three emitter topics
2. Correlates events in real-time
3. Executes scenes based on patterns
4. Learns which patterns work best
5. Adapts over time

---

## Testing Workflows

### Simulate HA State Change

```bash
docker exec ark-nats nats pub "ark.event.state.change" \
'{"entity_id":"light.bedroom","old_state":"off","new_state":"on","source":"homeassistant"}'
```

### Simulate Jellyfin Playback

```bash
docker exec ark-nats nats pub "ark.event.media.playback" \
'{"event":"playback_start","device":"Living Room","title":"Breaking Bad","source":"jellyfin"}'
```

### Simulate UniFi Device Offline

```bash
docker exec ark-nats nats pub "ark.event.network.device" \
'{"event":"device_status_changed","device_name":"Main AP","old_status":"connected","new_status":"offline","source":"unifi"}'
```

### Monitor All Events

```bash
docker exec ark-nats nats sub "ark.event.*" --raw
```

---

## Debugging Workflows

### Check Events Are Being Emitted

```bash
# Count events by source
docker exec ark-nats nats stream view ark.events --samples 100 | jq '.data.message.data | fromjson | .source' | sort | uniq -c
```

### Check Correlator Agent

```bash
curl http://localhost:7000/api/service/correlator | jq

# Or subscribe to correlations
docker exec ark-nats nats sub "ark.correlation.detected" --raw
```

### Verify n8n Webhook

```bash
curl -X POST http://localhost:5678/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"test":"data"}'
```

---

**Emitter workflows enable your home/infrastructure to react intelligently to events.**
