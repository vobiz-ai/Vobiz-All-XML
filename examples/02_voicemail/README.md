# 02 — Voicemail / Leave a Message

Records a caller's voicemail message and notifies your system via two callbacks — one immediately when recording ends, and one when the MP3 file is ready to download.

## Call Flow

```
/answer
  └── Greeting: "Please leave a message after the beep. Press * when done."
        └── <Record maxLength="60" finishOnKey="*" playBeep="true">
              ├── action → /voicemail-done   (fires immediately on stop)
              │     └── "Thank you for your message of X seconds." → Hangup
              └── callbackUrl → /voicemail-file  (fires when MP3 is ready)
                    └── Download / process recording here
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/answer` | Entry point — plays greeting and starts recording |
| POST | `/voicemail-done` | Action URL — fires immediately when recording ends |
| POST | `/voicemail-file` | Callback URL — fires when MP3 file is ready |
| POST | `/hangup` | Call ended webhook |
| GET  | `/health` | Health check |

## Webhook Data

### `/voicemail-done` receives:
| Field | Description |
|-------|-------------|
| `RecordUrl` | URL to download the recording |
| `RecordingDuration` | Duration in seconds |
| `RecordingID` | Unique ID for this recording |
| `RecordingEndReason` | `finishKey`, `timeout`, `maxLength`, or `hangup` |
| `CallUUID` | Unique call identifier |

### `/voicemail-file` receives:
Same fields as above — use `RecordUrl` to download the MP3.

## Extending This Example

In `voicemail-file`, you can:
- Upload to AWS S3
- Transcribe with OpenAI Whisper
- Send email notification with the recording link
- Push to Slack or a CRM

## Setup

```bash
cp .env.example .env
# Edit .env with your values
pip install -r requirements.txt
python server.py
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `HTTP_PORT` | No | Server port (default: `8000`) |
| `PUBLIC_URL` | No | Production URL — skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |

## XML Elements Used

- `<Speak>` — greeting message
- `<Record maxLength action callbackUrl finishOnKey playBeep fileFormat>` — records caller audio
- `<Hangup>` — ends the call
