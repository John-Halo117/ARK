# UniFi Hook

## Purpose

UniFi can feed the MVP in two ways:

- preferred push hook: `POST http://localhost:5678/webhook/ark/unifi`
- optional controller/API polling from a sidecar or future workflow expansion

The Phase 0 workflow is optimized for push-first ingest so anomalies show up immediately.

## Webhook shape

The workflow accepts either a native controller event or a normalized envelope. A minimal native-style payload looks like this:

```json
{
  "event_type": "client_connected",
  "timestamp": "2026-04-10T20:12:00Z",
  "site": "default",
  "client_mac": "AA:BB:CC:DD:EE:FF",
  "hostname": "steamdeck",
  "ip": "192.168.1.80",
  "ap": "office-u7-pro"
}
```

## Recommended hook

If your UniFi environment can emit webhooks, point it directly at:

- `http://localhost:5678/webhook/ark/unifi`

If your controller only supports periodic polling, have the poller POST the raw JSON response to the same hook. The normalization step handles either event-style or snapshot-style payloads.

## Optional API polling

Use a low-rate poller outside the main workflow if you want steady-state inventory:

- clients: `GET https://<controller>/proxy/network/api/s/<site>/stat/sta`
- devices: `GET https://<controller>/proxy/network/api/s/<site>/stat/device`
- alarms: `GET https://<controller>/proxy/network/api/s/<site>/stat/alarm`

Recommended headers:

```http
Authorization: Bearer <UNIFI_API_KEY>
Accept: application/json
```

## Mapping notes

- `client_mac`, `mac`, `device_id`, `host`, or `ap` becomes `entity_id`.
- `event_type`, `type`, `alert_type`, and `subsystem` are normalized into an open `signal_key` like `network.default.client.connected`.
- `connected`, `status`, or the full raw object becomes `value`.
- Site, host, subsystem, and severity are preserved in `metadata`.

## Auto-detect note

If the controller sends a payload without a clear `entity_id` or `signal_key`, the workflow tries inference once through Ollama. If the payload is still ambiguous, it is stored as `unknown.raw` with the original payload in `raw_payload` and a classifier note in `metadata`.
