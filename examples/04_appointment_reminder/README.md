# 04 — Appointment Reminder

Calls a customer to remind them of an upcoming appointment. They can confirm, request to reschedule, or cancel. Cancellation requires a second confirmation to prevent accidental cancellations.

## Call Flow

```
/answer?name=John&date=April+5th&time=3+PM
  └── "You have an appointment on April 5th at 3 PM."
        └── Gather: 1=Confirm, 2=Reschedule, 3=Cancel, 9=Repeat
              ├── 1 → "Your appointment is confirmed." → Hangup
              ├── 2 → "Please call us to reschedule." → Hangup
              ├── 3 → "Are you sure you want to cancel?"
              │       └── Gather: 1=Yes cancel, 2=Keep appointment
              │             ├── 1 → "Appointment cancelled." → Hangup
              │             └── 2 → Back to main reminder
              └── 9 → Repeat reminder
```

## Passing Appointment Details

Appointment details are passed as query params to `/answer`:

```
/answer?name=John&date=April+5th&time=3+PM
```

Or set defaults in `.env`:
```
APPT_NAME=John
APPT_DATE=April 5th
APPT_TIME=3 PM
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/answer` | Entry point — plays appointment reminder |
| POST | `/appt-choice` | Routes confirm / reschedule / cancel |
| POST | `/appt-cancel-confirm` | Double-confirms cancellation |
| POST | `/hangup` | Call ended webhook |
| GET  | `/health` | Health check |

## Extending This Example

In `/appt-choice` and `/appt-cancel-confirm`, add your business logic:
- Write confirmation status to a database
- Send a confirmation SMS
- Update your CRM or calendar system

## Setup

```bash
cp .env.example .env
# Edit .env with your values
pip install -r requirements.txt
python server.py
```

Trigger an outbound call:
```bash
python ../../make_call.py --to +91XXXXXXXXXX \
  --answer-url "https://your-server/answer?name=John&date=April+5th&time=3+PM"
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID |
| `APPT_NAME` | No | Default customer name (default: `there`) |
| `APPT_DATE` | No | Default appointment date (default: `tomorrow`) |
| `APPT_TIME` | No | Default appointment time (default: `10 AM`) |
| `HTTP_PORT` | No | Server port (default: `8000`) |
| `PUBLIC_URL` | No | Production URL — skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |

## XML Elements Used

- `<Speak>` — reminder message and responses
- `<Gather inputType="dtmf" numDigits="1">` — collects caller's choice
- `<Redirect>` — navigates between flows
- `<Hangup>` — ends the call
