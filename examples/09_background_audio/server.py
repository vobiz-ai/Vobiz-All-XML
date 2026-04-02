"""
09_background_audio/server.py — Background Audio Mixing via Live Call Play API
================================================================================
Plays a looping background music track at low volume in parallel with the
caller's live conversation — true audio mixing, no conference room needed.

HOW IT WORKS
  When a call is answered, Vobiz hits /answer which returns a <Stream> XML to
  keep the call alive. Simultaneously, the server fires the Vobiz Live Call
  Play API with:
      "loop": true   → Vobiz loops the file natively (no asyncio workaround)
      "mix":  true   → audio is MIXED into the call alongside live speech
      "legs": "both" → both caller and agent hear the background music

  This is the simplest and most reliable approach — one API call per call,
  Vobiz handles all the looping internally.

VOBIZ WEBHOOKS (set in your Vobiz application):
  Answer URL  →  POST {BASE_URL}/answer
  Hangup URL  →  POST {BASE_URL}/hangup

YOUR APP / CONTROL API:
  POST  /trigger-background  →  Start (or restart) music on a live call
                                 body: { "call_uuid": "...", "url": "..." }
  POST  /stop-background     →  Stop music on a live call
                                 body: { "call_uuid": "..." }
  GET   /status              →  Active calls + audio state
  GET   /health              →  Health check + public URL
"""

import logging
import os
import threading

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pyngrok import conf, ngrok

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv(dotenv_path="../../.env")

HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
VOBIZ_AUTH_ID = os.getenv("VOBIZ_AUTH_ID", "")
VOBIZ_AUTH_TOKEN = os.getenv("VOBIZ_AUTH_TOKEN", "")
FROM_NUMBER = os.getenv("FROM_NUMBER", "")

# Royalty-free looping background music (publicly accessible MP3).
# Replace with your own track. The file loops natively via loop=true.
BACKGROUND_AUDIO_URL = os.getenv(
    "BACKGROUND_AUDIO_URL",
    "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
)

VOBIZ_API_BASE = "https://api.vobiz.ai/api/v1"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("background_audio")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Background Audio — Vobiz Example 09")
BASE_URL: str = ""

# Track active calls: call_uuid → { "from", "music_playing" }
active_calls: dict[str, dict] = {}

