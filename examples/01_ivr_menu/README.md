# 01 — Multi-Level IVR Menu

A multi-level Interactive Voice Response (IVR) system built on the Vobiz XML API. Callers navigate a two-tier menu using keypad (DTMF) input.

## Call Flow

```
/answer
  └── Main Menu
        ├── 1 → Sales sub-menu
        │       ├── 1 → Product information (spoken)
        │       ├── 2 → Transfer to sales rep
        │       └── 9 → Back to main menu
        ├── 2 → Support sub-menu
        │       ├── 1 → Connect to tech support
        │       ├── 2 → Raise a ticket (automated)
        │       └── 9 → Back to main menu
        ├── 3 → Billing sub-menu
        │       ├── 1 → Bill information (spoken)
        │       ├── 2 → Transfer to billing team
        │       └── 9 → Back to main menu
        ├── 0 → Direct transfer to operator
        └── 9 → Repeat main menu
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/answer` | Entry point — plays main menu |
| POST | `/ivr-main-choice` | Routes DTMF digit from main menu |
| POST | `/ivr-sales` | Sales sub-menu |
| POST | `/ivr-sales-choice` | Routes sales choice |
| POST | `/ivr-support` | Support sub-menu |
| POST | `/ivr-support-choice` | Routes support choice |
| POST | `/ivr-billing` | Billing sub-menu |
| POST | `/ivr-billing-choice` | Routes billing choice |
| POST | `/ivr-operator` | Transfers directly to operator |
| POST | `/dial-complete` | Callback after any Dial ends |
| POST | `/hangup` | Call ended webhook |
| GET  | `/health` | Health check |

## Setup

```bash
cp .env.example .env
# Edit .env with your values
pip install -r requirements.txt
python server.py
```

The server prints the **Answer URL** and **Hangup URL** on startup. Paste them into your Vobiz console.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID — used as caller ID for transfers |
| `HTTP_PORT` | No | Server port (default: `8000`) |
| `PUBLIC_URL` | No | Production URL — skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |

## XML Elements Used

- `<Gather inputType="dtmf">` — collects keypad input
- `<Speak voice="WOMAN" language="en-US">` — text-to-speech
- `<Redirect>` — transfers call flow to another endpoint
- `<Dial><Number>` — connects caller to a phone number
- `<Hangup>` — ends the call
