# 05 — Customer Feedback Survey

A 3-question post-call DTMF survey. All responses are logged per call UUID and can be saved to a database or CRM.

## Call Flow

```
/answer
  └── "Thank you for being a customer. Quick 3-question survey."
        └── Q1: Rate our service 1-5
              └── Q2: Would you recommend us? (1=Yes, 2=No)
                    └── Q3: Overall experience (1=Excellent, 2=Good, 3=Needs improvement)
                          └── "Thank you! Your feedback is valuable." → Hangup
```

If a caller doesn't press anything within the timeout, the question is skipped and the survey continues to the next question.

## Questions

| # | Question | Valid Input |
|---|----------|-------------|
| Q1 | Rate our service | `1`–`5` (1=very poor, 5=excellent) |
| Q2 | Would you recommend us? | `1`=Yes, `2`=No |
| Q3 | Overall experience | `1`=Excellent, `2`=Good, `3`=Needs improvement |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/answer` | Entry point — intro message |
| POST | `/survey-q1` | Question 1 |
| POST | `/survey-q1-result` | Collects Q1 answer → goes to Q2 |
| POST | `/survey-q2` | Question 2 |
| POST | `/survey-q2-result` | Collects Q2 answer → goes to Q3 |
| POST | `/survey-q3` | Question 3 |
| POST | `/survey-q3-result` | Collects Q3 answer → goes to done |
| POST | `/survey-done` | Thank you + logs full survey result |
| POST | `/hangup` | Call ended webhook |
| GET  | `/health` | Health check |

## Survey Results

All answers are logged at `/survey-done`:
```
Survey complete — CallUUID=xxx | Q1=4 | Q2=yes | Q3=excellent
```

To save results, add your persistence code in `/survey-done`:
```python
# e.g. save to database
db.save_survey(call_uuid, q1=q1, q2=q2, q3=q3)
```

## Setup

```bash
cp .env.example .env
pip install -r requirements.txt
python server.py
```

For outbound surveys, trigger via `make_call.py`:
```bash
python ../../make_call.py --to +91XXXXXXXXXX
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID |
| `HTTP_PORT` | No | Server port (default: `8000`) |
| `PUBLIC_URL` | No | Production URL — skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |

## XML Elements Used

- `<Speak>` — question prompts and acknowledgements
- `<Gather inputType="dtmf" numDigits="1" executionTimeout="10">` — collects each answer
- `<Redirect>` — chains questions together
- `<Hangup>` — ends after thank-you message
