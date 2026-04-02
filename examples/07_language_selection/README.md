# 07 — Language Selection IVR

A bilingual IVR that greets callers in both English and Hindi, routes them to their preferred language, and provides a full sub-menu in that language including information and agent transfer.

## Call Flow

```
/answer
  └── "For English press 1. Hindi ke liye 2 dabaein."
        ├── 1 → English Menu
        │       ├── 1 → Product information (spoken in English)
        │       ├── 2 → Transfer to English-speaking agent
        │       └── 0 → Back to language selection
        └── 2 → Hindi Menu
                ├── 1 → Product information (spoken in Hindi)
                ├── 2 → Transfer to Hindi-speaking agent
                └── 0 → Back to language selection
```

## Supported Languages

| Code | Language | Voice |
|------|----------|-------|
| `en-US` | English (US) | `WOMAN` |
| `hi-IN` | Hindi (India) | `WOMAN` |

Additional languages supported by Vobiz can be added by creating new menu routes following the same pattern.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/answer` | Entry point — bilingual greeting |
| POST | `/lang-choice` | Routes to English or Hindi flow |
| POST | `/english-menu` | English sub-menu |
| POST | `/english-choice` | Routes English choices |
| POST | `/hindi-menu` | Hindi sub-menu |
| POST | `/hindi-choice` | Routes Hindi choices |
| POST | `/dial-complete` | Callback after any Dial ends |
| POST | `/hangup` | Call ended webhook |
| GET  | `/health` | Health check |

## Adding More Languages

To add a new language (e.g. Tamil — `ta-IN`):
1. Add a digit option in `/answer`
2. Create `/tamil-menu` and `/tamil-choice` routes
3. Use `<Speak language="ta-IN">` for TTS

## Setup

```bash
cp .env.example .env
# Set AGENT_NUMBER for transfers
pip install -r requirements.txt
python server.py
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID |
| `AGENT_NUMBER` | Yes | Number to transfer to for agent calls |
| `HTTP_PORT` | No | Server port (default: `8000`) |
| `PUBLIC_URL` | No | Production URL — skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |

## XML Elements Used

- `<Speak voice="WOMAN" language="en-US">` — English TTS
- `<Speak voice="WOMAN" language="hi-IN">` — Hindi TTS
- `<Gather inputType="dtmf" numDigits="1">` — language and menu selection
- `<Redirect>` — flow navigation
- `<Dial><Number>` — agent transfer
- `<Hangup>` — ends the call
