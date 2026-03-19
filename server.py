"""
server.py — HTTP Server + ngrok Tunnel for Vobiz Webhooks
==========================================================
Serves XML webhooks for Vobiz call handling and manages ngrok tunnel.

Two modes:
  - "stream" (default): Direct AI agent via bidirectional WebSocket Stream
  - "test":  Sequential XML test pipeline exercising all Vobiz XML elements

Starts both the HTTP server and the agent WebSocket server.
"""

import os
import sys
import asyncio
import logging
import uvicorn

from fastapi import FastAPI, Request
from fastapi.responses import Response
from dotenv import load_dotenv
from pyngrok import ngrok, conf

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Render injects PORT automatically; fall back to HTTP_PORT or 8000
HTTP_PORT = int(os.getenv("PORT") or os.getenv("HTTP_PORT", "8000"))
WS_PORT = int(os.getenv("AGENT_WS_PORT", "8001"))
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
SERVER_MODE = os.getenv("SERVER_MODE", "stream")  # "stream" or "test"

# Production: set PUBLIC_URL to your Render URL to skip ngrok entirely.
# Render provides this automatically as RENDER_EXTERNAL_URL.
# You can also set it manually: PUBLIC_URL=https://vobiz-voice-agent.onrender.com
PUBLIC_URL = (
    os.getenv("PUBLIC_URL")
    or os.getenv("RENDER_EXTERNAL_URL", "")
).rstrip("/")

# XML Test Pipeline settings
DIAL_TEST_NUMBER = os.getenv("DIAL_TEST_NUMBER", "")
TEST_AUDIO_URL = os.getenv(
    "TEST_AUDIO_URL",
    "https://actions.google.com/sounds/v1/alarms/beep_short.ogg",
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("server")

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="Vobiz Voice Agent Server")

# Will be set at startup — either from PUBLIC_URL (production) or ngrok (local)
NGROK_URL = None


# ===========================================================================
#  HELPER: Build WebSocket URL from ngrok URL
# ===========================================================================

def _ws_url() -> str:
    """Convert the ngrok HTTPS URL to a WSS URL for the /ws proxy endpoint."""
    return NGROK_URL.replace("https://", "wss://").replace("http://", "ws://") + "/ws"


# ===========================================================================
#  SHARED ENDPOINTS (available in both modes)
# ===========================================================================

@app.post("/hangup")
async def hangup_call(request: Request):
    """Vobiz calls this when the call ends."""
    form_data = await request.form()
    call_uuid = form_data.get("CallUUID", "unknown")
    duration = form_data.get("Duration", "0")
    hangup_cause = form_data.get("HangupCause", "unknown")

    logger.info(
        f"Call ended — UUID={call_uuid}, Duration={duration}s, Cause={hangup_cause}"
    )
    return Response(content="OK", status_code=200)


@app.post("/stream-status")
async def stream_status(request: Request):
    """Vobiz sends stream lifecycle events here."""
    form_data = await request.form()
    event = form_data.get("Event", "unknown")
    stream_id = form_data.get("StreamID", "unknown")
    call_uuid = form_data.get("CallUUID", "unknown")
    name = form_data.get("Name", "")

    logger.info(
        f"Stream event — Event={event}, StreamID={stream_id}, "
        f"CallUUID={call_uuid}, Name={name}"
    )
    return Response(content="OK", status_code=200)


@app.get("/health")
async def health_check():
    """Health check endpoint — also used by make_call.py for auto-discovery."""
    return {
        "status": "healthy",
        "ngrok_url": NGROK_URL,
        "public_url": NGROK_URL,
        "mode": SERVER_MODE,
        "production": bool(PUBLIC_URL),
    }


# ===========================================================================
#  /answer — entry point for all inbound/outbound calls
# ===========================================================================

@app.post("/answer")
async def answer_call(request: Request):
    """
    Main answer webhook.
    - In "stream" mode: returns bidirectional Stream XML (AI agent).
    - In "test" mode:   returns an IVR Gather menu exercising all XML elements.
    """
    form_data = await request.form()
    call_uuid = form_data.get("CallUUID", "unknown")
    from_number = form_data.get("From", "unknown")
    to_number = form_data.get("To", "unknown")
    direction = form_data.get("Direction", "unknown")

    logger.info(
        f"Call connected — UUID={call_uuid}, From={from_number}, "
        f"To={to_number}, Direction={direction}, Mode={SERVER_MODE}"
    )

    if SERVER_MODE == "test":
        return _answer_test_menu()
    else:
        return _answer_stream()


