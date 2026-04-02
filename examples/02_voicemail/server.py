"""
02_voicemail/server.py — Voicemail (with persistent store + admin API)
======================================================================
YOUR APP interacts via:
  GET    /voicemails          → list all voicemails
  GET    /voicemails/{id}     → single voicemail detail + recording URL
  PATCH  /voicemails/{id}/read → mark as read
  DELETE /voicemails/{id}     → delete
  GET    /voicemails/stats    → total / unread count

VOBIZ calls:
  POST /answer                → plays greeting and starts recording
  POST /voicemail-done        → action URL — fires when recording ends
  POST /voicemail-file        → callback — fires when MP3 is ready
  POST /hangup
"""

import os
import logging
import uvicorn

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from dotenv import load_dotenv
from pyngrok import ngrok, conf

from voicemail_store import VoicemailStore

load_dotenv(dotenv_path="../../.env")

HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("voicemail")

app = FastAPI(title="Voicemail — Vobiz Example 02")
BASE_URL: str = ""
store = VoicemailStore()


def setup_ngrok() -> str:
    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN
    tunnel = ngrok.connect(HTTP_PORT, "http")
    url = tunnel.public_url.replace("http://", "https://")
    logger.info(f"ngrok tunnel: {url}")
    return url


# ===========================================================================
# YOUR APP API — manage voicemails
# ===========================================================================


@app.get("/voicemails/stats")
async def voicemail_stats():
    """Total / unread counts."""
    return JSONResponse(store.stats())


@app.get("/voicemails")
async def list_voicemails():
    """List all voicemails, newest first."""
    return JSONResponse(store.list_all())


@app.get("/voicemails/{vm_id}")
async def get_voicemail(vm_id: str):
    """Get a single voicemail by ID."""
    vm = store.get(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="Voicemail not found")
    return JSONResponse(vm.to_dict())


@app.patch("/voicemails/{vm_id}/read")
async def mark_read(vm_id: str):
    """Mark a voicemail as read."""
    ok = store.mark_read(vm_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Voicemail not found")
    return JSONResponse({"status": "marked_read", "id": vm_id})


@app.delete("/voicemails/{vm_id}")
async def delete_voicemail(vm_id: str):
    """Delete a voicemail."""
    ok = store.delete(vm_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Voicemail not found")
    return JSONResponse({"status": "deleted", "id": vm_id})


# ===========================================================================
# VOBIZ WEBHOOKS
# ===========================================================================


@app.post("/answer")
async def answer(request: Request):
    form = await request.form()
    logger.info(
        f"Incoming call — CallUUID={form.get('CallUUID', '?')}, From={form.get('From', '?')}"
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Hello! You have reached Acme Corporation.
        Our team is currently unavailable.
        Please leave your name and message after the beep,
        and we will get back to you as soon as possible.
        Press the star key when you are finished.
    </Speak>
    <Record action="{BASE_URL}/voicemail-done"
            method="POST"
            maxLength="60"
            timeout="5"
            finishOnKey="*"
            playBeep="true"
            fileFormat="mp3"
            redirect="true"
            callbackUrl="{BASE_URL}/voicemail-file"/>
    <Speak voice="WOMAN" language="en-US">We did not receive a recording. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/voicemail-done")
async def voicemail_done(request: Request):
    """Action URL — fires immediately when recording ends."""
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    from_num = form.get("From", "unknown")
    record_url = form.get("RecordUrl", "")
    duration = int(form.get("RecordingDuration", "0"))
    end_reason = form.get("RecordingEndReason", "unknown")

    vm = store.save(call_uuid, from_num, duration, record_url)
    logger.info(
        f"Voicemail saved — id={vm.id}, From={from_num}, "
        f"Duration={duration}s, Reason={end_reason}, URL={record_url}"
    )
    # TODO: send email / Slack notification here with vm.id and record_url

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Thank you for your message of {duration} seconds.
        Our team will contact you shortly. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/voicemail-file")
async def voicemail_file(request: Request):
    """Callback URL — fires when MP3 file is fully processed and ready to download."""
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    record_url = form.get("RecordUrl", "")
    duration = form.get("RecordingDuration", "0")

    store.update_url(call_uuid, record_url)
    logger.info(
        f"Voicemail MP3 ready — CallUUID={call_uuid}, Duration={duration}s, URL={record_url}"
    )

    # TODO: download MP3 and transcribe with OpenAI Whisper:
    # audio = requests.get(record_url).content
    # transcription = openai.audio.transcriptions.create(model="whisper-1", file=audio)
    # store.get_by_call_uuid(call_uuid).transcription = transcription.text

    return Response(content="OK", status_code=200)


@app.post("/hangup")
async def hangup(request: Request):
    form = await request.form()
    logger.info(
        f"Call ended — CallUUID={form.get('CallUUID', '?')}, Duration={form.get('Duration', '0')}s"
    )
    return Response(content="OK", status_code=200)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "base_url": BASE_URL,
        "example": "02_voicemail",
        **store.stats(),
    }


def main():
    global BASE_URL
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()

    logger.info("=" * 60)
    logger.info("  02 — Voicemail")
    logger.info(f"  Answer URL     : {BASE_URL}/answer")
    logger.info(f"  Hangup URL     : {BASE_URL}/hangup")
    logger.info(f"  List voicemails: GET {BASE_URL}/voicemails")
    logger.info(f"  Stats          : GET {BASE_URL}/voicemails/stats")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
