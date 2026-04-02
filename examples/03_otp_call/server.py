"""
03_otp_call/server.py — OTP Verification Call (with generator, store + verify API)
====================================================================================
YOUR APP interacts via:
  POST /send-otp              → generate OTP + trigger outbound Vobiz call
                                body: {"phone": "+91XXXXXXXXXX"}
                                returns: {"status": "call_initiated", "expires_in": 300}

  POST /verify-otp            → check the OTP the user typed on your website
                                body: {"phone": "+91XXXXXXXXXX", "otp": "482916"}
                                returns: {"verified": true} or {"verified": false, "reason": "..."}

  GET  /otp-status/{phone}    → delivery status (pending/calling/delivered/expired/used)

VOBIZ calls:
  POST /answer                → reads OTP aloud to the called party
  POST /otp-choice            → handles "press 1 to repeat"
  POST /hangup                → cleanup
"""

import os
import logging
import uvicorn
import requests
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from pyngrok import ngrok, conf

from otp_store import OTPStore

load_dotenv(dotenv_path="../../.env")

HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
FROM_NUMBER = os.getenv("FROM_NUMBER", "")
VOBIZ_AUTH_ID = os.getenv("VOBIZ_AUTH_ID", "")
VOBIZ_AUTH_TOKEN = os.getenv("VOBIZ_AUTH_TOKEN", "")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("otp_call")

app = FastAPI(title="OTP Call — Vobiz Example 03")
BASE_URL: str = ""
store = OTPStore()


def setup_ngrok() -> str:
    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN
    tunnel = ngrok.connect(HTTP_PORT, "http")
    url = tunnel.public_url.replace("http://", "https://")
    logger.info(f"ngrok tunnel: {url}")
    return url


def _trigger_vobiz_call(to_number: str, answer_url: str) -> str:
    """Trigger an outbound Vobiz call. Returns the call UUID."""
    payload = {
        "from": FROM_NUMBER,
        "to": to_number,
        "answer_url": answer_url,
        "answer_method": "POST",
        "hangup_url": f"{BASE_URL}/hangup",
        "hangup_method": "POST",
    }
    resp = requests.post(
        f"https://api.vobiz.ai/api/v1/Account/{VOBIZ_AUTH_ID}/Call/",
        json=payload,
        headers={"X-Auth-ID": VOBIZ_AUTH_ID, "X-Auth-Token": VOBIZ_AUTH_TOKEN},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("api_id", "")


def _spell_otp(otp: str) -> str:
    """
    One <Speak> per digit + a 1-second <Wait> between each one.
    Single digit in its own tag forces TTS to say the number, not a word.
    Wait gives caller time to write it down.
    """
    parts = []
    for d in otp:
        parts.append(f'<Speak voice="WOMAN" language="en-US">{d}</Speak>')
        parts.append('<Wait length="1"/>')
    return "\n    ".join(parts)


def _normalize_phone(raw: str) -> str:
    """
    Fix URL encoding: Vobiz decodes '+' as a space in query params.
    ' 919148227303' → '+919148227303'
    """
    raw = raw.strip()
    if raw and not raw.startswith("+"):
        raw = "+" + raw.lstrip()
    return raw


# ===========================================================================
# YOUR APP API
# ===========================================================================


class SendOTPRequest(BaseModel):
    phone: str


class VerifyOTPRequest(BaseModel):
    phone: str
    otp: str


@app.post("/send-otp")
async def send_otp(body: SendOTPRequest):
    """
    1. Generate a 6-digit OTP for the phone number.
    2. Trigger a Vobiz outbound call to read it aloud.
    3. Return call status to your app.
    """
    phone = body.phone.strip()
    otp = store.generate(phone)
    logger.info(f"OTP generated for {phone}: {otp}")

    answer_url = f"{BASE_URL}/answer?phone={quote(phone)}"  # encode + as %2B
    try:
        call_uuid = _trigger_vobiz_call(phone, answer_url)
        store.bind_call(phone, call_uuid)
        logger.info(f"Outbound call triggered — phone={phone}, call_uuid={call_uuid}")
    except Exception as e:
        logger.error(f"Failed to trigger call: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to trigger call: {e}")

    return JSONResponse(
        {
            "status": "call_initiated",
            "phone": phone,
            "call_uuid": call_uuid,
            "expires_in_seconds": 300,
            "max_attempts": 3,
        }
    )


@app.post("/verify-otp")
async def verify_otp(body: VerifyOTPRequest):
    """
    Verify the OTP the user typed on your website/app.
    Returns {"verified": true} or {"verified": false, "reason": "..."}
    """
    success, reason = store.verify(body.phone.strip(), body.otp.strip())
    logger.info(f"OTP verify — phone={body.phone}, result={reason}")
    return JSONResponse({"verified": success, "reason": reason})


@app.get("/otp-status/{phone}")
async def otp_status(phone: str):
    """Check the delivery status of an OTP call."""
    return JSONResponse(store.status(phone))


# ===========================================================================
# VOBIZ WEBHOOKS
# ===========================================================================


@app.post("/answer")
async def answer(request: Request):
    """Vobiz calls this when the outbound call is answered."""
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    raw_phone = request.query_params.get("phone", "")
    phone = _normalize_phone(raw_phone)  # fix '+' decoded as space

    # 1st: look up by call UUID (most reliable)
    record = store.get_by_call_uuid(call_uuid)

    # 2nd: fall back to phone number lookup
    if not record and phone:
        record = store._store.get(phone)

    otp = record.otp if record else None
    logger.info(
        f"Reading OTP aloud — CallUUID={call_uuid}, phone={phone}, found={otp is not None}"
    )

    if not otp:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Sorry, we could not retrieve your one-time password. Please request a new OTP. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    spelled = _spell_otp(otp)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Hello! This is a verification call from Acme Corporation.
        Your one-time password is:
    </Speak>
    {spelled}
    <Speak voice="WOMAN" language="en-US">I repeat, your one-time password is:</Speak>
    {spelled}
    <Gather action="{BASE_URL}/otp-choice?call_uuid={call_uuid}" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="8">
        <Speak voice="WOMAN" language="en-US">
            To hear your OTP again, press 1. Otherwise, you may hang up now. Thank you!
        </Speak>
    </Gather>
    <Speak voice="WOMAN" language="en-US">Thank you for using Acme services. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/otp-choice")
async def otp_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    call_uuid = request.query_params.get("call_uuid", "unknown")

    record = store.get_by_call_uuid(call_uuid)
    otp = record.otp if record else None

    if digit == "1" and otp:
        spelled = _spell_otp(otp)
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Your one-time password is:</Speak>
    {spelled}
    <Speak voice="WOMAN" language="en-US">Thank you. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    else:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Thank you. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/hangup")
async def hangup(request: Request):
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    store.mark_delivered(call_uuid)
    store.cleanup_expired()
    logger.info(f"Call ended — CallUUID={call_uuid}")
    return Response(content="OK", status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok", "base_url": BASE_URL, "example": "03_otp_call"}


def main():
    global BASE_URL
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()

    logger.info("=" * 60)
    logger.info("  03 — OTP Verification Call")
    logger.info(f"  Send OTP    : POST {BASE_URL}/send-otp")
    logger.info(f"  Verify OTP  : POST {BASE_URL}/verify-otp")
    logger.info(f"  OTP Status  : GET  {BASE_URL}/otp-status/{{phone}}")
    logger.info(f"  Answer URL  : {BASE_URL}/answer  (set in Vobiz)")
    logger.info(f"  Hangup URL  : {BASE_URL}/hangup")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
