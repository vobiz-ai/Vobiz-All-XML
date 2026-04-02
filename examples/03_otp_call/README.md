# 03 — OTP / Verification Call

Calls a number and reads out a one-time password (OTP) digit by digit with natural pauses. The caller can press 1 to hear the OTP again.

## Call Flow

```
/answer?otp=482916
  └── "Your one-time password is: 4, 8, 2, 9, 1, 6"
        └── Repeated once more automatically
              └── Gather: "Press 1 to hear again."
                    ├── 1 → /otp-choice → Read OTP again → Hangup
                    └── (timeout / other) → "Thank you. Goodbye!" → Hangup
```

## Passing the OTP

The OTP can be provided in two ways:

**Option 1 — Query param on the Answer URL** (recommended for dynamic OTPs):
```
https://your-server/answer?otp=482916
```
Set this as the Answer URL when triggering the outbound call from your system.

**Option 2 — `.env` default** (for testing):
```
OTP_CODE=123456
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/answer` | Entry point — reads OTP to caller |
| POST | `/otp-choice` | Handles "press 1 to repeat" |
| POST | `/hangup` | Call ended webhook |
| GET  | `/health` | Health check |

## How the Digit Spacing Works

The OTP `482916` is converted to `4,  8,  2,  9,  1,  6` before being passed to `<Speak>`. The commas create a natural pause between each digit in TTS so callers can write them down clearly.

## Setup

```bash
cp .env.example .env
# Edit .env with your values
pip install -r requirements.txt
python server.py
```

Trigger an outbound call using `make_call.py` from the root of the repo:
```bash
python ../../make_call.py --to +91XXXXXXXXXX --answer-url "https://your-ngrok-url/answer?otp=482916"
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID (caller ID for outbound calls) |
| `TO_NUMBER` | No | Default destination number |
| `OTP_CODE` | No | Fallback OTP for testing (default: `123456`) |
| `HTTP_PORT` | No | Server port (default: `8000`) |
| `PUBLIC_URL` | No | Production URL — skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |

## XML Elements Used

- `<Speak>` — reads out the OTP with digit spacing
- `<Gather inputType="dtmf" numDigits="1">` — listens for repeat request
- `<Hangup>` — ends the call
