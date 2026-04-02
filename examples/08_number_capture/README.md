# 08 — Phone Number Capture (DTMF + # Terminator)

Prompts the caller to enter a 10-digit phone number using their keypad, terminated by pressing `#`. The number is read back digit by digit and the caller confirms, re-enters, or cancels.

## Call Flow

```
/answer
  └── "Enter your 10-digit number followed by #. You have 15 seconds."
        └── <Gather finishOnKey="#" timeout="15">
              └── /number-received
                    ├── Invalid / empty → "Try again." → back to /answer
                    └── Valid (10 digits) → Read back: "You entered: 9, 8, 7, 6..."
                          └── Gather: 1=Confirm, 2=Re-enter, 3=Cancel
                                ├── 1 → "Number saved." → Hangup
                                ├── 2 → Back to /answer
                                └── 3 → "Cancelled." → Hangup
```

## Key Feature: `finishOnKey="#"`

```xml
<Gather inputType="dtmf" finishOnKey="#" timeout="15">
```

- Caller enters digits and presses `#` to submit
- If 15 seconds pass with no input, Gather exits (no number entered)
- The `#` key itself is **not** included in the captured `Digits`

## Validation

Basic validation checks that the input is exactly 10 digits (Indian mobile number format). To adjust for other formats, edit `_is_valid_number()` in `server.py`:

```python
def _is_valid_number(number: str) -> bool:
    return bool(re.fullmatch(r"\d{10}", number))
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/answer` | Entry point — prompts for number input |
| POST | `/number-received` | Validates and reads back the captured number |
| POST | `/number-confirm` | Handles confirm / re-enter / cancel |
| POST | `/number-received-repeat` | Re-reads number after invalid key press |
| POST | `/hangup` | Call ended webhook |
| GET  | `/health` | Health check |

## Saving the Number

In `/number-confirm` when `digit == "1"`, add your persistence logic:

```python
# Save to your database
db.save_phone_number(call_uuid=call_uuid, number=number)

# Or call an external API
requests.post("https://your-crm.com/api/contacts", json={"phone": number})
```

## Setup

```bash
cp .env.example .env
pip install -r requirements.txt
python server.py
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

- `<Speak>` — instructions and readback
- `<Gather inputType="dtmf" finishOnKey="#" timeout="15">` — captures digits until `#`
- `<Redirect>` — loops back on invalid input
- `<Hangup>` — ends the call
