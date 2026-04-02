"""
04_appointment_reminder/server.py — Appointment Reminder (with store + scheduling API)
=======================================================================================
YOUR APP interacts via:
  POST /appointments              → schedule a single reminder call
                                    body: {"phone":"+91...","name":"John","date":"Apr 5","time":"3 PM"}
  POST /appointments/bulk         → schedule multiple at once (JSON array)
  GET  /appointments              → list all with outcomes (?status=confirmed to filter)
  GET  /appointments/{id}         → single appointment status
  PATCH /appointments/{id}/cancel → cancel a pending appointment before call is made
  GET  /appointments/stats        → outcome breakdown

VOBIZ calls:
  POST /answer                    → reads reminder, collects response
  POST /appt-choice               → routes confirm/reschedule/cancel
  POST /appt-cancel-confirm       → double confirms cancellation
  POST /hangup
"""

import os
import logging
import uvicorn
import requests as req

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv
from pyngrok import ngrok, conf

from appointment_store import AppointmentStore

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
logger = logging.getLogger("appointment")

app = FastAPI(title="Appointment Reminder — Vobiz Example 04")
BASE_URL: str = ""
store = AppointmentStore()


def setup_ngrok() -> str:
    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN
    tunnel = ngrok.connect(HTTP_PORT, "http")
    url = tunnel.public_url.replace("http://", "https://")
    logger.info(f"ngrok tunnel: {url}")
    return url


