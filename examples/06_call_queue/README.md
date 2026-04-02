# 06 — Call Queue with Hold Music

Puts callers on hold and retries connecting to an agent on each cycle. After a configurable number of failed attempts, the caller is offered the option to leave a voicemail.

## Call Flow

```
/answer
  └── "All agents are busy. Please hold."
        └── Hold cycle 1
              ├── Play hold music + Wait N seconds
              └── Try Dial to AGENT_NUMBER (15s ring timeout)
                    ├── Agent answers → /dial-complete → Hangup
                    └── No answer → Hold cycle 2
                          ├── Play hold music + Wait N seconds
                          └── Try Dial again
                                ├── Agent answers → Done
                                └── No answer → Hold cycle 3
                                      └── (after MAX_WAIT_CYCLES)
                                            └── "Sorry, please leave a message."
                                                  └── Record voicemail → Hangup
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_NUMBER` | `FROM_NUMBER` | Number to dial for agent |
| `MAX_WAIT_CYCLES` | `3` | Max hold attempts before voicemail |
| `HOLD_WAIT_SECS` | `20` | Seconds of hold music per cycle |
| `HOLD_MUSIC_URL` | Google beep | URL to MP3 hold music |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/answer` | Entry point — greeting |
| POST | `/queue-hold` | Plays hold music + wait per cycle |
| POST | `/queue-try-agent` | Dials the agent number |
| POST | `/dial-complete` | Callback after Dial — agent answered or not |
| POST | `/queue-voicemail` | Fallback voicemail after max retries |
| POST | `/voicemail-done` | Action URL when recording ends |
| POST | `/voicemail-file` | Callback when MP3 is ready |
| POST | `/hangup` | Call ended webhook |
| GET  | `/health` | Health check |

## Hold Music

Set `HOLD_MUSIC_URL` to any publicly accessible MP3 or OGG file:
```
HOLD_MUSIC_URL=https://example.com/hold-music.mp3
```

If left blank, the default is a short beep sound for testing.

## Setup

```bash
cp .env.example .env
# Set AGENT_NUMBER to the phone number of your support agent
pip install -r requirements.txt
python server.py
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID |
| `AGENT_NUMBER` | Yes | Phone number of the agent to connect to |
| `HOLD_MUSIC_URL` | No | URL to hold music MP3/OGG |
| `MAX_WAIT_CYCLES` | No | Max hold cycles before voicemail (default: `3`) |
| `HOLD_WAIT_SECS` | No | Seconds of hold per cycle (default: `20`) |
| `HTTP_PORT` | No | Server port (default: `8000`) |
| `PUBLIC_URL` | No | Production URL — skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |

## XML Elements Used

- `<Speak>` — queue messages and position updates
- `<Play loop="1">` — hold music
- `<Wait length silence>` — pause between retry attempts
- `<Dial><Number>` — connects caller to agent
- `<Record>` — fallback voicemail
- `<Redirect>` — loops between hold cycles
- `<Hangup>` — ends the call