def _answer_stream() -> Response:
    """Return bidirectional Stream XML for the AI agent (original behaviour)."""
    ws_url = _ws_url()
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" keepCallAlive="true"
            contentType="audio/x-mulaw;rate=8000"
            statusCallbackUrl="{NGROK_URL}/stream-status"
            statusCallbackMethod="POST">
        {ws_url}
    </Stream>
</Response>"""
    logger.info(f"Returning Stream XML -> {ws_url}")
    return Response(content=xml, media_type="application/xml")


def _answer_test_menu() -> Response:
    """Return an IVR Gather menu that lets the caller pick which XML element to test."""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{NGROK_URL}/menu-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="20">
        <Speak voice="WOMAN" language="en-US">
            Welcome to the Vobiz XML test suite.
            Press 1 to test Speak.
            Press 2 to test Play.
            Press 3 to test Record.
            Press 4 to test Dial transfer.
            Press 5 to test AI Stream.
            Press 6 to test Wait.
            Press 9 to repeat this menu.
            Press 0 to hang up.
        </Speak>
    </Gather>
    <Speak voice="WOMAN" language="en-US">
        We did not receive your input. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    logger.info("Returning IVR test menu XML")
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
#  /menu-choice — route DTMF digit to the correct test endpoint
# ===========================================================================

@app.post("/menu-choice")
async def menu_choice(request: Request):
    """Receives the digit pressed from the IVR Gather and redirects to the test."""
    form_data = await request.form()
    digits = form_data.get("Digits", "")
    call_uuid = form_data.get("CallUUID", "unknown")

    logger.info(f"Menu choice — Digits={digits}, CallUUID={call_uuid}")

    route_map = {
        "1": f"{NGROK_URL}/test-speak",
        "2": f"{NGROK_URL}/test-play",
        "3": f"{NGROK_URL}/test-record",
        "4": f"{NGROK_URL}/test-dial",
        "5": f"{NGROK_URL}/test-stream",
        "6": f"{NGROK_URL}/test-wait",
        "9": f"{NGROK_URL}/answer",
        "0": f"{NGROK_URL}/test-hangup",
    }

    target = route_map.get(digits, f"{NGROK_URL}/answer")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Redirect method="POST">{target}</Redirect>
</Response>"""
    logger.info(f"Redirecting to {target}")
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
#  TEST 1: /test-speak — Speak element (TTS with voices, SSML)
# ===========================================================================

@app.post("/test-speak")
async def test_speak(request: Request):
    """
    Demonstrates the Speak element with:
    - Different voices (WOMAN, MAN)
    - Different languages
    - SSML support
    Then redirects back to the main menu.
    """
    form_data = await request.form()
    logger.info(f"TEST SPEAK — CallUUID={form_data.get('CallUUID', 'unknown')}")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Test 1: Speak element. This is the female voice in English.
    </Speak>
    <Speak voice="MAN" language="en-US">
        And this is the male voice in English.
    </Speak>
    <Speak voice="WOMAN" language="en-GB">
        Now testing British English accent.
    </Speak>
    <Speak voice="WOMAN" language="en-US">
        Speak test complete. Returning to the main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
#  TEST 2: /test-play — Play element (MP3/WAV from URL)
# ===========================================================================

@app.post("/test-play")
async def test_play(request: Request):
    """
    Demonstrates the Play element by playing an audio file from a remote URL.
    """
    form_data = await request.form()
    logger.info(f"TEST PLAY — CallUUID={form_data.get('CallUUID', 'unknown')}")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Test 2: Play element. Playing an audio file now.
    </Speak>
    <Play loop="1">{TEST_AUDIO_URL}</Play>
    <Speak voice="WOMAN" language="en-US">
        Audio playback complete. Returning to the main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
#  TEST 3: /test-record — Record element + callback
# ===========================================================================

