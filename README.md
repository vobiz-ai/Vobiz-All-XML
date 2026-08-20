# Vobiz AI Voice Agent — Full XML Pipeline

A single FastAPI service that answers real phone calls two ways: as a streaming AI voice agent (Deepgram STT, OpenAI GPT-4o-mini, OpenAI TTS) and as an IVR test pipeline that exercises every Vobiz XML element in turn.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688.svg)](https://fastapi.tiangolo.com/)
[![Docs](https://img.shields.io/badge/Docs-docs.vobiz.ai-6366F1.svg)](https://docs.vobiz.ai)

---

## Table of Contents

1. [Overview](#overview)
2. [What you can build with it](#what-you-can-build-with-it)
3. [How it works](#how-it-works)
4. [Architecture](#architecture)
5. [Prerequisites](#prerequisites)
6. [Setup](#setup)
7. [Configuration](#configuration)
8. [Running it](#running-it)
9. [Deployment](#deployment)
10. [XML test pipeline](#xml-test-pipeline)
11. [LLM function calling](#llm-function-calling)
12. [SIP trunk integration](#sip-trunk-integration)
13. [Webhook reference](#webhook-reference)
14. [WebSocket event protocol](#websocket-event-protocol)
15. [Audio engineering](#audio-engineering)
16. [Troubleshooting](#troubleshooting)
17. [Security notes](#security-notes)
18. [Roadmap](#roadmap)
19. [Related examples](#related-examples)
20. [Contributing](#contributing)

---

## Overview

Most voice examples show one thing: an IVR menu, or a recording, or a streaming
agent. This repository is the reference implementation that shows the whole
Vobiz XML surface in one running service, and then puts a real AI agent on top
of it. It is the deepest example in the Vobiz XML series and the one to read
first if you want to understand how the pieces fit together.

The service runs in one of two modes, chosen by the `SERVER_MODE` environment
variable and served from the same process on the same port.

In `stream` mode (the default), `/answer` returns a bidirectional `<Stream>`
element pointing at this server's own `/ws` endpoint. Vobiz opens a WebSocket,
pushes mu-law 8 kHz audio frames, and the agent transcribes them with Deepgram
Nova-2, sends the text to GPT-4o-mini, synthesises the reply with OpenAI TTS,
and streams it back as `playAudio` frames. The model has two call-control tools
available to it — `transfer_call` and `end_call` — so it can hand the caller to
a human or hang up cleanly from inside the conversation, using the Vobiz Call
Transfer API to swap the live A-leg onto new XML.

In `test` mode, `/answer` returns a DTMF `<Gather>` menu instead. Each keypress
routes the call to an endpoint that demonstrates one XML element — `<Speak>`,
`<Play>`, `<Record>`, `<Dial>`, `<Stream>`, `<Wait>`, `<Hangup>` — with the
action and callback URLs wired up and every returned parameter logged. It is a
live conformance walk through the XML vocabulary, useful when you are learning
the elements or verifying a trunk end to end.

At the end you have one Python service you can point a Vobiz number or SIP trunk
at, a CLI that places outbound calls into it, and a Docker image that runs the
same code on a server. Local development needs no tunnel configuration: if
`PUBLIC_URL` is empty, the server starts an ngrok tunnel itself and prints the
webhook URLs on the banner.

## What you can build with it

- **An inbound AI receptionist.** Point a Vobiz DID at `/answer` in `stream`
  mode. Callers talk to the agent, and when they ask for a person the model
  calls `transfer_call` and the Vobiz Transfer API dials them through.
- **An outbound qualification or callback bot.** Drive `make_call.py` from a
  cron job or your own backend to place calls into the same agent, with the
  `answer_url` and `hangup_url` set for you.
- **A SIP trunk front door.** Configure `/sip` as the inbound origination URI on
  a Vobiz SIP trunk so calls arriving over SIP get the same XML as PSTN calls,
  and `/trunk-webhook` to log `CallInitiated` and `Hangup` events with duration,
  billsec, cost, MOS, and jitter.
- **An XML conformance harness.** Run in `test` mode to walk a real call through
  every element and read the exact callback parameters Vobiz returns for each —
  `RecordUrl`, `RecordingDuration`, `DialStatus`, `DialBLegUUID`,
  `SpeechConfidenceScore`, and the rest.
- **A voice-agent starting point for your own stack.** The STT, LLM, and TTS
  calls are each a single function in `agent.py`, so swapping a provider is a
  local change rather than a rewrite.
- **A live-transfer demo for a customer call.** Deploy the Docker image on a
  small instance, set `PUBLIC_URL`, and you have a shareable number that
  answers, converses, and transfers.

## How it works

```
Caller (Phone)
  <--PSTN--> Vobiz Cloud
    <--HTTP/WSS--> server.py  (FastAPI — port 8000)
      |                |
      |                +--> /answer, /sip, /test-*, /transfer-*
      |                     /trunk-webhook (SIP events)
      |
      <--WebSocket /ws--> agent.py  (CallSession in-process)
            |
            |--> Deepgram Nova-2  (real-time STT)
            |--> OpenAI GPT-4o-mini  (LLM + function calling)
            |--> OpenAI TTS-1  (speech synthesis)
            |--> Vobiz Call Transfer API  (live transfer / hangup)
```

**Local dev:** an ngrok tunnel is created automatically — no manual setup needed.
**Production:** `PUBLIC_URL` is set to the server's public address, and ngrok is
skipped entirely.

A single turn of conversation, in order:

1. Vobiz sends a `start` event on `/ws`. `CallSession` records `streamId` and
   `callId`, opens a Deepgram WebSocket, and plays a greeting.
2. Each `media` event carries a base64 mu-law frame. The session base64-decodes
   it and forwards the raw bytes straight to Deepgram — no transcoding on the
   inbound leg, because Deepgram is asked for `encoding=mulaw&sample_rate=8000`.
3. Deepgram returns interim and final transcripts. Finals are appended to a
   buffer and a 1.2-second silence timer is restarted; `UtteranceEnd` restarts
   it too. When the timer fires, the buffered text is one user turn.
4. If the agent is still speaking, a `clearAudio` event is sent first so the
   caller can interrupt — that is the barge-in path.
5. The turn goes to GPT-4o-mini with `tools=AGENT_TOOLS` and `tool_choice="auto"`.
   The model either replies with text or requests `transfer_call` / `end_call`.
6. Text replies go to OpenAI TTS as 24 kHz PCM, are resampled to 8 kHz,
   converted to mu-law, split into 160-byte frames, and sent as `playAudio`
   events, followed by a `checkpoint` so the server learns when playback ends.
7. Tool calls play an announcement, then POST to the Vobiz Call Transfer API to
   point the live A-leg at `/transfer-to-number` or `/agent-hangup`, which
   return `<Dial>` or `<Hangup>` XML.

## Architecture

| File | Responsibility |
|---|---|
| `server.py` | FastAPI application. Owns every HTTP webhook, the mode switch, the ngrok tunnel, the startup banner, and the `/ws` WebSocket endpoint that hosts the agent session in-process. |
| `agent.py` | `CallSession` — per-call state, Deepgram STT socket, LLM turn handling with function calling, OpenAI TTS, mu-law conversion and resampling, barge-in, and the Vobiz transfer/hangup API calls. |
| `make_call.py` | CLI that places an outbound call through the Vobiz REST API. Resolves the answer URL from `--answer-url`, `PUBLIC_URL`, or a running local server's `/health`, and prints the equivalent `curl`. |
| `generate_docs.py` | Compiles `DOCS.md` from the metadata for every example in the Vobiz XML Python series. |
| `DOCS.md` | Generated reference covering all the sibling XML examples. Regenerate with `python generate_docs.py` rather than editing by hand. |
| `Dockerfile` | `python:3.11-slim` image with `curl` for the container health check, dependencies installed from `requirements.txt`, port 8000 exposed, `CMD ["python", "server.py"]`. |
| `docker-compose.yml` | Single `vobiz-agent` service: builds the image, maps 8000, passes the environment through, `restart: unless-stopped`, and caps JSON log files at 10 MB × 3. |
| `ec2-setup.sh` | One-shot Ubuntu bootstrap — installs Docker and Compose, clones the repo, seeds `.env` from `.env.example`, and prints the remaining steps. |
| `requirements.txt` | Pinned dependencies: FastAPI, Uvicorn, `websockets`, `openai`, `deepgram-sdk`, `pyngrok`, `requests`, `python-dotenv`, `python-multipart`. |
| `.env.example` | Every environment variable the code reads, with placeholder values. |

```
├── server.py           # FastAPI HTTP server — webhooks, ngrok tunnel, WS handler
├── agent.py            # WebSocket AI agent — STT/LLM/TTS pipeline + function calling
├── make_call.py        # CLI to trigger outbound calls via Vobiz REST API
├── generate_docs.py    # Builds DOCS.md from the XML example series metadata
├── DOCS.md             # Generated docs for the whole XML example series
├── Dockerfile          # Docker image definition (python:3.11-slim)
├── docker-compose.yml  # Docker Compose service config
├── ec2-setup.sh        # One-command Ubuntu server bootstrap script
├── requirements.txt    # Pinned Python dependencies
├── .env.example        # All environment variables documented
├── .dockerignore
└── .gitignore
```

## Prerequisites

| Requirement | Notes |
|---|---|
| Vobiz account | Sign up at [vobiz.ai](https://vobiz.ai). You need the Auth ID and Auth Token from the console. |
| A Vobiz phone number (DID) | Used as `FROM_NUMBER` and as the `callerId` on every transfer B-leg. |
| Python 3.9 or newer | The Docker image pins 3.11. `CallSession` uses `str | None` annotations, so 3.9 is the floor. |
| OpenAI API key | Used for both the LLM (`gpt-4o-mini`) and TTS (`tts-1`). |
| Deepgram API key | Used for streaming STT (`nova-2`). |
| ngrok | Local development only. `pyngrok` starts the tunnel; it reads a token from your system ngrok config, or set `NGROK_AUTH_TOKEN`. |
| Docker and Docker Compose | Server deployment only. `ec2-setup.sh` installs both on Ubuntu. |
| A destination number to call | For `TO_NUMBER` and, in test mode, `DIAL_TEST_NUMBER`. |

## Setup

1. **Clone the repository.**

   ```bash
   git clone https://github.com/vobiz-ai/Vobiz-All-XML-python.git
   cd Vobiz-All-XML-python
   ```

2. **Create and activate a virtual environment.**

   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   ```

3. **Install the dependencies.**

   ```bash
   pip install -r requirements.txt
   ```

4. **Create your `.env`.**

   ```bash
   cp .env.example .env
   ```

5. **Fill in the required values** — `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`,
   `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`, `FROM_NUMBER`, `TO_NUMBER`. Leave
   `PUBLIC_URL` empty for local development so ngrok starts automatically. See
   [Configuration](#configuration) for the full list.

6. **Start the server** and note the public URL on the banner.

   ```bash
   python server.py
   ```

7. **Point Vobiz at it.** In the Vobiz console, set the application's Answer URL
   to `<public-url>/answer` and the Hangup URL to `<public-url>/hangup`. If you
   are using a SIP trunk, set the inbound URI to `<public-url>/sip` and the
   outbound trunk webhook to `<public-url>/trunk-webhook`.

8. **Place a test call.**

   ```bash
   python make_call.py
   ```

## Configuration

All variables are read from the process environment; `python-dotenv` loads `.env`
at import time in `server.py`, `agent.py`, and `make_call.py`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI key. Used for both `gpt-4o-mini` and `tts-1`. |
| `DEEPGRAM_API_KEY` | Yes | — | Deepgram key, sent as `Authorization: Token …` on the STT WebSocket. |
| `VOBIZ_AUTH_ID` | Yes | — | Vobiz account ID. Sent as `X-Auth-ID` and used in the API path. |
| `VOBIZ_AUTH_TOKEN` | Yes | — | Vobiz auth token, sent as `X-Auth-Token`. |
| `FROM_NUMBER` | Yes | — | Your Vobiz DID in E.164. Caller ID for outbound calls and for the `callerId` on every `<Dial>` B-leg. |
| `TO_NUMBER` | Yes | — | Default destination for `make_call.py` when `--to` is omitted. |
| `SERVER_MODE` | No | `stream` | `stream` runs the AI agent; `test` runs the XML test IVR. Any other value falls through to `stream`. |
| `PUBLIC_URL` | No | — | Public base URL of this server. When set, ngrok is skipped and this value is used to build every callback and the WebSocket URL. Trailing slashes are stripped. |
| `NGROK_AUTH_TOKEN` | No | — | ngrok token. If unset, `pyngrok` falls back to your system ngrok configuration. |
| `NGROK_URL` | No | — | Read by `agent.py` to build transfer callback URLs. Normally left unset — the agent auto-detects it from `http://127.0.0.1:<HTTP_PORT>/health`. |
| `AGENT_SYSTEM_PROMPT` | No | `You are a helpful AI phone assistant. Be concise and conversational. Keep responses under 2 sentences.` | Agent personality. The code appends a tool-usage addendum describing `transfer_call` and `end_call`. |
| `OPENAI_TTS_VOICE` | No | `alloy` | One of `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`. |
| `DIAL_TEST_NUMBER` | No | — | Transfer target for test 4. If unset, `/test-dial` speaks an error and returns to the menu. |
| `TEST_AUDIO_URL` | No | `https://actions.google.com/sounds/v1/alarms/beep_short.ogg` | Audio file played by test 2's `<Play>` element. |
| `HTTP_PORT` | No | `8000` | Port Uvicorn binds. Also the port `make_call.py` and `agent.py` probe for `/health`. |
| `AGENT_WS_PORT` | No | `8001` | Port for the standalone WebSocket server in `agent.py`. Only used when `agent.py` is run directly; under `server.py` the session runs in-process on `/ws`. |
| `RENDER_EXTERNAL_URL` | No | — | Fallback base URL read by `make_call.py` when `PUBLIC_URL` is empty. |

## Running it

```bash
source venv/bin/activate
python server.py
```

The startup banner shows the resolved public URL and every webhook path:

```
============================================================
  Vobiz Voice Agent Server

   Mode:           STREAM
   Public URL:     https://xxxx.ngrok-free.app
   Answer URL:     https://xxxx.ngrok-free.app/answer
   Hangup URL:     https://xxxx.ngrok-free.app/hangup
   Health:         https://xxxx.ngrok-free.app/health

   SIP Trunk Endpoints:
     /sip            -> Inbound URI  (Console → SIP → Inbound Trunks)
     /trunk-webhook  -> Webhook URL  (Console → SIP → Outbound Trunks)

============================================================
```

In `test` mode the banner also lists the `/test-*` endpoints.

**Make an outbound call:**

```bash
python make_call.py                              # calls TO_NUMBER from .env
python make_call.py --to +15550003333            # specific number
python make_call.py --from +15550001111          # override the caller ID
python make_call.py --curl                       # print curl, then place the call
python make_call.py --test-endpoint test-speak   # jump straight to a test endpoint
python make_call.py --answer-url https://example.ngrok-free.app/answer
```

`--test-endpoint` accepts `answer`, `test-speak`, `test-play`, `test-record`,
`test-dial`, `test-stream`, `test-wait`, `test-hangup`, and `test-gather-speech`.

**What you should observe.** Answering the call in `stream` mode, you hear
*"Hello! This is the Vobiz AI assistant. How can I help you today?"* and the log
prints `Stream started`, then `Deepgram STT WebSocket connected`, then alternating
`[STT Final]`, `LLM response:`, and `TTS audio generated: … bytes of mulaw` lines.
Interrupting the agent logs `Sent clearAudio (barge-in)`. Asking for a transfer
logs `Executing tool: transfer_call({…})` followed by `Transfer API response:`.

**Check health without a call:**

```bash
curl http://127.0.0.1:8000/health
# {"status":"healthy","ngrok_url":"…","public_url":"…","mode":"stream","production":false}
```

**Kill stale processes if the ports are busy:**

```bash
pkill -9 ngrok
lsof -ti:8000,8001 | xargs kill -9
```

## Deployment

The image is self-contained: `python:3.11-slim`, `curl` for the health check,
pinned dependencies, and `python server.py` as the entrypoint. Port **8000** is
the only port to expose — the WebSocket runs on `/ws` on the same port, so there
is nothing else to open.

**Build and run with Compose:**

```bash
cp .env.example .env
# edit .env — and set PUBLIC_URL to this server's public address
docker compose up -d --build
docker compose logs -f
curl http://localhost:8000/health
```

**Or with plain Docker**, passing the environment at run time rather than baking
it into the image:

```bash
docker build -t vobiz-agent .
docker run -d --name vobiz-agent -p 8000:8000 --env-file .env vobiz-agent
```

`PUBLIC_URL` is the variable that makes the difference between the two modes of
operation. Set it and the server skips ngrok, uses it verbatim for every action,
callback, and redirect URL, and derives the WebSocket URL from it — `https://`
becomes `wss://`, `http://` becomes `ws://`. Prefer an HTTPS address so the
media WebSocket is `wss://`.

Required in the container: `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `VOBIZ_AUTH_ID`,
`VOBIZ_AUTH_TOKEN`, `FROM_NUMBER`, `TO_NUMBER`, `PUBLIC_URL`. Optional:
`SERVER_MODE`, `OPENAI_TTS_VOICE`, `AGENT_SYSTEM_PROMPT`, `DIAL_TEST_NUMBER`,
`TEST_AUDIO_URL`.

### Bootstrapping an Ubuntu server

`ec2-setup.sh` handles a fresh Ubuntu instance end to end.

```bash
# 1. Launch Ubuntu 24.04 (t2.micro is enough) and open ports 22 and 8000
# 2. SSH in
ssh -i <your-key>.pem ubuntu@<server-ip>

# 3. Install Docker, clone the repo, seed .env
curl -fsSL https://raw.githubusercontent.com/vobiz-ai/Vobiz-All-XML-python/main/ec2-setup.sh | bash

# 4. Fill in credentials and set the public address
nano /home/ubuntu/Vobiz-All-XML-python/.env
#    PUBLIC_URL=https://<your-server-hostname>

# 5. Start
cd /home/ubuntu/Vobiz-All-XML-python
newgrp docker
docker compose up -d --build

# 6. Verify
curl http://<server-ip>:8000/health
```

Then set the Answer URL in **Vobiz Console → Applications** to
`<PUBLIC_URL>/answer`.

**Update after a code change:**

```bash
ssh -i <your-key>.pem ubuntu@<server-ip> \
  'cd /home/ubuntu/Vobiz-All-XML-python && git pull && sudo docker compose up -d --build'
```

**Day-to-day commands:**

```bash
sudo docker compose logs -f                             # live logs
sudo docker compose restart                             # restart container
sudo docker compose down && sudo docker compose up -d   # full restart
```

## XML test pipeline

Set `SERVER_MODE=test` to activate the IVR test menu. Calling your number plays:

```
"Welcome to the Vobiz XML test suite.
 Press 1 to test Speak.     Press 2 to test Play.
 Press 3 to test Record.    Press 4 to test Dial transfer.
 Press 5 to test AI Stream. Press 6 to test Wait.
 Press 9 to repeat.         Press 0 to hang up."
```

Each option exercises a specific Vobiz XML element:

| Key | Endpoint | XML elements used |
|---|---|---|
| 1 | `/test-speak` | `<Speak>` (WOMAN/MAN, en-US/en-GB), `<Redirect>` |
| 2 | `/test-play` | `<Play loop="1">` (remote audio URL), `<Speak>`, `<Redirect>` |
| 3 | `/test-record` | `<Record>` (`maxLength="15"`, `playBeep`, `finishOnKey="*"`, `fileFormat="mp3"`), callback reads duration |
| 4 | `/test-dial` | `<Dial>`, `<Number>`, `callerId`, `timeout`, `timeLimit`, action and callback URLs |
| 5 | `/test-stream` | `<Stream bidirectional="true" streamTimeout="120">` (full AI conversation) |
| 6 | `/test-wait` | `<Wait length="3"/>` then `<Wait length="10" silence="true" minSilence="2000"/>` |
| 0 | `/test-hangup` | `<Speak>`, `<Hangup reason="rejected"/>` |
| Menu | `/answer` + `/menu-choice` | `<Gather inputType="dtmf" numDigits="1" executionTimeout="20">`, `<Redirect>` |
| — | `/test-gather-speech` | `<Gather inputType="speech" speechModel="phone_call" speechEndTimeout="3">` — not on the menu, reachable via `--test-endpoint` |

Jump directly to any test from the CLI:

```bash
python make_call.py --test-endpoint test-speak
python make_call.py --test-endpoint test-record
```

Every test endpoint logs the parameters Vobiz posts to it, which is the point of
the exercise — `/test-record-callback` logs `RecordUrl`, `RecordingDuration`,
`RecordingID`, and `RecordingEndReason`; `/test-dial-status` logs `DialStatus`,
`DialHangupCause`, `DialALegUUID`, and `DialBLegUUID`.

## LLM function calling

The AI agent has two tools it can invoke mid-conversation.

### `transfer_call`

Triggered when the caller says something like *"transfer me to +1 555 000 3333"*.

1. GPT detects intent and calls `transfer_call(phone_number="+15550003333")`.
2. The agent plays the announcement via TTS: *"Transferring your call now. Please hold."*
3. The agent POSTs to the Vobiz Transfer API at
   `POST /api/v1/Account/{auth_id}/Call/{call_uuid}/` with
   `{"legs": "aleg", "aleg_url": "<public-url>/transfer-to-number?number=…", "aleg_method": "POST"}`.
4. Vobiz interrupts the `<Stream>` and fetches `/transfer-to-number`.
5. That endpoint returns `<Speak>` plus `<Dial callerId="FROM_NUMBER"><Number>…</Number></Dial>`.
6. The caller is connected. `/transfer-complete` runs when the B-leg ends.

The `announcement` argument is optional; the tool falls back to
*"Transferring your call to &lt;number&gt;. Please hold."* If the API call fails,
the agent speaks an apology and the conversation continues.

### `end_call`

Triggered when the caller says *"goodbye"*, *"bye"*, *"I'm done"*, and similar.

1. GPT calls `end_call(goodbye_message="Goodbye! Have a great day!")`.
2. The agent plays the goodbye via TTS and waits two seconds for playback.
3. The agent points the same Transfer API at `<public-url>/agent-hangup`.
4. Vobiz fetches that endpoint and gets `<Speak>` followed by `<Hangup/>`.

Both tools need `VOBIZ_AUTH_ID` and `VOBIZ_AUTH_TOKEN`, and a resolvable public
URL. The agent resolves that URL from `NGROK_URL` if set, otherwise from the
local `/health` endpoint.

## SIP trunk integration

### Inbound URI — `/sip`

Configure in **Vobiz Console → SIP → Inbound Trunks → Inbound URI**:

```
https://<your-public-host>/sip
```

When a call arrives on the SIP trunk, Vobiz sends a request here and gets back
XML — the AI `<Stream>` or the IVR menu, depending on `SERVER_MODE`. The handler
accepts both POST and GET, and reads call parameters from the form body or the
query string, whichever is present.

### Trunk webhook — `/trunk-webhook`

Configure in **Vobiz Console → SIP → Outbound Trunks → Webhook URL**:

```
https://<your-public-host>/trunk-webhook
```

Events arrive as JSON (the handler falls back to form parsing). The response is
informational only and does not affect the call.

**`CallInitiated`** — fires on every outbound attempt:

```json
{
  "Event": "CallInitiated",
  "CallUUID": "uuid",
  "From": "+15550001111",
  "To": "+15550003333",
  "Allowed": true,
  "Reason": "",
  "TrunkID": "trunk-id",
  "Timestamp": "..."
}
```

A rejected attempt (`"Allowed": false`) is logged at warning level with the
`Reason`.

**`Hangup`** — fires when the call ends, with the CDR:

```json
{
  "Event": "Hangup",
  "Duration": 125,
  "Billsec": 120,
  "RingTime": 4,
  "Cost": 0.75,
  "Currency": "INR",
  "MOS": 4.2,
  "Jitter": 12
}
```

## Webhook reference

| Method | Endpoint | Trigger | Returns |
|---|---|---|---|
| POST | `/answer` | Call connects (stream mode) | `<Stream>` XML |
| POST | `/answer` | Call connects (test mode) | `<Gather>` IVR menu XML |
| POST, GET | `/sip` | Inbound SIP trunk call | `<Stream>` or IVR XML |
| POST | `/hangup` | Call ends | `200 OK` |
| POST | `/stream-status` | Stream lifecycle events | `200 OK` |
| POST, GET | `/trunk-webhook` | SIP trunk events (JSON) | `{"status":"received"}` |
| POST | `/menu-choice` | DTMF digit from Gather | `<Redirect>` XML |
| POST | `/test-speak` | Test 1 | `<Speak>` XML |
| POST | `/test-play` | Test 2 | `<Play>` XML |
| POST | `/test-record` | Test 3 | `<Record>` XML |
| POST | `/test-record-callback` | Record action URL | `<Speak>` + duration, `<Redirect>` |
| POST | `/test-record-result` | Recording file ready | `200 OK` |
| POST | `/test-dial` | Test 4 | `<Dial>` XML |
| POST | `/test-dial-status` | Dial action URL | `<Speak>` + status, `<Redirect>` |
| POST | `/test-dial-events` | Real-time dial events | `200 OK` |
| POST | `/test-stream` | Test 5 | `<Stream>` XML |
| POST | `/test-wait` | Test 6 | `<Wait>` XML |
| POST | `/test-hangup` | Test 0 | `<Hangup>` XML |
| POST | `/test-gather-speech` | Speech Gather demo | `<Gather inputType="speech">` XML |
| POST | `/test-gather-speech-result` | Speech Gather result | `<Speak>` + transcript, `<Redirect>` |
| POST | `/transfer-to-number` | Agent-triggered transfer | `<Dial>` XML |
| POST | `/transfer-complete` | Transfer ended | `<Hangup>` or menu redirect |
| POST | `/transfer-events` | Real-time transfer events | `200 OK` |
| POST | `/agent-hangup` | Agent-triggered hangup | `<Hangup>` XML |
| GET | `/health` | Health check / auto-discovery | JSON |
| WS | `/ws` | Vobiz audio stream | Direct `CallSession` handler |

## WebSocket event protocol

### Events from Vobiz to the agent

```json
{ "event": "start",       "streamId": "s-123", "callId": "c-456" }
{ "event": "media",       "media": { "payload": "<base64-mulaw>", "track": "inbound" } }
{ "event": "playedStream","name": "response-3" }
{ "event": "clearedAudio","streamId": "s-123" }
{ "event": "stop",        "streamId": "s-123" }
```

On `start`, the agent reads the call identifier from `callId`, `start.callId`,
`start.callUUID`, or `CallUUID` — whichever the platform sends — because that
identifier is what the Transfer API needs later.

### Commands from the agent to Vobiz

```json
{ "event": "playAudio",  "media": { "contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": "<base64>" } }
{ "event": "clearAudio", "streamId": "s-123" }
{ "event": "checkpoint", "streamId": "s-123", "name": "response-3" }
```

`checkpoint` is sent after the last audio frame of a reply. Vobiz echoes it back
as `playedStream` with the same `name` once playback finishes, which is how the
agent knows it has stopped speaking and clears `is_playing`.

## Audio engineering

### Outbound pipeline: OpenAI TTS to Vobiz

```
OpenAI TTS-1 (PCM 16-bit, 24kHz)
  → resample_linear(24000 → 8000)    3:1 ratio, linear interpolation
  → pcm16_to_mulaw()                 logarithmic 16-bit → 8-bit compression
  → chunk into 160-byte frames       20ms @ 8kHz mono
  → base64 encode
  → playAudio WebSocket event → Vobiz → Caller
```

### Inbound pipeline: Vobiz to Deepgram

Inbound audio needs no conversion at all. Deepgram is opened with
`encoding=mulaw&sample_rate=8000&channels=1`, so the base64-decoded frame from
Vobiz is forwarded byte for byte. The socket also enables `interim_results`,
`vad_events`, `utterance_end_ms=1000`, and `endpointing=300`.

Vobiz uses **G.711 mu-law (PCMU)** — the global telephony standard. Mu-law uses
a logarithmic scale that prioritises the amplitude range of human speech,
halving bandwidth against linear 16-bit PCM while maintaining perceptual quality
on voice calls.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Address already in use` on startup | A previous run or a stale ngrok process still holds port 8000 or 8001 | `pkill -9 ngrok && lsof -ti:8000,8001 \| xargs kill -9` |
| `Failed to setup ngrok: … ERR_NGROK_334` then exit | An ngrok agent session is already online for that token | `pkill -9 ngrok && python server.py`. The code already retries `ngrok.connect` with `pooling_enabled=True` first. |
| Call connects but you hear nothing | The Answer URL in the Vobiz console still points at a previous ngrok URL — it changes on every restart | Read the new URL from the startup banner or `curl /health`, and update the console. Set `PUBLIC_URL` on a server to make the URL stable. |
| `Deepgram connection error` in the log, agent never responds | `DEEPGRAM_API_KEY` is missing, wrong, or out of credit | Check the key. The greeting still plays because it does not depend on STT, which is the usual clue. |
| `OpenAI TTS error` or `OpenAI TTS returned empty audio` | `OPENAI_API_KEY` is invalid, rate-limited, or out of quota | Check the key and account balance; `generate_tts_audio` returns empty bytes and nothing is played. |
| Test 4 speaks *"No test phone number configured"* | `DIAL_TEST_NUMBER` is not set | Add `DIAL_TEST_NUMBER=+15550003333` to `.env` and restart. |
| Dial test ends with `ORIGINATOR_CANCEL` | The `callerId` is not a DID owned by your account, or the balance is insufficient | Verify `FROM_NUMBER` is your Vobiz DID in E.164 and that the account is funded. |
| `Cannot transfer: VOBIZ_AUTH_ID/TOKEN not set` | The agent process cannot see the Vobiz credentials | Confirm they are in `.env`, or passed through `environment:`/`--env-file` in Docker. |
| `Cannot transfer: ngrok URL not available` | The agent could not resolve the public URL from `/health` | Set `PUBLIC_URL` (or `NGROK_URL`), and check `HTTP_PORT` matches the port the server actually bound. |
| Transfer never fires despite the caller asking | The model did not select the tool | Look for `Executing tool: transfer_call` in the log. If it is absent, make `AGENT_SYSTEM_PROMPT` more explicit about when to transfer. |
| `make_call.py` exits with *"Could not connect to server.py"* | No local server is running and `PUBLIC_URL` is empty | Start `server.py` first, set `PUBLIC_URL`, or pass `--answer-url` explicitly. |
| Agent replies feel slow (roughly 2–3 s) | The turn only starts after a fixed 1.2 s silence window in `_process_after_silence` | Lower the `asyncio.sleep(1.2)` in `agent.py` to around `0.8` — shorter windows respond faster but cut off slower speakers. |
| Caller cannot interrupt the agent | `streamId` was never captured, so `clearAudio` is skipped | Check the `Stream started — streamId=…` log line; a missing ID means the `start` event did not carry one. |
| Container restarts in a loop and `/health` is unhealthy | A required key is missing, so the process exits before Uvicorn binds | `docker compose logs -f` and check the first traceback; the health check probes `http://localhost:8000/health` every 30 s. |
| Vobiz cannot open the media WebSocket | `PUBLIC_URL` is an `http://` address, so the stream URL becomes `ws://` and may be blocked | Put the service behind HTTPS and set `PUBLIC_URL` to the `https://` address so the URL resolves to `wss://`. |

## Security notes

- **The `.env` file holds four sets of credentials** — OpenAI, Deepgram, and the
  Vobiz Auth ID and Token. `.gitignore` excludes `.env` and `.env.*` while
  keeping `.env.example`; keep it that way and never commit a filled-in file.
- **The Dockerfile copies `.env*` into the image** for convenience during local
  builds. Any image built that way contains your keys — do not push it to a
  shared registry. For anything beyond your own machine, build without a `.env`
  present and inject the values at run time with `--env-file` or the Compose
  `environment:` block.
- **The webhook endpoints are unauthenticated.** `/answer`, `/sip`,
  `/menu-choice`, `/trunk-webhook`, and every `/test-*` endpoint will answer any
  caller that finds them, and `/transfer-to-number` takes its destination from a
  query parameter. Before exposing the service beyond a demo, restrict inbound
  traffic to Vobiz source addresses at the firewall or add a shared secret to the
  callback URLs.
- **Run it over TLS.** Media frames and transcripts cross the `/ws` socket in the
  clear on a plain `ws://` connection. Terminate HTTPS in front of the container
  and set `PUBLIC_URL` to the `https://` address so the derived URL is `wss://`.
- **Call audio leaves your infrastructure.** Inbound audio goes to Deepgram and
  reply text goes to OpenAI. If you handle regulated or personal data, check that
  against your own data-processing obligations and your providers' terms.
- **Recordings are hosted by the platform.** Test 3 writes a recording and the
  callback receives a `RecordUrl`. Treat those URLs as sensitive and do not paste
  them into logs you share.
- **Logs are verbose by design.** Caller numbers, transcripts, and full XML bodies
  are written at INFO level, which is what makes this a good learning tool and a
  poor default for a production log sink. Lower the level or filter the fields
  before shipping logs anywhere shared.

## Roadmap

> Planned improvements to this example. Ideas and pull requests are welcome —
> open an issue to discuss anything here.

- [ ] Add an automated test suite — unit tests for `pcm16_to_mulaw` and
      `resample_linear` against known vectors, and webhook tests that assert the
      XML each endpoint returns.
- [ ] Reconnect the Deepgram socket when it drops mid-call. Today
      `send_audio_to_deepgram` clears the handle on `ConnectionClosed` and the
      call continues without transcription until it ends.
- [ ] Add tracing and metrics on the audio path — per-turn STT, LLM, and TTS
      latency, frames sent and received, and barge-in counts — so slow turns can
      be attributed to a stage rather than guessed at.
- [ ] Persist conversations. `conversation_history` lives on the `CallSession`
      and is discarded by `cleanup()`, so transcripts and tool outcomes do not
      survive the call. A pluggable store would enable post-call review.
- [ ] Make the turn-taking tunable. The 1.2-second silence window and the
      160-byte frame size are constants in `agent.py`; exposing them as
      environment variables would let each deployment trade responsiveness
      against interrupting slower speakers.
- [ ] Make the model choices configurable. `gpt-4o-mini`, `tts-1`, and `nova-2`
      are hard-coded; reading them from the environment would let the same code
      run against different models without an edit.
- [ ] Support horizontal scaling across regions. Session state is in-process, so
      every leg of a call must land on the same instance; moving it to a shared
      store would allow more than one replica and a region closer to the caller.

## Related examples

This repository is the hub of the Vobiz XML example series. Each sibling below
is a focused, standalone FastAPI service covering one call flow, and `DOCS.md`
in this repo compiles the reference for all of them.

| Example | What it shows |
|---|---|
| [IVR menu](https://github.com/vobiz-ai/Vobiz-IVR-XML-Python) | Multi-level DTMF menu with runtime-configurable transfer numbers and call analytics |
| [Voicemail](https://github.com/vobiz-ai/Vobiz-Voicemail-XML-Python) | Recording a caller message and retrieving it through an admin API |
| [OTP call](https://github.com/vobiz-ai/Vobiz-OTP-call-XML-Python) | Placing an outbound call that reads a one-time code digit by digit |
| [Appointment reminder](https://github.com/vobiz-ai/-Vobiz-Appointment-reminder-XML-Python) | Outbound reminder with confirm, reschedule, and cancel outcomes |
| [Call survey](https://github.com/vobiz-ai/Vobiz-Call-Survey-XML-Python) | Outbound DTMF survey with a results API and CSV export |
| [Call queue](https://github.com/vobiz-ai/Vobiz-Call-Queue-XML-Python) | Hold music, round-robin agent dispatch, retry cycles, voicemail fallback |
| [Number capture](https://github.com/vobiz-ai/Vobiz-Number-Capture-XML-Python) | Collecting a phone number over the keypad with validation and duplicate detection |
| [Background music](https://github.com/vobiz-ai/Background-Music-Vobiz-Python) | Playing audio underneath a call flow |

## Contributing

Issues and pull requests are welcome. If you hit something that does not work,
open an issue with the relevant log lines — the endpoint names and event names in
the log map directly onto the tables above, which makes most problems quick to
place.

Before opening a pull request:

```bash
source venv/bin/activate
pip install -r requirements.txt
python -c "import server, agent, make_call"   # imports cleanly
python make_call.py --curl --to +15550003333  # CLI still resolves and prints
docker build -t vobiz-agent .                 # image still builds
```

Then place a real call in both `SERVER_MODE=stream` and `SERVER_MODE=test` and
confirm the flows you touched still behave. If you change anything in
`generate_docs.py`, regenerate `DOCS.md` with `python generate_docs.py` and
commit the result. Keep credentials out of diffs and screenshots.

## License

Released under the [MIT License](./LICENSE) © Vobiz.

MIT is permissive: you may use, modify, and redistribute this code, including in
closed-source commercial products, provided the copyright notice and licence text
are retained. There is no warranty. If your organisation needs a different
licensing arrangement, contact [piyush@vobiz.ai](mailto:piyush@vobiz.ai).

## Built by Team Vobiz

[Vobiz](https://vobiz.ai) is a programmable voice and SIP-trunking platform for
voice APIs, SIP trunking, and AI voice agents. This repository is built and
maintained by the Vobiz team.

**Maintainer:** Piyush Sahoo — [piyush@vobiz.ai](mailto:piyush@vobiz.ai) · [LinkedIn](https://www.linkedin.com/in/piyush-s713/)

Questions, or want to talk through an integration? Open an issue on this repo,
or reach out directly at [piyush@vobiz.ai](mailto:piyush@vobiz.ai).

**Useful links:** [Docs](https://docs.vobiz.ai) · [API reference](https://docs.vobiz.ai/api-reference) · [Sign up](https://vobiz.ai)