VOBIZ_HEADERS = {
    "X-Auth-ID": VOBIZ_AUTH_ID,
    "X-Auth-Token": VOBIZ_AUTH_TOKEN,
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# Live Call Play API helpers
# ---------------------------------------------------------------------------


def call_play_start(call_uuid: str, audio_url: str) -> dict:
    """
    POST /Call/{call_uuid}/Play/
    Plays audio_url on the live call with:
      loop=true  → Vobiz loops natively, no re-trigger needed
      mix=true   → mixed alongside live speech (background music behaviour)
      legs=both  → both caller and agent hear it
    """
    url = f"{VOBIZ_API_BASE}/Account/{VOBIZ_AUTH_ID}/Call/{call_uuid}/Play/"
    payload = {
        "urls": [audio_url],
        "loop": True,
        "mix": True,
        "legs": "both",
    }
    try:
        resp = requests.post(url, json=payload, headers=VOBIZ_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Live Play started — uuid={call_uuid} url={audio_url} resp={data}")
        return data
    except requests.RequestException as exc:
        logger.error(f"Live Play start failed — uuid={call_uuid} err={exc}")
        return {"error": str(exc)}


def call_play_stop(call_uuid: str) -> bool:
    """
    DELETE /Call/{call_uuid}/Play/
    Stops any currently playing audio on the call.
    Returns True on success (204).
    """
    url = f"{VOBIZ_API_BASE}/Account/{VOBIZ_AUTH_ID}/Call/{call_uuid}/Play/"
    try:
        resp = requests.delete(url, headers=VOBIZ_HEADERS, timeout=10)
        logger.info(f"Live Play stopped — uuid={call_uuid} status={resp.status_code}")
        return resp.status_code in (200, 204)
    except requests.RequestException as exc:
        logger.error(f"Live Play stop failed — uuid={call_uuid} err={exc}")
        return False


def start_music_after_answer(call_uuid: str, audio_url: str, delay: float = 1.5):
    """
    Fire the Play API in a background thread after a short delay.
    The delay gives Vobiz time to finish the <Speak> greeting first.
    """

    def _fire():
        import time

        time.sleep(delay)
        result = call_play_start(call_uuid, audio_url)
        if "error" not in result:
            if call_uuid in active_calls:
                active_calls[call_uuid]["music_playing"] = True

    t = threading.Thread(target=_fire, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# ngrok helper
# ---------------------------------------------------------------------------


def setup_ngrok() -> str:
    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN
    tunnel = ngrok.connect(HTTP_PORT, "http")
    url = tunnel.public_url.replace("http://", "https://")
    logger.info(f"ngrok tunnel: {url}")
    return url


# ===========================================================================
# VOBIZ WEBHOOKS
# ===========================================================================


@app.post("/answer")
async def answer(request: Request):
    """
    Entry point — Vobiz calls this when the call is answered.

    1. Returns a <Speak> greeting followed by a <Wait> to hold the line open.
       (In production, replace <Wait> with your <Stream> AI agent or <Dial>.)
    2. Immediately fires the Live Call Play API in a background thread so that
       looping background music starts playing alongside the live call.
    """
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    caller = form.get("From", "unknown")
    logger.info(f"Call answered — CallUUID={call_uuid} From={caller}")

    # Register the call
    active_calls[call_uuid] = {"from": caller, "music_playing": False}

    # Fire background music asynchronously (after short delay)
    start_music_after_answer(call_uuid, BACKGROUND_AUDIO_URL, delay=2.0)

    # Return XML — keep the line open for 120s so you can hear the music.
    # In a real deployment replace <Wait> with <Stream> or <Dial> for your agent.
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Hello! Background music is now playing on this call.
        You should hear soft music mixed with this voice.
    </Speak>
    <Wait length="120"/>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/hangup")
async def hangup(request: Request):
    """Call ended webhook — remove from active calls."""
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    active_calls.pop(call_uuid, None)
    logger.info(f"Call ended — CallUUID={call_uuid} | active_calls={len(active_calls)}")
    return Response(content="OK", status_code=200)


# ===========================================================================
# YOUR APP / CONTROL API
# ===========================================================================


@app.post("/trigger-background")
async def trigger_background(request: Request):
    """
    Start (or restart) background music on a live call.

    Body (JSON):
      {
        "call_uuid": "<required — CallUUID of the live call>",
        "url": "<optional — override the audio URL>"
      }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON body required"}, status_code=400)

    call_uuid = body.get("call_uuid", "")
    audio_url = body.get("url", BACKGROUND_AUDIO_URL)

    if not call_uuid:
        return JSONResponse({"error": "call_uuid is required"}, status_code=400)

    result = call_play_start(call_uuid, audio_url)
    if "error" in result:
        return JSONResponse({"status": "error", **result}, status_code=400)

    if call_uuid in active_calls:
        active_calls[call_uuid]["music_playing"] = True

    return JSONResponse(
        {
            "status": "started",
            "call_uuid": call_uuid,
            "audio_url": audio_url,
            "vobiz_response": result,
        }
    )


@app.post("/stop-background")
async def stop_background(request: Request):
    """
    Stop background music on a live call.

    Body (JSON):
      { "call_uuid": "<required>" }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON body required"}, status_code=400)

    call_uuid = body.get("call_uuid", "")
    if not call_uuid:
        return JSONResponse({"error": "call_uuid is required"}, status_code=400)

    ok = call_play_stop(call_uuid)
    if call_uuid in active_calls:
        active_calls[call_uuid]["music_playing"] = False

    return JSONResponse(
        {
            "status": "stopped" if ok else "error",
            "call_uuid": call_uuid,
        }
    )


@app.get("/status")
async def status():
    """Active calls and their music state."""
    return JSONResponse(
        {
            "active_call_count": len(active_calls),
            "active_calls": active_calls,
            "default_audio_url": BACKGROUND_AUDIO_URL,
        }
    )


@app.get("/health")
async def health():
    return JSONResponse(
        {
            "status": "ok",
            "base_url": BASE_URL,
            "example": "09_background_audio",
            "answer_url": f"{BASE_URL}/answer",
            "audio_url": BACKGROUND_AUDIO_URL,
            "approach": "Live Call Play API (loop=true, mix=true)",
        }
    )


# ===========================================================================
# Entry point
# ===========================================================================


def main():
    global BASE_URL, VOBIZ_HEADERS
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()

    # Rebuild headers now that env is fully loaded
    VOBIZ_HEADERS = {
        "X-Auth-ID": VOBIZ_AUTH_ID,
        "X-Auth-Token": VOBIZ_AUTH_TOKEN,
        "Content-Type": "application/json",
    }

    logger.info("=" * 65)
    logger.info("  09 — Background Audio (Live Call Play API)")
    logger.info(f"  Answer URL     : {BASE_URL}/answer")
    logger.info(f"  Hangup URL     : {BASE_URL}/hangup")
    logger.info(f"  Trigger music  : POST {BASE_URL}/trigger-background")
    logger.info(f"  Stop music     : POST {BASE_URL}/stop-background")
    logger.info(f"  Status         : GET  {BASE_URL}/status")
    logger.info(f"  Audio URL      : {BACKGROUND_AUDIO_URL}")
    logger.info(f"  Mode           : loop=true  mix=true  legs=both")
    logger.info("=" * 65)

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