def _trigger_vobiz_call(to_number: str, answer_url: str) -> str:
    payload = {
        "from": FROM_NUMBER,
        "to": to_number,
        "answer_url": answer_url,
        "answer_method": "POST",
        "hangup_url": f"{BASE_URL}/hangup",
        "hangup_method": "POST",
    }
    resp = req.post(
        f"https://api.vobiz.ai/api/v1/Account/{VOBIZ_AUTH_ID}/Call/",
        json=payload,
        headers={"X-Auth-ID": VOBIZ_AUTH_ID, "X-Auth-Token": VOBIZ_AUTH_TOKEN},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("api_id", "")


# ===========================================================================
# YOUR APP API
# ===========================================================================


class AppointmentRequest(BaseModel):
    phone: str
    name: str
    date: str
    time: str


@app.post("/appointments")
async def create_appointment(body: AppointmentRequest):
    """Schedule a single appointment reminder call."""
    appt = store.create(body.phone, body.name, body.date, body.time)
    logger.info(f"Appointment created — id={appt.id}, phone={body.phone}")

    answer_url = f"{BASE_URL}/answer?appt_id={appt.id}"
    try:
        call_uuid = _trigger_vobiz_call(body.phone, answer_url)
        store.bind_call(appt.id, call_uuid)
        logger.info(f"Call triggered — appt_id={appt.id}, call_uuid={call_uuid}")
    except Exception as e:
        logger.error(f"Call trigger failed: {e}")
        raise HTTPException(
            status_code=502, detail=f"Appointment saved but call failed: {e}"
        )

    return JSONResponse(appt.to_dict(), status_code=201)


@app.post("/appointments/bulk")
async def create_appointments_bulk(body: List[AppointmentRequest]):
    """Schedule multiple reminder calls at once."""
    results = []
    for item in body:
        appt = store.create(item.phone, item.name, item.date, item.time)
        try:
            answer_url = f"{BASE_URL}/answer?appt_id={appt.id}"
            call_uuid = _trigger_vobiz_call(item.phone, answer_url)
            store.bind_call(appt.id, call_uuid)
            results.append({**appt.to_dict(), "call_triggered": True})
        except Exception as e:
            results.append({**appt.to_dict(), "call_triggered": False, "error": str(e)})
    return JSONResponse(results, status_code=201)


@app.get("/appointments/stats")
async def appointments_stats():
    return JSONResponse(store.stats())


@app.get("/appointments")
async def list_appointments(status: Optional[str] = None):
    return JSONResponse(store.list_all(status_filter=status))


@app.get("/appointments/{appt_id}")
async def get_appointment(appt_id: str):
    appt = store.get(appt_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return JSONResponse(appt.to_dict())


@app.patch("/appointments/{appt_id}/cancel")
async def cancel_appointment(appt_id: str):
    ok = store.abort(appt_id)
    if not ok:
        raise HTTPException(
            status_code=400, detail="Cannot cancel — appointment not in pending state"
        )
    return JSONResponse({"status": "cancelled", "id": appt_id})


# ===========================================================================
# VOBIZ WEBHOOKS
# ===========================================================================


@app.post("/answer")
async def answer(request: Request):
    form = await request.form()
    appt_id = request.query_params.get("appt_id", "")
    appt = store.get(appt_id) if appt_id else None

    name = appt.name if appt else "there"
    date = appt.date if appt else "tomorrow"
    time = appt.time if appt else "your scheduled time"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/appt-choice?appt_id={appt_id}" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            Hello {name}! This is a reminder from Acme Clinic.
            You have an appointment scheduled for {date} at {time}.
            To confirm your appointment, press 1.
            To reschedule, press 2.
            To cancel, press 3.
            To hear this message again, press 9.
        </Speak>
    </Gather>
    <Speak voice="WOMAN" language="en-US">
        We did not receive your response. Please call us at 1800 123 456. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/appt-choice")
async def appt_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    appt_id = request.query_params.get("appt_id", "")
    appt = store.get(appt_id)

    call_uuid = form.get("CallUUID", "unknown")
    name = appt.name if appt else "there"
    date = appt.date if appt else "your appointment"
    time = appt.time if appt else ""

    if digit == "1":
        store.update_status(call_uuid, "confirmed")
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Thank you, {name}! Your appointment on {date} at {time} is confirmed.
        We look forward to seeing you. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    elif digit == "2":
        store.update_status(call_uuid, "reschedule_requested")
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        We understand. Please call us at 1800 123 456 to choose a new time.
        Your current appointment on {date} at {time} has been flagged for rescheduling. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    elif digit == "3":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/appt-cancel-confirm?appt_id={appt_id}" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="8">
        <Speak voice="WOMAN" language="en-US">
            Are you sure you want to cancel your appointment on {date} at {time}?
            Press 1 to confirm cancellation. Press 2 to keep your appointment.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/answer?appt_id={appt_id}</Redirect>
</Response>"""
    elif digit == "9":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/answer?appt_id={appt_id}</Redirect></Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/answer?appt_id={appt_id}</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/appt-cancel-confirm")
async def appt_cancel_confirm(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    call_uuid = form.get("CallUUID", "unknown")
    appt_id = request.query_params.get("appt_id", "")
    appt = store.get(appt_id)

    date = appt.date if appt else "your appointment"
    time = appt.time if appt else ""
    name = appt.name if appt else "there"

    if digit == "1":
        store.update_status(call_uuid, "cancelled")
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Your appointment on {date} at {time} has been cancelled, {name}.
        We hope to see you soon. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Great! Your appointment is still confirmed.</Speak>
    <Redirect method="POST">{BASE_URL}/answer?appt_id={appt_id}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/hangup")
async def hangup(request: Request):
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    # If hangup without a digit choice, mark as no_answer
    appt = store.get_by_call_uuid(call_uuid)
    if appt and appt.status == "calling":
        store.update_status(call_uuid, "no_answer")
    logger.info(f"Call ended — CallUUID={call_uuid}")
    return Response(content="OK", status_code=200)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "base_url": BASE_URL,
        "example": "04_appointment_reminder",
        **store.stats(),
    }


def main():
    global BASE_URL
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()

    logger.info("=" * 60)
    logger.info("  04 — Appointment Reminder")
    logger.info(f"  Schedule call : POST {BASE_URL}/appointments")
    logger.info(f"  Bulk schedule : POST {BASE_URL}/appointments/bulk")
    logger.info(f"  List outcomes : GET  {BASE_URL}/appointments")
    logger.info(f"  Stats         : GET  {BASE_URL}/appointments/stats")
    logger.info(f"  Hangup URL    : {BASE_URL}/hangup")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
