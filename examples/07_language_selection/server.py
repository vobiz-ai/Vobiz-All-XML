"""
07_language_selection/server.py — Language Selection IVR (with preference store + analytics)
==============================================================================================
YOUR APP interacts via:
  GET  /preferences/{phone}       → get stored language for a caller
  DELETE /preferences/{phone}     → reset preference (caller sees menu again)
  GET  /preferences               → list all stored preferences
  GET  /preferences/analytics     → language distribution across all callers

VOBIZ calls:
  POST /answer                    → check preference; skip menu for known callers
  POST /lang-choice               → saves language choice + routes to sub-menu
  POST /english-menu / /hindi-menu
  POST /english-choice / /hindi-choice
  POST /dial-complete
  POST /hangup
"""

import os
import logging
import uvicorn

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from dotenv import load_dotenv
from pyngrok import ngrok, conf

from preference_store import PreferenceStore

load_dotenv(dotenv_path="../../.env")

HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
AGENT_NUMBER = os.getenv("AGENT_NUMBER", os.getenv("FROM_NUMBER", ""))
FROM_NUMBER = os.getenv("FROM_NUMBER", "")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("language_selection")

app = FastAPI(title="Language Selection — Vobiz Example 07")
BASE_URL: str = ""
prefs = PreferenceStore()


def setup_ngrok() -> str:
    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN
    tunnel = ngrok.connect(HTTP_PORT, "http")
    url = tunnel.public_url.replace("http://", "https://")
    logger.info(f"ngrok tunnel: {url}")
    return url


# ===========================================================================
# YOUR APP API
# ===========================================================================


@app.get("/preferences/analytics")
async def preferences_analytics():
    """Language distribution across all callers."""
    return JSONResponse(prefs.analytics())


@app.get("/preferences")
async def list_preferences():
    """List all stored caller language preferences."""
    return JSONResponse(prefs.list_all())


@app.get("/preferences/{phone}")
async def get_preference(phone: str):
    """Get the stored language for a specific caller."""
    lang = prefs.get(phone)
    if not lang:
        raise HTTPException(
            status_code=404, detail="No preference stored for this number"
        )
    return JSONResponse({"phone": phone, "language": lang})


@app.delete("/preferences/{phone}")
async def delete_preference(phone: str):
    """Reset preference — caller will see the language menu on next call."""
    ok = prefs.delete(phone)
    if not ok:
        raise HTTPException(
            status_code=404, detail="No preference stored for this number"
        )
    return JSONResponse({"status": "deleted", "phone": phone})


# ===========================================================================
# VOBIZ WEBHOOKS
# ===========================================================================


@app.post("/answer")
async def answer(request: Request):
    form = await request.form()
    from_num = form.get("From", "")

    # Check if we already know this caller's language — skip menu if so
    known_lang = prefs.get(from_num) if from_num else None
    if known_lang:
        logger.info(f"Known caller {from_num} → language={known_lang}, skipping menu")
        target = (
            f"{BASE_URL}/english-menu"
            if known_lang == "en"
            else f"{BASE_URL}/hindi-menu"
        )
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Redirect method="POST">{target}</Redirect>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    # New caller — show language selection
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/lang-choice?from={from_num}" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            Welcome to Acme Corporation. For English, press 1.
        </Speak>
        <Speak voice="WOMAN" language="hi-IN">
            Hindi ke liye, 2 dabaein.
        </Speak>
    </Gather>
    <Speak voice="WOMAN" language="en-US">We did not receive your input. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/lang-choice")
async def lang_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")
    from_num = request.query_params.get("from", form.get("From", ""))

    if digit == "1":
        prefs.save(from_num, "en")
        target = f"{BASE_URL}/english-menu"
        logger.info(f"Language saved: {from_num} → en")
    elif digit == "2":
        prefs.save(from_num, "hi")
        target = f"{BASE_URL}/hindi-menu"
        logger.info(f"Language saved: {from_num} → hi")
    else:
        target = f"{BASE_URL}/answer"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{target}</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


# ── English flow ──────────────────────────────────────────────────────────────


@app.post("/english-menu")
async def english_menu(request: Request):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/english-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="en-US">
            You have selected English.
            For general information, press 1.
            To speak with an agent, press 2.
            To change your language, press 0.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/english-menu</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/english-choice")
async def english_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")

    if digit == "1":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Acme Corporation provides cloud telephony and AI voice agents for businesses.
        Visit acme dot com for more information. Returning to the menu.
    </Speak>
    <Redirect method="POST">{BASE_URL}/english-menu</Redirect>
</Response>"""
    elif digit == "2":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Please hold while we connect you to an agent.</Speak>
    <Dial action="{BASE_URL}/dial-complete" method="POST" timeout="30" callerId="{FROM_NUMBER}">
        <Number>{AGENT_NUMBER}</Number>
    </Dial>
    <Speak voice="WOMAN" language="en-US">No agents available. Please try again later.</Speak>
    <Redirect method="POST">{BASE_URL}/english-menu</Redirect>
</Response>"""
    elif digit == "0":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/answer</Redirect></Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/english-menu</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


# ── Hindi flow ────────────────────────────────────────────────────────────────


@app.post("/hindi-menu")
async def hindi_menu(request: Request):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{BASE_URL}/hindi-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak voice="WOMAN" language="hi-IN">
            Aapne Hindi chunee hai.
            Jaankaari ke liye 1 dabaein.
            Agent se baat karne ke liye 2 dabaein.
            Bhasha badalne ke liye 0 dabaein.
        </Speak>
    </Gather>
    <Redirect method="POST">{BASE_URL}/hindi-menu</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/hindi-choice")
async def hindi_choice(request: Request):
    form = await request.form()
    digit = form.get("Digits", "")

    if digit == "1":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="hi-IN">
        Acme Corporation cloud telephony aur AI voice agents provide karta hai.
        Adhik jaankari ke liye acme dot com visit karein. Menu par wapas jaa rahe hain.
    </Speak>
    <Redirect method="POST">{BASE_URL}/hindi-menu</Redirect>
</Response>"""
    elif digit == "2":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="hi-IN">Kripya ruken, agent se connect kar rahe hain.</Speak>
    <Dial action="{BASE_URL}/dial-complete" method="POST" timeout="30" callerId="{FROM_NUMBER}">
        <Number>{AGENT_NUMBER}</Number>
    </Dial>
    <Speak voice="WOMAN" language="hi-IN">Koi agent upalabdh nahi hai. Baad mein call karein.</Speak>
    <Redirect method="POST">{BASE_URL}/hindi-menu</Redirect>
</Response>"""
    elif digit == "0":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/answer</Redirect></Response>"""
    else:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Redirect method="POST">{BASE_URL}/hindi-menu</Redirect></Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/dial-complete")
async def dial_complete(request: Request):
    form = await request.form()
    status = form.get("DialStatus", "unknown")
    logger.info(f"Dial complete — status={status}")
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Thank you for calling. Goodbye!</Speak>
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
        "example": "07_language_selection",
        **prefs.analytics(),
    }


def main():
    global BASE_URL
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()

    logger.info("=" * 60)
    logger.info("  07 — Language Selection IVR")
    logger.info(f"  Answer URL    : {BASE_URL}/answer")
    logger.info(f"  Preferences   : GET {BASE_URL}/preferences")
    logger.info(f"  Analytics     : GET {BASE_URL}/preferences/analytics")
    logger.info("  Known callers skip the menu automatically")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
