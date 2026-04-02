"""
06_call_queue/server.py — Call Queue (with agent pool, round-robin + metrics API)
==================================================================================
YOUR APP / AGENTS interact via:
  POST /agents                    → agent registers as available
                                    body: {"number": "+91...", "name": "Raj"}
  DELETE /agents/{number}         → agent goes offline
  GET  /agents                    → list all available agents
  GET  /queue/status              → callers waiting + agent count
  GET  /queue/metrics             → avg wait, connected, abandoned, abandonment rate

VOBIZ calls:
  POST /answer                    → greeting + start hold
  POST /queue-hold                → play music + wait per cycle
  POST /queue-try-agent           → dial next available agent (round-robin)
  POST /dial-complete             → agent answered or didn't
  POST /queue-voicemail           → fallback record after max retries
  POST /voicemail-done
  POST /voicemail-file
  POST /hangup
"""

import os
import logging
import uvicorn

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from pyngrok import ngrok, conf

from queue_store import QueueStore

load_dotenv(dotenv_path="../../.env")

HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
FROM_NUMBER = os.getenv("FROM_NUMBER", "")
HOLD_MUSIC_URL = os.getenv(
    "HOLD_MUSIC_URL",
    "https://actions.google.com/sounds/v1/alarms/beep_short.ogg",
)
MAX_WAIT_CYCLES = int(os.getenv("MAX_WAIT_CYCLES", "2"))  # 2 cycles for demo
HOLD_WAIT_SECS = int(os.getenv("HOLD_WAIT_SECS", "10"))  # 10s hold per cycle

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("call_queue")

app = FastAPI(title="Call Queue — Vobiz Example 06")
BASE_URL: str = ""
queue = QueueStore(fallback_number=FROM_NUMBER)

# Per-call attempt counter (in-memory)
call_attempts: dict[str, int] = {}


def setup_ngrok() -> str:
    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN
    tunnel = ngrok.connect(HTTP_PORT, "http")
    url = tunnel.public_url.replace("http://", "https://")
    logger.info(f"ngrok tunnel: {url}")
    return url


# ===========================================================================
# YOUR APP / AGENT API
# ===========================================================================


class AgentRequest(BaseModel):
    number: str
    name: str


@app.post("/agents")
async def add_agent(body: AgentRequest):
    """Register an agent as available for calls."""
    agent = queue.add_agent(body.number, body.name)
    logger.info(f"Agent online — {body.name} ({body.number})")
    return JSONResponse(agent.to_dict(), status_code=201)


@app.delete("/agents/{number}")
async def remove_agent(number: str):
    """Take an agent offline."""
    ok = queue.remove_agent(number)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    logger.info(f"Agent offline — {number}")
    return JSONResponse({"status": "offline", "number": number})


@app.get("/agents")
async def list_agents():
    """List all currently available agents."""
    return JSONResponse(queue.list_agents())


@app.get("/queue/status")
async def queue_status():
    """Current queue depth + agent availability."""
    return JSONResponse(queue.queue_status())


@app.get("/queue/metrics")
async def queue_metrics():
    """Historical metrics: avg wait time, connected, abandoned, abandonment rate."""
    return JSONResponse(queue.metrics())


# ===========================================================================
# VOBIZ WEBHOOKS
# ===========================================================================


@app.post("/answer")
async def answer(request: Request):
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    call_attempts[call_uuid] = 0
    queue.caller_joined(call_uuid)
    logger.info(f"Caller joined queue — CallUUID={call_uuid}")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Thank you for calling Acme Corporation.
        All our agents are currently assisting other customers.
        Your call is important to us. Please hold and we will be with you shortly.
    </Speak>
    <Redirect method="POST">{BASE_URL}/queue-hold?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/queue-hold")
