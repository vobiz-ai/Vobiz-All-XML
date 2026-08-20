# Vobiz AI Voice Agent — Full XML Pipeline

A production-grade AI voice agent that handles real phone calls using Vobiz telephony, Deepgram STT, OpenAI GPT-4o-mini, and OpenAI TTS. Supports a full Vobiz XML test pipeline, LLM function calling for live call transfers, SIP trunk integration, and Docker-based EC2 deployment.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [Features](#2-features)
3. [Project Structure](#3-project-structure)
4. [XML Test Pipeline](#4-xml-test-pipeline)
5. [LLM Function Calling](#5-llm-function-calling)
6. [SIP Trunk Integration](#6-sip-trunk-integration)
7. [Webhook Reference](#7-webhook-reference)
8. [WebSocket Event Protocol](#8-websocket-event-protocol)
9. [Audio Engineering](#9-audio-engineering)
10. [Setup & Installation](#10-setup--installation)
11. [Running Locally](#11-running-locally)
12. [Deploying to EC2](#12-deploying-to-ec2)
13. [Environment Variables](#13-environment-variables)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Architecture

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

**Local dev:** ngrok tunnel is created automatically — no manual setup needed.
**Production (EC2):** `PUBLIC_URL` is set to EC2 IP — ngrok is skipped entirely.

---

## 2. Features

- **Bidirectional audio streaming** — mu-law 8kHz WebSocket stream with barge-in support
- **Real-time STT** — Deepgram Nova-2 via raw WebSocket, no SDK overhead
- **LLM reasoning** — GPT-4o-mini with OpenAI function calling
- **Live call transfer** — agent says "transferring you" and calls the Vobiz Transfer API mid-conversation
- **Graceful hangup** — agent detects goodbye and terminates the call via API
- **Full XML test pipeline** — IVR menu that demos every Vobiz XML element (Speak, Play, Record, Dial, Stream, Wait, Gather, Hangup, Redirect)
- **SIP trunk endpoints** — `/sip` origination URI and `/trunk-webhook` for CallInitiated/Hangup events
- **Docker + EC2 deployment** — `Dockerfile` + `docker-compose.yml` + `ec2-setup.sh` for one-command production deploy
- **Dual-mode** — `SERVER_MODE=stream` for AI agent, `SERVER_MODE=test` for XML test pipeline

---

## 3. Project Structure

```
├── server.py          # FastAPI HTTP server — webhooks, ngrok tunnel, WS handler
├── agent.py           # WebSocket AI agent — STT/LLM/TTS pipeline + function calling
├── make_call.py       # CLI to trigger outbound calls via Vobiz REST API
├── Dockerfile         # Docker image definition (python:3.11-slim)
├── docker-compose.yml # Docker Compose service config for EC2
├── ec2-setup.sh       # One-command EC2 bootstrap script
├── requirements.txt   # Pinned Python dependencies
├── .env.example       # All environment variables documented
└── .gitignore
```

| File | Role | Lines |
|---|---|---|
| `server.py` | Orchestration — HTTP webhooks, tunnel, WS handler, all XML endpoints | ~900 |
| `agent.py` | Intelligence — audio pipeline, LLM, TTS, function calling | ~550 |
| `make_call.py` | Connectivity — Vobiz REST API caller, auto-detect server URL | ~180 |

---

## 4. XML Test Pipeline

Set `SERVER_MODE=test` to activate the IVR test menu. Calling your number plays:

```
"Welcome to the Vobiz XML test suite.
 Press 1 to test Speak.     Press 2 to test Play.
 Press 3 to test Record.    Press 4 to test Dial transfer.
 Press 5 to test AI Stream. Press 6 to test Wait.
 Press 9 to repeat.         Press 0 to hang up."
```

Each option exercises a specific Vobiz XML element:

| Key | Endpoint | XML Elements Used |
|---|---|---|
| 1 | `/test-speak` | `<Speak>` (WOMAN/MAN, en-US/en-GB), `<Redirect>` |
| 2 | `/test-play` | `<Play>` (remote MP3), `<Speak>`, `<Redirect>` |
| 3 | `/test-record` | `<Record>` (15s, beep, star to stop), callback reads duration |
| 4 | `/test-dial` | `<Dial>`, `<Number>`, callerId, action URL |
| 5 | `/test-stream` | `<Stream>` bidirectional (full AI conversation) |
| 6 | `/test-wait` | `<Wait>` (3s basic + silence detection) |
| 0 | `/test-hangup` | `<Speak>`, `<Hangup reason="rejected">` |
| Menu | `/answer` + `/menu-choice` | `<Gather>` DTMF, `<Redirect>` |

Jump directly to any test from CLI:
```bash
python make_call.py --test-endpoint test-speak
python make_call.py --test-endpoint test-record
```

---

## 5. LLM Function Calling

The AI agent has two tools it can invoke mid-conversation:

### `transfer_call`
Triggered when the caller says something like *"transfer me to +1 555 000 3333"*.

**Flow:**
1. GPT detects intent → calls `transfer_call(phone_number="+15550003333")`
2. Agent plays announcement via TTS: *"Transferring your call now. Please hold."*
3. Agent POSTs to Vobiz Transfer API: `POST /Account/{id}/Call/{uuid}/`
4. Vobiz interrupts the Stream and fetches `/transfer-to-number?number=+15550003333`
5. That endpoint returns `<Dial><Number>+15550003333</Number></Dial>` XML
6. Caller is connected to the target number

### `end_call`
Triggered when the caller says *"goodbye"*, *"bye"*, *"I'm done"*, etc.

**Flow:**
1. GPT detects farewell → calls `end_call(goodbye_message="Goodbye! Have a great day!")`
2. Agent plays goodbye via TTS
3. Agent calls Vobiz Transfer API pointing to `/agent-hangup`
4. Vobiz fetches that endpoint and gets `<Hangup/>` XML

---

## 6. SIP Trunk Integration

### Inbound URI — `/sip`
Configure in **Vobiz Console → SIP → Inbound Trunks → Inbound URI**:
```
http://13.233.163.77:8000/sip
```
When a call arrives on the SIP trunk, Vobiz POSTs here and gets back XML (AI Stream or IVR menu depending on `SERVER_MODE`).

### Trunk Webhook — `/trunk-webhook`
Configure in **Vobiz Console → SIP → Outbound Trunks → Webhook URL**:
```
http://13.233.163.77:8000/trunk-webhook
```

Receives JSON events:

**`CallInitiated`** — fires on every outbound attempt:
```json
{
  "Event": "CallInitiated",
  "CallUUID": "uuid",
  "From": "+15550001111",
  "To": "+15550003333",
  "Allowed": true,
  "Reason": ""
}
```

**`Hangup`** — fires when call ends with full CDR:
```json
{
  "Event": "Hangup",
  "Duration": 125,
  "Billsec": 120,
  "Cost": 0.75,
  "Currency": "INR",
  "MOS": 4.2,
  "Jitter": 12
}
```

---

## 7. Webhook Reference

| Method | Endpoint | Trigger | Returns |
|---|---|---|---|
| POST | `/answer` | Call connects (stream mode) | `<Stream>` XML |
| POST | `/answer` | Call connects (test mode) | `<Gather>` IVR menu XML |
| POST | `/sip` | Inbound SIP trunk call | `<Stream>` or IVR XML |
| POST | `/hangup` | Call ends | `200 OK` |
| POST | `/stream-status` | Stream lifecycle events | `200 OK` |
| POST | `/trunk-webhook` | SIP trunk events (JSON) | `{"status":"received"}` |
| POST | `/menu-choice` | DTMF digit from Gather | `<Redirect>` XML |
| POST | `/test-speak` | Test 1 | `<Speak>` XML |
| POST | `/test-play` | Test 2 | `<Play>` XML |
| POST | `/test-record` | Test 3 | `<Record>` XML |
| POST | `/test-record-callback` | Recording done | `<Speak>` + duration |
| POST | `/test-dial` | Test 4 | `<Dial>` XML |
| POST | `/test-dial-status` | Dial completed | `<Speak>` + status |
| POST | `/test-stream` | Test 5 | `<Stream>` XML |
| POST | `/test-wait` | Test 6 | `<Wait>` XML |
| POST | `/test-hangup` | Test 0 | `<Hangup>` XML |
| POST | `/transfer-to-number` | Agent-triggered transfer | `<Dial>` XML |
| POST | `/transfer-complete` | Transfer ended | `<Hangup>` or menu |
| POST | `/agent-hangup` | Agent-triggered hangup | `<Hangup>` XML |
| GET | `/health` | Health check / auto-discover | JSON |
| WS | `/ws` | Vobiz audio stream | Direct CallSession handler |

---

## 8. WebSocket Event Protocol

### Events FROM Vobiz to Agent

```json
{ "event": "start",       "streamId": "s-123", "callId": "c-456" }
{ "event": "media",       "media": { "payload": "<base64-mulaw>", "track": "inbound" } }
{ "event": "playedStream","name": "response-3" }
{ "event": "clearedAudio","streamId": "s-123" }
{ "event": "stop",        "streamId": "s-123" }
```

### Commands FROM Agent to Vobiz

```json
{ "event": "playAudio",  "media": { "contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": "<base64>" } }
{ "event": "clearAudio", "streamId": "s-123" }
{ "event": "checkpoint", "streamId": "s-123", "name": "response-3" }
```

---

## 9. Audio Engineering

### Pipeline: OpenAI TTS → Vobiz

```
OpenAI TTS-1 (PCM 16-bit, 24kHz)
  → resample_linear(24000 → 8000)    3:1 ratio, linear interpolation
  → pcm16_to_mulaw()                 logarithmic 16-bit → 8-bit compression
  → chunk into 160-byte frames       20ms @ 8kHz mono
  → base64 encode
  → playAudio WebSocket event → Vobiz → Caller
```

Vobiz uses **G.711 mu-law (PCMU)** — the global telephony standard. Mu-law uses a logarithmic scale that prioritizes the amplitude range of human speech, halving bandwidth vs linear 16-bit PCM while maintaining perceptual quality on voice calls.

---

## 10. Setup & Installation

**Prerequisites:** Python 3.9+, ngrok (local dev only), API keys for Deepgram and OpenAI, Vobiz account.

```bash
git clone git@github.com:Piyush-sahoo/Vobiz-Call-All-XML.git
cd Vobiz-Call-All-XML

python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Fill in your API keys in .env
```

---

## 11. Running Locally

```bash
source venv/bin/activate
python server.py
```

The startup banner shows your ngrok URL:
```
============================================================
  Vobiz Voice Agent Server
   Mode:       STREAM
   Public URL: https://xxxx.ngrok-free.app
   Answer URL: https://xxxx.ngrok-free.app/answer
   SIP URI:    https://xxxx.ngrok-free.app/sip
============================================================
```

**Make an outbound call:**
```bash
python make_call.py                              # calls TO_NUMBER from .env
python make_call.py --to +15550003333           # specific number
python make_call.py --curl                       # print curl + make call
python make_call.py --test-endpoint test-speak   # jump to specific test
```

**Kill stale processes if ports are busy:**
```bash
pkill -9 ngrok
lsof -ti:8000,8001 | xargs kill -9
```

---

## 12. Deploying to EC2

### One-time setup

```bash
# 1. Launch Ubuntu 24.04 t2.micro, open ports 22 + 8000

# 2. SSH in
ssh -i vobizxml.pem ubuntu@<ec2-ip>

# 3. Run setup script (installs Docker, clones repo, creates .env)
curl -fsSL https://raw.githubusercontent.com/vobiz-ai/Vobiz-All-XML/main/ec2-setup.sh | bash

# 4. Edit .env with your credentials
nano /home/ubuntu/Vobiz-All-XML/.env
# Set: PUBLIC_URL=http://<ec2-ip>:8000

# 5. Start
cd /home/ubuntu/Vobiz-All-XML
newgrp docker
docker compose up -d --build

# 6. Verify
curl http://<ec2-ip>:8000/health
```

Set in **Vobiz Console → Applications → Answer URL:**
```
http://<ec2-ip>:8000/answer
```

### Update after code changes

```bash
# Push to GitHub, then on EC2:
ssh -i vobizxml.pem ubuntu@<ec2-ip> \
  'cd /home/ubuntu/Vobiz-All-XML && git pull && sudo docker compose up -d --build'
```

### Useful EC2 commands

```bash
sudo docker compose logs -f          # live logs
sudo docker compose restart          # restart container
sudo docker compose down && sudo docker compose up -d  # full restart
```

---

## 13. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI key (LLM + TTS) |
| `DEEPGRAM_API_KEY` | Yes | — | Deepgram key (STT) |
| `VOBIZ_AUTH_ID` | Yes | — | Vobiz account ID |
| `VOBIZ_AUTH_TOKEN` | Yes | — | Vobiz auth token |
| `FROM_NUMBER` | Yes | — | Your Vobiz DID number (E.164) |
| `TO_NUMBER` | Yes | — | Default destination number |
| `SERVER_MODE` | No | `stream` | `stream` = AI agent, `test` = XML pipeline |
| `PUBLIC_URL` | No | — | EC2 public URL — skips ngrok (e.g. `http://13.233.163.77:8000`) |
| `AGENT_SYSTEM_PROMPT` | No | built-in | Agent personality |
| `OPENAI_TTS_VOICE` | No | `alloy` | alloy / echo / fable / onyx / nova / shimmer |
| `DIAL_TEST_NUMBER` | No | — | Transfer target for Dial test |
| `TEST_AUDIO_URL` | No | Google beep | MP3/WAV URL for Play test |
| `HTTP_PORT` | No | `8000` | HTTP server port |
| `AGENT_WS_PORT` | No | `8001` | Internal WebSocket agent port |
| `NGROK_AUTH_TOKEN` | No | — | ngrok token (reads from system config automatically) |

---

## 14. Troubleshooting

| Problem | Fix |
|---|---|
| `Address already in use` | `pkill -9 ngrok && lsof -ti:8000,8001 \| xargs kill -9` |
| `ngrok ERR_NGROK_334` | `pkill -9 ngrok && sleep 1 && python server.py` |
| Agent crashes on startup | Check all required env vars are set in `.env` |
| Dial test `ORIGINATOR_CANCEL` | Verify `FROM_NUMBER` is a DID owned by your Vobiz account and balance is sufficient |
| Transfer not working | Check server logs for `Executing tool: transfer_call` — verify `VOBIZ_AUTH_ID`/`TOKEN` are set |
| Slow AI responses (~2-3s) | Reduce `asyncio.sleep(1.2)` in `agent.py` to `0.8` for faster response |
| Can't hear AI | Verify Answer URL in Vobiz console matches your current server URL |

---

## Built by Team Vobiz

[Vobiz](https://vobiz.ai) is a programmable voice & SIP-trunking platform for
voice APIs, SIP trunking, and AI voice agents. This repository is built and
maintained by the Vobiz team.

**Maintainer:** Piyush Sahoo — [piyush@vobiz.ai](mailto:piyush@vobiz.ai) · [LinkedIn](https://www.linkedin.com/in/piyush-s713/)

Questions, or want to talk through an integration? Open an issue on this repo,
or reach out directly at [piyush@vobiz.ai](mailto:piyush@vobiz.ai).

**Useful links:** [Docs](https://docs.vobiz.ai) · [API reference](https://docs.vobiz.ai/api-reference) · [Sign up](https://vobiz.ai)

## License

[MIT](./LICENSE) © Vobiz
