"""
08_number_capture/server.py — Phone Number Capture (with lead store + admin API)
==================================================================================
YOUR APP interacts via:
  GET  /leads                     → list all captured numbers
  GET  /leads/export.csv          → download all as CSV
  GET  /leads/analytics           → total, unique, duplicates, today count
  GET  /leads/{id}                → single lead detail
  DELETE /leads/{id}              → remove a lead

VOBIZ calls:
  POST /answer                    → "Enter your 10-digit number followed by #"
  POST /number-received           → validate + read back
  POST /number-confirm            → handle confirm / re-enter / cancel
  POST /number-received-repeat    → re-read number on invalid key
  POST /hangup
"""

import os
import re
import logging
import uvicorn

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse, PlainTextResponse
from dotenv import load_dotenv
from pyngrok import ngrok, conf

from lead_store import LeadStore

load_dotenv(dotenv_path="../../.env")

HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("number_capture")

app = FastAPI(title="Number Capture — Vobiz Example 08")
BASE_URL: str = ""
store = LeadStore()


def setup_ngrok() -> str:
    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN
    tunnel = ngrok.connect(HTTP_PORT, "http")
    url = tunnel.public_url.replace("http://", "https://")
    logger.info(f"ngrok tunnel: {url}")
    return url


def _spell_number(number: str) -> str:
    return ",  ".join(list(number))


def _is_valid(number: str) -> bool:
    return bool(re.fullmatch(r"\d{10}", number))


# ===========================================================================
# YOUR APP API
# ===========================================================================


@app.get("/leads/analytics")
async def leads_analytics():
    """Total, unique, duplicate count and today's count."""
    return JSONResponse(store.analytics())


@app.get("/leads/export.csv")
async def leads_export():
    """Download all captured numbers as CSV."""
    csv_data = store.export_csv()
    return PlainTextResponse(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@app.get("/leads")
async def list_leads(include_duplicates: bool = True):
    """List all captured leads. Pass ?include_duplicates=false to filter."""
    return JSONResponse(store.list_all(include_duplicates=include_duplicates))


@app.get("/leads/{lead_id}")
async def get_lead(lead_id: str):
    lead = store.get(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return JSONResponse(lead.to_dict())


@app.delete("/leads/{lead_id}")
async def delete_lead(lead_id: str):
    ok = store.delete(lead_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Lead not found")
    return JSONResponse({"status": "deleted", "id": lead_id})


# ===========================================================================
# VOBIZ WEBHOOKS
# ===========================================================================


@app.post("/answer")
async def answer(request: Request):
    form = await request.form()
    logger.info(
        f"Number capture call — CallUUID={form.get('CallUUID', '?')}, From={form.get('From', '?')}"
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/number-received" method="POST"
            inputType="dtmf"
            finishOnKey="#"
            timeout="15">
        <Speak voice="WOMAN" language="en-US">
            Welcome! Please enter your 10-digit mobile number,
            followed by the hash key.
            You have 15 seconds to enter your number.
        </Speak>
    </Gather>
    <Speak voice="WOMAN" language="en-US">We did not receive your number. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/number-received")
async def number_received(request: Request):
    form = await request.form()
    number = form.get("Digits", "").strip()
    call_uuid = form.get("CallUUID", "unknown")
    from_num = form.get("From", "unknown")
    logger.info(f"Number received: '{number}', CallUUID={call_uuid}")

    if not number:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">We did not receive any digits. Please try again.</Speak>
    <Redirect method="POST">{BASE_URL}/answer</Redirect>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    if not _is_valid(number):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        You entered {_spell_number(number)}.
        This does not appear to be a valid 10-digit number. Please try again.
    </Speak>
    <Redirect method="POST">{BASE_URL}/answer</Redirect>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    spelled = _spell_number(number)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">You entered:</Speak>
    <Speak voice="WOMAN" language="en-US">{spelled}</Speak>
    <Gather action="{BASE_URL}/number-confirm?number={number}&amp;call_uuid={call_uuid}&amp;from={from_num}"
            method="POST" inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            Press 1 to confirm this number.
            Press 2 to re-enter your number.
            Press 3 to cancel.
        </Speak>
    </Gather>
    <Speak voice="WOMAN" language="en-US">No response received. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/number-confirm")
async def number_confirm(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    number = request.query_params.get("number", "")
    call_uuid = request.query_params.get("call_uuid", "unknown")
    from_num = request.query_params.get("from", "unknown")
    spelled = _spell_number(number)

    if digit == "1":
        lead = store.save(number, from_num, call_uuid)
        dup_note = (
            " This number was previously registered." if lead.is_duplicate else ""
        )
        logger.info(
            f"Lead saved — id={lead.id}, number={number}, duplicate={lead.is_duplicate}"
        )
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Thank you! Your number {spelled} has been successfully registered.{dup_note}
        We will use this number to contact you. Have a great day! Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    elif digit == "2":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">No problem! Please enter your number again.</Speak>
    <Redirect method="POST">{BASE_URL}/answer</Redirect>
</Response>"""
    elif digit == "3":
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Cancelled. No number has been saved. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/number-confirm?number={number}&amp;call_uuid={call_uuid}&amp;from={from_num}"
            method="POST" inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            Your number is {spelled}.
            Press 1 to confirm, 2 to re-enter, 3 to cancel.
        </Speak>
    </Gather>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/hangup")
async def hangup(request: Request):
    form = await request.form()
    logger.info(f"Call ended — CallUUID={form.get('CallUUID', '?')}")
    return Response(content="OK", status_code=200)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "base_url": BASE_URL,
        "example": "08_number_capture",
        **store.analytics(),
    }


def main():
    global BASE_URL
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()

    logger.info("=" * 60)
    logger.info("  08 — Phone Number Capture")
    logger.info(f"  Answer URL    : {BASE_URL}/answer")
    logger.info(f"  View leads    : GET {BASE_URL}/leads")
    logger.info(f"  Export CSV    : GET {BASE_URL}/leads/export.csv")
    logger.info(f"  Analytics     : GET {BASE_URL}/leads/analytics")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
