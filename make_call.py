"""
make_call.py — Initiate an Outbound Call via Vobiz REST API
=============================================================
Triggers a call from your Vobiz number to a destination number.

Usage:
  python make_call.py                              # Call TO_NUMBER via auto-detected server
  python make_call.py --to +919876543210           # Call a specific number
  python make_call.py --test-endpoint test-speak   # Jump directly to a test endpoint
  python make_call.py --curl                       # Print curl command only (don't call)
  python make_call.py --to +919876543210 --curl    # Print curl for a specific number
"""

import os
import sys
import json
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VOBIZ_AUTH_ID    = os.getenv("VOBIZ_AUTH_ID", "")
VOBIZ_AUTH_TOKEN = os.getenv("VOBIZ_AUTH_TOKEN", "")
VOBIZ_API_BASE   = "https://api.vobiz.ai/api/v1"

FROM_NUMBER = os.getenv("FROM_NUMBER", "")
TO_NUMBER   = os.getenv("TO_NUMBER", "")

# Production Render URL (used when server.py is not running locally)
PUBLIC_URL = os.getenv("PUBLIC_URL", os.getenv("RENDER_EXTERNAL_URL", ""))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_payload(from_number: str, to_number: str, answer_url: str) -> dict:
    base = answer_url.rsplit("/", 1)[0]
    hangup_url = f"{base}/hangup"
    return {
        "from":          from_number,
        "to":            to_number,
        "answer_url":    answer_url,
        "answer_method": "POST",
        "hangup_url":    hangup_url,
        "hangup_method": "POST",
    }


def _print_curl(from_number: str, to_number: str, answer_url: str):
    """Print a ready-to-run curl command for the call."""
    if not VOBIZ_AUTH_ID or not VOBIZ_AUTH_TOKEN:
        print("# Note: set VOBIZ_AUTH_ID and VOBIZ_AUTH_TOKEN in .env first")

    payload = _build_payload(from_number, to_number, answer_url)
    url     = f"{VOBIZ_API_BASE}/Account/{VOBIZ_AUTH_ID}/Call/"

    print()
    print("# ── Copy-paste this curl to trigger the call ──────────────────")
    print(f"curl -X POST '{url}' \\")
    print(f"  -H 'Content-Type: application/json' \\")
    print(f"  -H 'X-Auth-ID: {VOBIZ_AUTH_ID}' \\")
    print(f"  -H 'X-Auth-Token: {VOBIZ_AUTH_TOKEN}' \\")
    print(f"  -d '{json.dumps(payload)}'")
    print("# ────────────────────────────────────────────────────────────────")
    print()


def make_call(to_number: str, from_number: str, answer_url: str, print_curl: bool = False):
    """Make an outbound call via the Vobiz REST API."""
    if not VOBIZ_AUTH_ID or not VOBIZ_AUTH_TOKEN:
        print("Error: VOBIZ_AUTH_ID and VOBIZ_AUTH_TOKEN must be set in .env")
        sys.exit(1)

    url     = f"{VOBIZ_API_BASE}/Account/{VOBIZ_AUTH_ID}/Call/"
    headers = {
        "Content-Type": "application/json",
        "X-Auth-ID":    VOBIZ_AUTH_ID,
        "X-Auth-Token": VOBIZ_AUTH_TOKEN,
    }
    payload = _build_payload(from_number, to_number, answer_url)

    print(f"Making call...")
    print(f"   From:       {from_number}")
    print(f"   To:         {to_number}")
    print(f"   Answer URL: {answer_url}")
    print(f"   Hangup URL: {payload['hangup_url']}")
    print()

    # Always show the equivalent curl for reference
    _print_curl(from_number, to_number, answer_url)

    if print_curl:
        return  # --curl flag: just print, don't call

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        call_uuid = data.get("request_uuid", data.get("call_uuid", "unknown"))
        print(f"Call initiated successfully!")
        print(f"   Call UUID: {call_uuid}")
        print(f"   Response:  {data}")
        return data

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        print(f"   Response: {e.response.text if e.response else 'No response'}")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print("Connection error. Check your internet and Vobiz API URL.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def _resolve_answer_url(args) -> str:
    """Resolve the answer URL from args, PUBLIC_URL, or running local server."""
    if args.answer_url:
        return args.answer_url

    # Use production URL if set
    base_url = PUBLIC_URL
    if not base_url:
        base_url = _auto_detect_local_url()

    endpoint = args.test_endpoint.lstrip("/") if args.test_endpoint else "answer"
    url = f"{base_url}/{endpoint}"

    if args.test_endpoint:
        print(f"   Direct test endpoint: {url}")
    else:
        print(f"   Answer URL: {url}")

    return url


def _auto_detect_local_url() -> str:
    """Get public URL from the running local server's health endpoint."""
    port = os.getenv("HTTP_PORT", "8000")
    try:
        health = requests.get(f"http://127.0.0.1:{port}/health", timeout=3)
        data   = health.json()
        url    = data.get("public_url") or data.get("ngrok_url", "")
        mode   = data.get("mode", "stream")
        if url:
            print(f"Auto-detected from running server (mode={mode}): {url}")
            return url
        print("Error: Could not detect server URL. Is server.py running?")
        sys.exit(1)
    except Exception:
        print(f"Error: Could not connect to server.py at http://127.0.0.1:{port}")
        print("   Start server.py first, or set PUBLIC_URL in .env, or pass --answer-url")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Make an outbound call via Vobiz (or print the curl equivalent)",
        epilog="""
Examples:
  python make_call.py                                         # Call TO_NUMBER via auto-detected URL
  python make_call.py --to +919876543210                      # Call a specific number
  python make_call.py --curl                                  # Print curl command only
  python make_call.py --to +919876543210 --curl               # Print curl for specific number
  python make_call.py --test-endpoint test-speak              # Jump to Speak XML test
  python make_call.py --test-endpoint test-stream --curl      # Print curl for Stream test
  python make_call.py --answer-url https://vobiz-all-xml.onrender.com/answer  # Use Render URL

Available --test-endpoint values:
  answer, test-speak, test-play, test-record, test-dial,
  test-stream, test-wait, test-hangup, test-gather-speech
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--to",
        type=str,
        default=TO_NUMBER,
        help="Destination phone number in E.164 format (e.g. +919876543210)",
    )
    parser.add_argument(
        "--from",
        dest="from_number",
        type=str,
        default=FROM_NUMBER,
        help="Caller ID — your Vobiz DID number (e.g. +911171366941)",
    )
    parser.add_argument(
        "--answer-url",
        type=str,
        default=None,
        help="Full answer URL. Auto-detected from PUBLIC_URL or running server if omitted.",
    )
    parser.add_argument(
        "--test-endpoint",
        type=str,
        default=None,
        metavar="ENDPOINT",
        help="Route call directly to a test endpoint (e.g. test-speak, test-dial)",
    )
    parser.add_argument(
        "--curl",
        action="store_true",
        default=False,
        help="Print the curl command only — do not make the actual call",
    )

    args = parser.parse_args()

    to_number   = args.to
    from_number = args.from_number

    if not to_number:
        print("Error: --to is required (or set TO_NUMBER in .env)")
        sys.exit(1)
    if not from_number:
        print("Error: --from is required (or set FROM_NUMBER in .env)")
        sys.exit(1)

    answer_url = _resolve_answer_url(args)
    make_call(to_number, from_number, answer_url, print_curl=args.curl)


if __name__ == "__main__":
    main()