async def queue_hold(request: Request):
    call_uuid = request.query_params.get("call_uuid", "unknown")
    attempt = call_attempts.get(call_uuid, 0)

    if attempt >= MAX_WAIT_CYCLES:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        We are sorry, all agents are still busy.
        Please leave a message and we will call you back as soon as possible.
    </Speak>
    <Redirect method="POST">{BASE_URL}/queue-voicemail?call_uuid={call_uuid}</Redirect>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    agents_avail = queue.agent_count()
    position_msg = (
        f"There are {agents_avail} agent{'s' if agents_avail != 1 else ''} available. Connecting shortly."
        if agents_avail > 0
        else "You are next in the queue. Please continue to hold."
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">{position_msg}</Speak>
    <Play loop="1">{HOLD_MUSIC_URL}</Play>
    <Wait length="{HOLD_WAIT_SECS}"/>
    <Redirect method="POST">{BASE_URL}/queue-try-agent?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/queue-try-agent")
async def queue_try_agent(request: Request):
    call_uuid = request.query_params.get("call_uuid", "unknown")
    attempt = call_attempts.get(call_uuid, 0)
    call_attempts[call_uuid] = attempt + 1

    agent_number = queue.next_agent_number()
    logger.info(
        f"Trying agent {agent_number} — attempt={attempt + 1}, CallUUID={call_uuid}"
    )

    if not agent_number:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Redirect method="POST">{BASE_URL}/queue-hold?call_uuid={call_uuid}</Redirect>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Connecting you now. Please hold.</Speak>
    <Dial action="{BASE_URL}/dial-complete?call_uuid={call_uuid}&amp;agent={agent_number}"
          method="POST" timeout="15" callerId="{FROM_NUMBER}">
        <Number>{agent_number}</Number>
    </Dial>
    <Redirect method="POST">{BASE_URL}/queue-hold?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/dial-complete")
async def dial_complete(request: Request):
    form = await request.form()
    status = form.get("DialStatus", "unknown")
    call_uuid = request.query_params.get("call_uuid", "unknown")
    agent_number = request.query_params.get("agent", "")

    if status == "answer":
        queue.caller_connected(call_uuid, agent_number)
        call_attempts.pop(call_uuid, None)
        logger.info(f"Call connected to agent {agent_number} — CallUUID={call_uuid}")
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">Thank you for calling Acme Corporation. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    else:
        logger.info(f"Agent {agent_number} did not answer — status={status}")
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Redirect method="POST">{BASE_URL}/queue-hold?call_uuid={call_uuid}</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/queue-voicemail")
async def queue_voicemail(request: Request):
    call_uuid = request.query_params.get("call_uuid", "unknown")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record action="{BASE_URL}/voicemail-done?call_uuid={call_uuid}"
            method="POST" maxLength="60" timeout="5"
            finishOnKey="*" playBeep="true" fileFormat="mp3"
            redirect="true" callbackUrl="{BASE_URL}/voicemail-file"/>
    <Speak voice="WOMAN" language="en-US">No message received. Goodbye!</Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/voicemail-done")
async def voicemail_done(request: Request):
    form = await request.form()
    call_uuid = request.query_params.get("call_uuid", "unknown")
    duration = form.get("RecordingDuration", "0")
    logger.info(f"Voicemail left — CallUUID={call_uuid}, Duration={duration}s")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Thank you for leaving a {duration}-second message.
        An agent will call you back shortly. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/voicemail-file")
async def voicemail_file(request: Request):
    form = await request.form()
    logger.info(f"Voicemail MP3 ready — URL={form.get('RecordUrl', 'N/A')}")
    return Response(content="OK", status_code=200)


@app.post("/hangup")
async def hangup(request: Request):
    form = await request.form()
    call_uuid = form.get("CallUUID", "unknown")
    queue.caller_abandoned(call_uuid)
    call_attempts.pop(call_uuid, None)
    logger.info(f"Call ended — CallUUID={call_uuid}")
    return Response(content="OK", status_code=200)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "base_url": BASE_URL,
        "example": "06_call_queue",
        **queue.queue_status(),
    }


def main():
    global BASE_URL
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()

    logger.info("=" * 60)
    logger.info("  06 — Call Queue / Hold Music")
    logger.info(f"  Answer URL    : {BASE_URL}/answer")
    logger.info(f"  Add agent     : POST {BASE_URL}/agents")
    logger.info(f"  Queue status  : GET  {BASE_URL}/queue/status")
    logger.info(f"  Metrics       : GET  {BASE_URL}/queue/metrics")
    logger.info(f"  Max retries   : {MAX_WAIT_CYCLES} | Hold secs: {HOLD_WAIT_SECS}")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
