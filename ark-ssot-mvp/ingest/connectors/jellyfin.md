# Jellyfin Hook

## Purpose

Jellyfin should push media events into the MVP through:

- `POST http://localhost:5678/webhook/ark/jellyfin`

Polling is optional for backlog or reconciliation, but Phase 0 is built around webhook-first ingest so playback events are visible immediately.

## Webhook shape

The workflow accepts the common Jellyfin webhook plugin payload or a normalized envelope.

```json
{
  "NotificationType": "PlaybackStart",
  "Timestamp": "2026-04-10T20:15:00Z",
  "ItemId": "5b4b6f03f9b74a34b40f",
  "ItemType": "Episode",
  "Name": "S01E01",
  "SeriesName": "Example Show",
  "UserName": "trevl",
  "DeviceName": "Living Room TV"
}
```

## Webhook plugin target

Point the Jellyfin webhook plugin at:

- `http://localhost:5678/webhook/ark/jellyfin`

Keep the payload raw. The workflow extracts the right fields and preserves the original body in `raw_payload`.

## Optional API polling

For scheduled reconciliation or library inventory, poll as needed and POST the result to the same hook:

- sessions: `GET https://<jellyfin>/Sessions?api_key=<JELLYFIN_API_KEY>`
- item detail: `GET https://<jellyfin>/Items/<item-id>?api_key=<JELLYFIN_API_KEY>`
- users: `GET https://<jellyfin>/Users?api_key=<JELLYFIN_API_KEY>`

## Mapping notes

- `ItemId`, `SessionId`, `DeviceId`, or `UserId` becomes `entity_id`.
- `NotificationType` and `ItemType` are normalized into an open `signal_key` like `media.episode.playbackstart`.
- Playback details become `value`; source context stays in `metadata`.

## Auto-detect note

If the plugin sends a custom body that does not expose a clear item, session, or signal, the workflow sends it to Ollama for one inference pass. When inference cannot confidently classify it, the event is stored as `unknown.raw` and surfaced on the dashboard instead of being dropped.
