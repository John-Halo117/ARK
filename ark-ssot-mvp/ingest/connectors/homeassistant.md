# Home Assistant Hook

## Purpose

Home Assistant should push state changes into the MVP through the dedicated n8n hook:

- `POST http://localhost:5678/webhook/ark/homeassistant`

Use the local Mosquitto broker as an optional audit and fan-out path, not as a required ingest dependency for Phase 0. That keeps the ingest path linear and debuggable while still giving you a durable MQTT lane for edge devices.

## Recommended webhook payload

Send either the native state-change shape or a normalized envelope. The workflow accepts both.

```json
{
  "entity_id": "sensor.living_room_temperature",
  "state": "72.4",
  "attributes": {
    "device_class": "temperature",
    "unit_of_measurement": "F",
    "friendly_name": "Living Room Temperature"
  },
  "last_changed": "2026-04-10T20:10:30Z"
}
```

## Home Assistant webhook setup

Add a REST command and an automation that forwards selected state changes to the MVP hook.

```yaml
rest_command:
  ark_homeassistant_ingest:
    url: "http://localhost:5678/webhook/ark/homeassistant"
    method: POST
    content_type: "application/json"
    payload: >
      {
        "entity_id": "{{ trigger.entity_id }}",
        "state": {{ trigger.to_state.state | tojson }},
        "attributes": {{ trigger.to_state.attributes | tojson }},
        "last_changed": "{{ trigger.to_state.last_changed.isoformat() }}"
      }

automation:
  - alias: ARK ingest selected state changes
    mode: queued
    trigger:
      - platform: state
        entity_id:
          - sensor.living_room_temperature
          - binary_sensor.front_door
          - media_player.living_room_tv
    action:
      - service: rest_command.ark_homeassistant_ingest
```

## Optional MQTT mirror

Use the TLS broker to mirror the same payload for retained observability or downstream subscribers.

```yaml
mqtt:
  broker: 192.168.1.50
  port: 8883
  username: ark_homeassistant
  password: !secret ark_mqtt_password
  certificate: /ssl/ark-ca.crt
  client_cert: /ssl/homeassistant.crt
  client_key: /ssl/homeassistant.key

automation:
  - alias: ARK MQTT mirror
    mode: queued
    trigger:
      - platform: state
        entity_id:
          - sensor.living_room_temperature
          - binary_sensor.front_door
    action:
      - service: mqtt.publish
        data:
          topic: "ark/edge/homeassistant/{{ trigger.entity_id | replace('.', '/') }}"
          qos: 1
          retain: false
          payload: >
            {
              "entity_id": "{{ trigger.entity_id }}",
              "state": {{ trigger.to_state.state | tojson }},
              "attributes": {{ trigger.to_state.attributes | tojson }},
              "last_changed": "{{ trigger.to_state.last_changed.isoformat() }}"
            }
```

## Mapping notes

- `entity_id` becomes the canonical `entity_id`.
- `attributes.device_class` and `attributes.unit_of_measurement` help derive `signal_key`.
- `state` is coerced into boolean, number, or string when possible.
- `attributes` is preserved in `metadata.original_attributes`.

## Unknown payload note

If the payload does not provide enough structure to derive `signal_key`, `entity_id`, or `value`, the workflow asks Ollama to classify it. If classification is still uncertain, the event is stored as:

```json
{
  "signal_key": "unknown.raw",
  "classifier_status": "fallback"
}
```

The original Home Assistant payload is preserved in `raw_payload`, so no event is silently discarded.
