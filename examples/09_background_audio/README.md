# 09 — Background Audio via Conference + Play API

Play a background audio file continuously and in parallel with the live conversation — similar to audio mixing. Uses the Vobiz `<Conference>` XML element to join all parties into a room, then calls the Conference Member Play API server-side to inject background audio to all members simultaneously.

## How It Works

```
Caller dials in
      │
      ▼
POST /answer  →  returns <Conference>BackgroundAudioRoom</Conference>
      │
      ▼
Caller joins conference room
      │
      ▼
Vobiz fires conference-event (ConferenceAction=entered)
      │
      ▼
Server calls Conference Member Play API → background audio starts on all members
      │
      ▼
asyncio loop re-triggers Play API every AUDIO_LOOP_INTERVAL_SECS
      │
      ▼
Caller hears: live conversation + background audio simultaneously
```

**Key insight:** The Conference Play API injects audio directly into the conference mix — all members hear it alongside each other, achieving true background audio mixing without any client-side processing.

## Call Flow

```
/answer
  └── <Speak> "Welcome, connecting you now..."
        └── <Conference callbackUrl="/conference-event"> BackgroundAudioRoom
              │
              ├── conference-event (entered) → launch background_audio_loop task
              │     └── loop: Play API → wait AUDIO_LOOP_INTERVAL_SECS → repeat
              │
              └── conference-event (exited/ConfStop) → stop loop
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/answer` | Entry point — returns `<Conference>` XML |
| POST | `/conference-event` | Conference lifecycle webhook (member join/leave) |
| POST | `/hangup` | Call ended webhook — cleanup |
| POST | `/trigger-background` | Manually start/restart background audio |
| POST | `/stop-background` | Stop background audio (conference stays active) |
| GET  | `/status` | Live state: conference members + audio play status |
| GET  | `/health` | Health check + public URL |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VOBIZ_AUTH_ID` | — | **Required.** Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | — | **Required.** Vobiz account auth token |
| `FROM_NUMBER` | — | **Required.** Your Vobiz DID number |
| `CONFERENCE_NAME` | `BackgroundAudioRoom` | Conference room name |
| `BACKGROUND_AUDIO_URL` | Google beep | HTTPS URL to MP3/WAV background audio |
| `AUDIO_LOOP_INTERVAL_SECS` | `30` | Seconds between loop re-triggers — set to ≈ audio file duration |
| `HTTP_PORT` | `8000` | Server port |
| `PUBLIC_URL` | — | Production URL — skips ngrok if set |
| `NGROK_AUTH_TOKEN` | — | Optional ngrok auth token for local dev |

## Setup

```bash
cd examples/09_background_audio
cp .env.example .env
# Edit .env — fill in VOBIZ_AUTH_ID, VOBIZ_AUTH_TOKEN, FROM_NUMBER, BACKGROUND_AUDIO_URL
pip install -r requirements.txt
python server.py
```

Then in your **Vobiz dashboard**, set your phone number's **Answer URL** to:
```
POST https://<your-public-url>/answer
```

## Vobiz Dashboard Configuration

1. Go to **Voice → Applications** in the Vobiz console
2. Set **Answer URL** → `POST https://<your-url>/answer`
3. Set **Hangup URL** → `POST https://<your-url>/hangup`
4. The conference event callback is set automatically via the `<Conference callbackUrl=...>` XML attribute — no extra dashboard config needed

## Control API

### Trigger background audio manually
```bash
curl -X POST https://<your-url>/trigger-background

# With a different audio URL
curl -X POST https://<your-url>/trigger-background \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/new-music.mp3"}'
```

### Stop background audio
```bash
curl -X POST https://<your-url>/stop-background
```

### Check live status
```bash
curl https://<your-url>/status
```

Example response:
```json
{
  "conference_name": "BackgroundAudioRoom",
  "conference_active": true,
  "conference_started_at": "2026-04-02T10:30:00.000000",
  "member_count": 2,
  "members": {
    "17": {"call_uuid": "abc-123", "joined_at": "2026-04-02T10:30:00"},
    "18": {"call_uuid": "def-456", "joined_at": "2026-04-02T10:30:15"}
  },
  "audio_url": "https://example.com/background.mp3",
  "audio_playing": true,
  "play_count": 3,
  "last_play_at": "2026-04-02T10:31:30.000000",
  "loop_active": true
}
```

## Audio Looping

The Conference Play API plays an audio file **once**. To achieve continuous background audio, this example uses an `asyncio` loop task that:

1. Calls the Play API → audio starts playing to all conference members
2. Waits `AUDIO_LOOP_INTERVAL_SECS` seconds (≈ duration of your audio file)
3. Calls Play API again → seamless continuation
4. Repeats until `POST /stop-background` is called or the conference ends

**Tip:** Set `AUDIO_LOOP_INTERVAL_SECS` to 1–2 seconds *less* than your audio file's actual duration to avoid gaps between loops.

## Adding a Second Party (Bot / Agent)

To have a bot or agent also join the same conference (so all three — caller, agent, and background audio — are mixed together):

```python
# After the caller is in the conference, dial your bot/agent into the same room
xml = """
<Response>
    <Conference>BackgroundAudioRoom</Conference>
</Response>
"""
# Return this XML from your bot's answer URL, or use the Vobiz Make Call API
# to dial the agent and redirect them to the same conference
```

## XML Elements Used

- `<Speak>` — greeting message to caller
- `<Conference callbackUrl="...">` — joins caller into named room, fires lifecycle events
- Conference Member Play API — injects background audio into the mix (not XML — REST API call from server)