@app.post("/test-record")
async def test_record(request: Request):
    """
    Demonstrates the Record element:
    - Plays a prompt asking the user to leave a message
    - Records up to 15 seconds
    - Sends recording to callback URL
    - Redirects back to menu after recording
    """
    form_data = await request.form()
    logger.info(f"TEST RECORD — CallUUID={form_data.get('CallUUID', 'unknown')}")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Test 3: Record element. Please leave a short message after the beep.
        Press star when finished.
    </Speak>
    <Record action="{NGROK_URL}/test-record-callback"
            method="POST"
            maxLength="15"
            timeout="5"
            finishOnKey="*"
            playBeep="true"
            fileFormat="mp3"
            redirect="true"
            callbackUrl="{NGROK_URL}/test-record-result"/>
    <Speak voice="WOMAN" language="en-US">
        No recording received. Returning to the main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/test-record-callback")
async def test_record_callback(request: Request):
    """
    Action URL for Record element. Receives recording details
    and redirects back to the main menu.
    """
    form_data = await request.form()
    record_url = form_data.get("RecordUrl", "N/A")
    duration = form_data.get("RecordingDuration", "0")
    record_id = form_data.get("RecordingID", "N/A")
    end_reason = form_data.get("RecordingEndReason", "N/A")

    logger.info(
        f"RECORD CALLBACK — URL={record_url}, Duration={duration}s, "
        f"ID={record_id}, EndReason={end_reason}"
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Recording received. Duration: {duration} seconds.
        Reason: {end_reason}.
        Record test complete. Returning to main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/test-record-result")
async def test_record_result(request: Request):
    """
    Callback URL for Record element — fires when recording file is ready.
    This is a fire-and-forget callback, not an XML redirect.
    """
    form_data = await request.form()
    record_url = form_data.get("RecordUrl", "N/A")
    duration = form_data.get("RecordingDuration", "0")
    record_id = form_data.get("RecordingID", "N/A")

    logger.info(
        f"RECORD RESULT (callback) — URL={record_url}, Duration={duration}s, "
        f"ID={record_id}"
    )
    return Response(content="OK", status_code=200)


# ===========================================================================
#  TEST 4: /test-dial — Dial element (call transfer)
# ===========================================================================

@app.post("/test-dial")
async def test_dial(request: Request):
    """
    Demonstrates the Dial element:
    - Plays a message about the transfer
    - Dials a test phone number with explicit callerId
    - Reports dial status via action URL
    """
    form_data = await request.form()
    call_uuid = form_data.get("CallUUID", "unknown")
    from_number = form_data.get("From", "")
    logger.info(f"TEST DIAL — CallUUID={call_uuid}, From={from_number}")
    logger.info(f"TEST DIAL — Full params: {dict(form_data)}")

    if not DIAL_TEST_NUMBER:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Test 4: Dial element. Error: No test phone number configured.
        Please set DIAL_TEST_NUMBER in your environment file.
        Returning to the main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    # Use FROM_NUMBER (your Vobiz DID) as the callerId for the B-leg
    caller_id = os.getenv("FROM_NUMBER", from_number)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Test 4: Dial element. Transferring you to {DIAL_TEST_NUMBER}. Please wait.
    </Speak>
    <Dial action="{NGROK_URL}/test-dial-status"
          method="POST"
          timeout="30"
          timeLimit="120"
          callerId="{caller_id}"
          redirect="true"
          callbackUrl="{NGROK_URL}/test-dial-events"
          callbackMethod="POST">
        <Number>{DIAL_TEST_NUMBER}</Number>
    </Dial>
    <Speak voice="WOMAN" language="en-US">
        The transfer could not be completed. Returning to main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    logger.info(f"TEST DIAL — Dialing {DIAL_TEST_NUMBER} with callerId={caller_id}")
    return Response(content=xml, media_type="application/xml")


@app.post("/test-dial-status")
async def test_dial_status(request: Request):
    """
    Action URL for Dial element. Receives dial result and redirects back.
    """
    form_data = await request.form()
    dial_status = form_data.get("DialStatus", "unknown")
    dial_hangup_cause = form_data.get("DialHangupCause", "unknown")
    dial_a_leg = form_data.get("DialALegUUID", "N/A")
    dial_b_leg = form_data.get("DialBLegUUID", "N/A")

    logger.info(
        f"DIAL STATUS — Status={dial_status}, HangupCause={dial_hangup_cause}, "
        f"ALeg={dial_a_leg}, BLeg={dial_b_leg}"
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Dial test complete. Status: {dial_status}.
        Returning to main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/test-dial-events")
async def test_dial_events(request: Request):
    """
    Callback URL for Dial element — receives real-time dial events
    (answer, connected, hangup, digits).
    """
    form_data = await request.form()
    action = form_data.get("DialAction", "unknown")
    b_leg_status = form_data.get("DialBLegStatus", "N/A")

    logger.info(f"DIAL EVENT — Action={action}, BLegStatus={b_leg_status}")
    return Response(content="OK", status_code=200)


# ===========================================================================
#  TEST 5: /test-stream — Stream element (AI bidirectional WebSocket)
# ===========================================================================

@app.post("/test-stream")
async def test_stream(request: Request):
    """
    Demonstrates the Stream element with bidirectional audio.
    Connects the caller to the AI agent running on the WebSocket server.
    The agent will greet the caller and handle conversation.
    When the stream ends, control returns to the next XML element.

    NOTE: keepCallAlive is false here so when the WebSocket disconnects
    (e.g., agent says goodbye or timeout), the flow continues to the
    Redirect back to the main menu. The agent can also just converse
    and the caller presses * to disconnect.
    """
    form_data = await request.form()
    logger.info(f"TEST STREAM — CallUUID={form_data.get('CallUUID', 'unknown')}")

    ws_url = _ws_url()

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Test 5: AI Stream. You will now speak with the AI assistant.
        Say goodbye when you are done to return to the menu.
    </Speak>
    <Stream bidirectional="true" keepCallAlive="true"
            contentType="audio/x-mulaw;rate=8000"
            streamTimeout="120"
            statusCallbackUrl="{NGROK_URL}/stream-status"
            statusCallbackMethod="POST">
        {ws_url}
    </Stream>
    <Speak voice="WOMAN" language="en-US">
        AI Stream ended. Returning to main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
#  TEST 6: /test-wait — Wait element (silence/beep/machine detection)
# ===========================================================================

@app.post("/test-wait")
async def test_wait(request: Request):
    """
    Demonstrates the Wait element:
    - Basic wait (3 seconds)
    - Wait with silence detection (waits up to 10s but stops when silence is detected)
    """
    form_data = await request.form()
    logger.info(f"TEST WAIT — CallUUID={form_data.get('CallUUID', 'unknown')}")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Test 6: Wait element. First, a basic 3 second wait.
    </Speak>
    <Wait length="3"/>
    <Speak voice="WOMAN" language="en-US">
        3 seconds passed. Now testing wait with silence detection.
        Please stay silent. The system will detect silence and continue.
    </Speak>
    <Wait length="10" silence="true" minSilence="2000"/>
    <Speak voice="WOMAN" language="en-US">
        Silence detected. Wait test complete. Returning to main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
#  TEST 0: /test-hangup — Hangup element (graceful termination)
# ===========================================================================

@app.post("/test-hangup")
async def test_hangup(request: Request):
    """
    Demonstrates the Hangup element with a goodbye message.
    """
    form_data = await request.form()
    logger.info(f"TEST HANGUP — CallUUID={form_data.get('CallUUID', 'unknown')}")

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Goodbye! Thank you for testing the Vobiz XML suite. Have a great day!
    </Speak>
    <Hangup reason="rejected"/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
#  BONUS: /test-gather-speech — Gather with speech input (for future use)
# ===========================================================================

@app.post("/test-gather-speech")
async def test_gather_speech(request: Request):
    """
    Demonstrates Gather with speech recognition input.
    Collects spoken input, transcribes it, and reads it back.
    """
    form_data = await request.form()
    logger.info(
        f"TEST GATHER SPEECH — CallUUID={form_data.get('CallUUID', 'unknown')}"
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{NGROK_URL}/test-gather-speech-result"
            method="POST"
            inputType="speech"
            speechModel="phone_call"
            language="en-US"
            speechEndTimeout="3"
            executionTimeout="15">
        <Speak voice="WOMAN" language="en-US">
            Please say something and I will repeat it back to you.
        </Speak>
    </Gather>
    <Speak voice="WOMAN" language="en-US">
        No speech detected. Returning to main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/test-gather-speech-result")
async def test_gather_speech_result(request: Request):
    """Receives speech transcription from Gather and reads it back."""
    form_data = await request.form()
    input_type = form_data.get("InputType", "unknown")
    speech = form_data.get("Speech", "")
    confidence = form_data.get("SpeechConfidenceScore", "N/A")
    digits = form_data.get("Digits", "")

    logger.info(
        f"GATHER SPEECH RESULT — InputType={input_type}, Speech='{speech}', "
        f"Confidence={confidence}, Digits={digits}"
    )

    result_text = speech if speech else digits if digits else "nothing"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        You said: {result_text}. Confidence score: {confidence}.
        Returning to main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
#  SIP TRUNK ENDPOINTS
#  - /sip  : Origination URI — Vobiz SIP inbound trunk calls this URL
#            when a call arrives. Configure this as the "Inbound URI" in
#            your Vobiz Console → SIP → Inbound Trunks.
#  - /trunk-webhook : Trunk webhook for CallInitiated & Hangup events.
#            Configure in Vobiz Console → SIP → Outbound Trunks → Webhook.
# ===========================================================================

@app.post("/sip")
@app.get("/sip")
async def sip_inbound(request: Request):
    """
    SIP Origination URI endpoint.

    Configure this URL as the Inbound URI on your Vobiz SIP trunk:
      https://<ngrok-url>/sip

    When Vobiz receives an inbound SIP call on that trunk, it sends a POST
    here with call details and expects an XML response controlling the call.

    In "stream" mode  → connects directly to the AI agent.
    In "test" mode    → routes to the IVR test menu.
    """
    # Vobiz can send either form-encoded or query params for GET
    try:
        form_data = await request.form()
    except Exception:
        form_data = {}

    call_uuid   = form_data.get("CallUUID") or request.query_params.get("CallUUID", "unknown")
    from_number = form_data.get("From")     or request.query_params.get("From", "unknown")
    to_number   = form_data.get("To")       or request.query_params.get("To", "unknown")
    direction   = form_data.get("Direction") or request.query_params.get("Direction", "inbound")
    call_status = form_data.get("CallStatus") or request.query_params.get("CallStatus", "ringing")

    logger.info(
        f"[SIP INBOUND] CallUUID={call_uuid}, From={from_number}, "
        f"To={to_number}, Direction={direction}, Status={call_status}, Mode={SERVER_MODE}"
    )

    if SERVER_MODE == "test":
        return _answer_test_menu()
    else:
        return _answer_stream()


@app.post("/trunk-webhook")
@app.get("/trunk-webhook")
async def trunk_webhook(request: Request):
    """
    Trunk Webhook endpoint — receives real-time call events from Vobiz SIP trunks.

    Configure in Vobiz Console → SIP → Outbound Trunks → Webhook URL:
      https://<ngrok-url>/trunk-webhook

    Two events are delivered:
      - CallInitiated : fired on every outbound call attempt (allowed or rejected)
      - Hangup        : fired when a call ends (with cost, duration, MOS, jitter)
    """
    # Webhooks arrive as JSON (Content-Type: application/json)
    try:
        payload = await request.json()
    except Exception:
        try:
            form_data = await request.form()
            payload = dict(form_data)
        except Exception:
            payload = {}

    event      = payload.get("Event", "unknown")
    call_uuid  = payload.get("CallUUID", "unknown")
    from_num   = payload.get("From", "unknown")
    to_num     = payload.get("To", "unknown")
    allowed    = payload.get("Allowed", None)
    reason     = payload.get("Reason", "")
    trunk_id   = payload.get("TrunkID", "unknown")
    timestamp  = payload.get("Timestamp", "")

    if event == "CallInitiated":
        status_str = "ALLOWED" if allowed else f"REJECTED ({reason})"
        logger.info(
            f"[TRUNK] CallInitiated — UUID={call_uuid}, From={from_num}, "
            f"To={to_num}, Status={status_str}, Trunk={trunk_id}"
        )
        if not allowed:
            logger.warning(f"[TRUNK] Call REJECTED: {reason}")

    elif event == "Hangup":
        duration = payload.get("Duration", 0)
        billsec  = payload.get("Billsec", 0)
        cost     = payload.get("Cost", 0)
        currency = payload.get("Currency", "INR")
        mos      = payload.get("MOS", "N/A")
        jitter   = payload.get("Jitter", "N/A")
        ring_time = payload.get("RingTime", 0)

        logger.info(
            f"[TRUNK] Hangup — UUID={call_uuid}, From={from_num}, To={to_num}, "
            f"Duration={duration}s, Billsec={billsec}s, RingTime={ring_time}s, "
            f"Cost={cost} {currency}, MOS={mos}, Jitter={jitter}ms, Reason={reason}"
        )

    else:
        logger.info(f"[TRUNK] Unknown event={event}, Payload={payload}")

    # Trunk webhooks are informational only — response does not affect call
    return Response(content='{"status":"received"}', media_type="application/json")


# ===========================================================================
#  AGENT-TRIGGERED ENDPOINTS (called via Vobiz Transfer API from agent.py)
# ===========================================================================

@app.post("/transfer-to-number")
async def transfer_to_number(request: Request):
    """
    Called by Vobiz Transfer API when the AI agent decides to transfer a call.
    Receives the target phone number as a query parameter and returns Dial XML.
    """
    form_data = await request.form()
    call_uuid = form_data.get("CallUUID", "unknown")

    # Get the target number and announcement from query params
    number = request.query_params.get("number", "")
    announcement = request.query_params.get(
        "announcement", "Transferring your call now. Please hold."
    )

    logger.info(
        f"TRANSFER — CallUUID={call_uuid}, To={number}, Announcement={announcement}"
    )

    if not number:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Sorry, the transfer could not be completed. No destination number was provided.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
        return Response(content=xml, media_type="application/xml")

    # Use FROM_NUMBER (your Vobiz DID) as callerId for the B-leg
    caller_id = os.getenv("FROM_NUMBER", "")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">{announcement}</Speak>
    <Dial action="{NGROK_URL}/transfer-complete"
          method="POST"
          timeout="30"
          timeLimit="3600"
          callerId="{caller_id}"
          redirect="true"
          callbackUrl="{NGROK_URL}/transfer-events"
          callbackMethod="POST">
        <Number>{number}</Number>
    </Dial>
    <Speak voice="WOMAN" language="en-US">
        The transfer could not be completed. The number did not answer.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/transfer-complete")
async def transfer_complete(request: Request):
    """Action URL after a transfer Dial completes."""
    form_data = await request.form()
    dial_status = form_data.get("DialStatus", "unknown")
    call_uuid = form_data.get("CallUUID", "unknown")

    logger.info(f"TRANSFER COMPLETE — Status={dial_status}, CallUUID={call_uuid}")

    # After transfer ends, go back to main menu (test mode) or hang up (stream mode)
    if SERVER_MODE == "test":
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Transfer ended. Status: {dial_status}. Returning to main menu.
    </Speak>
    <Redirect method="POST">{NGROK_URL}/answer</Redirect>
</Response>"""
    else:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        The call has ended. Thank you.
    </Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.post("/transfer-events")
async def transfer_events(request: Request):
    """Callback for real-time transfer dial events."""
    form_data = await request.form()
    action = form_data.get("DialAction", "unknown")
    b_leg_status = form_data.get("DialBLegStatus", "N/A")
    logger.info(f"TRANSFER EVENT — Action={action}, BLegStatus={b_leg_status}")
    return Response(content="OK", status_code=200)


@app.post("/agent-hangup")
async def agent_hangup(request: Request):
    """
    Called by Vobiz Transfer API when the AI agent decides to hang up.
    Returns Hangup XML.
    """
    form_data = await request.form()
    call_uuid = form_data.get("CallUUID", "unknown")
    logger.info(f"AGENT HANGUP — CallUUID={call_uuid}")

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="WOMAN" language="en-US">
        Thank you for calling. Goodbye!
    </Speak>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ===========================================================================
#  WebSocket — direct agent handler (no proxy, no separate port)
# ===========================================================================

from starlette.websockets import WebSocket as StarletteWebSocket


@app.websocket("/ws")
async def websocket_handler(websocket: StarletteWebSocket):
    """
    Handle WebSocket connection from Vobiz directly in FastAPI.
    In production (Render) there is no separate agent port — the CallSession
    runs directly here. In local dev this is the same: the ngrok tunnel
    points here and the session is handled in-process.
    """
    from agent import CallSession
    import websockets.exceptions as ws_exc

    await websocket.accept()
    logger.info("WebSocket connection accepted from Vobiz")

    session = CallSession(websocket)
    try:
        while True:
            try:
                message = await websocket.receive_text()
                await session.handle_message(message)
            except Exception as e:
                if "disconnect" in str(e).lower() or "close" in str(e).lower():
                    break
                logger.error(f"WebSocket message error: {e}")
                break
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        await session.cleanup()
        logger.info("WebSocket connection closed")


# ===========================================================================
#  Main
# ===========================================================================

def _print_banner():
    """Print startup banner with all important URLs."""
    logger.info("")
    logger.info(f"{'=' * 60}")
    logger.info(f"  Vobiz Voice Agent Server")
    logger.info(f"")
    logger.info(f"   Mode:           {SERVER_MODE.upper()}")
    logger.info(f"   Public URL:     {NGROK_URL}")
    logger.info(f"   Answer URL:     {NGROK_URL}/answer")
    logger.info(f"   Hangup URL:     {NGROK_URL}/hangup")
    logger.info(f"   Health:         {NGROK_URL}/health")
    logger.info(f"")
    logger.info(f"   SIP Trunk Endpoints:")
    logger.info(f"     /sip            -> Inbound URI  (Console → SIP → Inbound Trunks)")
    logger.info(f"     /trunk-webhook  -> Webhook URL  (Console → SIP → Outbound Trunks)")
    logger.info(f"")
    if SERVER_MODE == "test":
        logger.info(f"   XML Test Pipeline:")
        logger.info(f"     /answer         -> IVR Menu")
        logger.info(f"     /test-speak     -> Speak demo")
        logger.info(f"     /test-play      -> Play demo")
        logger.info(f"     /test-record    -> Record demo")
        logger.info(f"     /test-dial      -> Dial/transfer demo")
        logger.info(f"     /test-stream    -> AI Stream")
        logger.info(f"     /test-wait      -> Wait demo")
        logger.info(f"     /test-hangup    -> Hangup demo")
        logger.info(f"")
    logger.info(f"{'=' * 60}")
    logger.info(f"")


def setup_ngrok():
    """Create ngrok tunnel (local dev only — skipped when PUBLIC_URL is set)."""
    global NGROK_URL

    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN

    # Try with pooling enabled first (handles case where tunnel is already online)
    try:
        http_tunnel = ngrok.connect(HTTP_PORT, "http", pooling_enabled=True)
    except Exception:
        http_tunnel = ngrok.connect(HTTP_PORT, "http")

    url = http_tunnel.public_url
    if url.startswith("http://"):
        url = url.replace("http://", "https://")
    NGROK_URL = url
    return NGROK_URL


def main():
    """Start everything: (optionally ngrok), HTTP server.

    The agent WebSocket sessions now run directly inside FastAPI's /ws
    endpoint — no separate port, no proxy, works on Render out of the box.
    """
    global NGROK_URL

    is_production = bool(PUBLIC_URL)

    if is_production:
        NGROK_URL = PUBLIC_URL
        logger.info(f"Starting Vobiz Voice Agent Server in PRODUCTION mode...")
        logger.info(f"Public URL: {NGROK_URL}")
    else:
        logger.info(f"Starting Vobiz Voice Agent Server in LOCAL mode (ngrok)...")
        import time
        time.sleep(1)
        try:
            setup_ngrok()
        except Exception as e:
            logger.error(f"Failed to setup ngrok: {e}")
            logger.error("Tip: run 'pkill -9 ngrok' to kill stale ngrok processes")
            sys.exit(1)

    _print_banner()

    # Start HTTP server (blocking) — WebSocket sessions run inside FastAPI
    logger.info(f"HTTP server starting on port {HTTP_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")


if __name__ == "__main__":
    main()
