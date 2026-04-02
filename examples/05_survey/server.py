"""
05_survey/server.py — Customer Feedback Survey (with store + results API)
==========================================================================
YOUR APP interacts via:
  POST /surveys/trigger           → trigger a survey call to a number
                                    body: {"phone": "+91XXXXXXXXXX"}
  GET  /surveys/results           → list all completed survey responses
  GET  /surveys/results/{id}      → single survey response
  GET  /surveys/export.csv        → download all results as CSV
  GET  /surveys/summary           → aggregated stats (avg rating, recommend %, etc.)

VOBIZ calls:
  POST /answer                    → survey intro
  POST /survey-q1                 → Q1: rate service 1-5
  POST /survey-q1-result          → save Q1 answer
  POST /survey-q2                 → Q2: recommend yes/no
  POST /survey-q2-result          → save Q2 answer
  POST /survey-q3                 → Q3: overall experience
  POST /survey-q3-result          → save Q3 answer
  POST /survey-done               → finalize + thank you
  POST /hangup
"""

import os
import logging
import uvicorn
import requests as req

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from pyngrok import ngrok, conf

from survey_store import SurveyStore

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
logger = logging.getLogger("survey")

app = FastAPI(title="Survey — Vobiz Example 05")
BASE_URL: str = ""
store = SurveyStore()


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


class TriggerRequest(BaseModel):
    phone: str


@app.post("/surveys/trigger")
async def trigger_survey(body: TriggerRequest):
    """Trigger an outbound survey call."""
    phone = body.phone.strip()
    answer_url = f"{BASE_URL}/answer?phone={phone}"
    try:
        call_uuid = _trigger_vobiz_call(phone, answer_url)
        logger.info(f"Survey call triggered — phone={phone}, call_uuid={call_uuid}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to trigger call: {e}")
    return JSONResponse(
        {"status": "call_initiated", "phone": phone, "call_uuid": call_uuid}
    )


@app.get("/surveys/summary")
async def survey_summary():
    """Aggregated stats: avg rating, recommend %, experience distribution."""
    return JSONResponse(store.summary())


@app.get("/surveys/export.csv")
async def survey_export():
    """Download all survey results as CSV."""
    csv_data = store.export_csv()
    return PlainTextResponse(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=survey_results.csv"},
    )


@app.get("/surveys/results")
async def list_results():
    """List all completed survey responses."""
    return JSONResponse(store.list_all())


@app.get("/surveys/results/{result_id}")
async def get_result(result_id: str):
    result = store.get(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Survey result not found")
    return JSONResponse(result.to_dict())


# ===========================================================================
# VOBIZ WEBHOOKS
# ===========================================================================


@app.post("/answer")
async def answer(request: Request):
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    phone = request.query_params.get("phone", form.get("From", "unknown"))
    store.start(call_uuid, phone)
    logger.info(f"Survey started — CallUUID={call_uuid}, phone={phone}")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Hello! Thank you for being a valued customer.
        We have a quick 3-question survey to help us serve you better.
        This will only take about 30 seconds.
    </Speak>
    <Redirect method="POST">{BASE_URL}/survey-q1?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/survey-q1")
async def survey_q1(request: Request):
    call_uuid = request.query_params.get("call_uuid", "unknown")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/survey-q1-result?call_uuid={call_uuid}" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            Question 1. On a scale of 1 to 5, how would you rate the quality of our service?
            Press 1 for very poor, 2 for poor, 3 for average, 4 for good, 5 for excellent.
        </Speak>
    </Gather>
    <Speak voice="WOMAN" language="en-US">No response received. Skipping to next question.</Speak>
    <Redirect method="POST">{BASE_URL}/survey-q2?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/survey-q1-result")
async def survey_q1_result(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    call_uuid = request.query_params.get("call_uuid", "unknown")
    labels = {
        "1": "very poor",
        "2": "poor",
        "3": "average",
        "4": "good",
        "5": "excellent",
    }
    label = labels.get(digit, "unknown")
    store.update_answer(call_uuid, "q1_rating", digit)
    logger.info(f"Q1 answer — call={call_uuid}, rating={digit} ({label})")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Thank you, you rated our service as {label}.</Speak>
    <Redirect method="POST">{BASE_URL}/survey-q2?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/survey-q2")
async def survey_q2(request: Request):
    call_uuid = request.query_params.get("call_uuid", "unknown")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/survey-q2-result?call_uuid={call_uuid}" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            Question 2. Would you recommend Acme Corporation to a friend or colleague?
            Press 1 for yes, press 2 for no.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/survey-q3?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/survey-q2-result")
async def survey_q2_result(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    call_uuid = request.query_params.get("call_uuid", "unknown")
    label = "yes" if digit == "1" else "no" if digit == "2" else "unknown"
    store.update_answer(call_uuid, "q2_recommend", label)
    logger.info(f"Q2 answer — call={call_uuid}, recommend={label}")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Got it, thank you!</Speak>
    <Redirect method="POST">{BASE_URL}/survey-q3?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/survey-q3")
async def survey_q3(request: Request):
    call_uuid = request.query_params.get("call_uuid", "unknown")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/survey-q3-result?call_uuid={call_uuid}" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            Question 3, the last one.
            How would you describe your overall experience with us?
            Press 1 for excellent, 2 for good, 3 for needs improvement.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/survey-done?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/survey-q3-result")
async def survey_q3_result(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    call_uuid = request.query_params.get("call_uuid", "unknown")
    labels = {"1": "excellent", "2": "good", "3": "needs improvement"}
    label = labels.get(digit, "unknown")
    store.update_answer(call_uuid, "q3_experience", label)
    logger.info(f"Q3 answer — call={call_uuid}, experience={label}")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Redirect method="POST">{BASE_URL}/survey-done?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/survey-done")
async def survey_done(request: Request):
    call_uuid = request.query_params.get("call_uuid", "unknown")
    result = store.complete(call_uuid)
    if result:
        logger.info(f"Survey complete — {result.to_dict()}")
        # TODO: push to CRM / analytics platform here
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Thank you so much for completing our survey!
        Your feedback is extremely valuable. Have a wonderful day! Goodbye!
    </Speak>
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
        "example": "05_survey",
        **store.summary(),
    }


def main():
    global BASE_URL
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()

    logger.info("=" * 60)
    logger.info("  05 — Customer Feedback Survey")
    logger.info(f"  Trigger call  : POST {BASE_URL}/surveys/trigger")
    logger.info(f"  Results       : GET  {BASE_URL}/surveys/results")
    logger.info(f"  Summary stats : GET  {BASE_URL}/surveys/summary")
    logger.info(f"  CSV export    : GET  {BASE_URL}/surveys/export.csv")
    logger.info(f"  Hangup URL    : {BASE_URL}/hangup")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
