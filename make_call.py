"""
make_call.py — Initiate an Outbound Call via Vobiz REST API
=============================================================
Triggers a call from your Vobiz number to a destination number.
The answer_url will point to your server.py's ngrok /answer endpoint.

Usage:
  python make_call.py                     # Auto-detect mode from running server
  python make_call.py --to +919876543210  # Call a specific number
  python make_call.py --test-endpoint test-speak  # Jump directly to a test
"""

import os
import sys
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VOBIZ_AUTH_ID = os.getenv("VOBIZ_AUTH_ID")
VOBIZ_AUTH_TOKEN = os.getenv("VOBIZ_AUTH_TOKEN")
VOBIZ_API_BASE = "https://api.vobiz.ai/api/v1"

FROM_NUMBER = os.getenv("FROM_NUMBER")
TO_NUMBER = os.getenv("TO_NUMBER")


def make_call(to_number: str, from_number: str, answer_url: str, hangup_url: str = None):
    """
    Make an outbound call using the Vobiz REST API.

    Args:
        to_number: Destination phone number (e.g., +919876543210)
        from_number: Caller ID / your Vobiz number (e.g., +919123456789)
        answer_url: The URL Vobiz will call when the call connects
        hangup_url: The URL Vobiz will call when the call ends
    """
    if not VOBIZ_AUTH_ID or not VOBIZ_AUTH_TOKEN:
        print("Error: VOBIZ_AUTH_ID and VOBIZ_AUTH_TOKEN must be set in .env")
        sys.exit(1)

    url = f"{VOBIZ_API_BASE}/Account/{VOBIZ_AUTH_ID}/Call/"

    headers = {
        "Content-Type": "application/json",
        "X-Auth-ID": VOBIZ_AUTH_ID,
        "X-Auth-Token": VOBIZ_AUTH_TOKEN,
    }

    if not hangup_url:
        # Derive hangup URL from answer URL base
        base = answer_url.rsplit("/", 1)[0]
        hangup_url = f"{base}/hangup"

    payload = {
        "from": from_number,
        "to": to_number,
        "answer_url": answer_url,
        "answer_method": "POST",
        "hangup_url": hangup_url,
        "hangup_method": "POST",
    }

    print(f"Making call...")
    print(f"   From: {from_number}")
    print(f"   To:   {to_number}")
    print(f"   Answer URL: {answer_url}")
    print(f"   Hangup URL: {hangup_url}")
    print()

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        call_uuid = data.get("request_uuid", data.get("call_uuid", "unknown"))
        print(f"Call initiated successfully!")
        print(f"   Call UUID: {call_uuid}")
        print(f"   Response: {data}")
        return data

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        print(f"   Response: {e.response.text if e.response else 'No response'}")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"Connection error. Check your internet and Vobiz API URL.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def _auto_detect_ngrok_url() -> str:
    """Try to get the ngrok URL from the running server's health endpoint."""
    try:
        port = os.getenv("HTTP_PORT", "8000")
        health = requests.get(f"http://127.0.0.1:{port}/health", timeout=3)
        health_data = health.json()
        ngrok_url = health_data.get("ngrok_url")
        mode = health_data.get("mode", "stream")
        if ngrok_url:
            print(f"Auto-detected from running server (mode={mode}):")
            print(f"   ngrok URL: {ngrok_url}")
            return ngrok_url
        else:
            print("Error: Could not detect ngrok URL. Is server.py running?")
            sys.exit(1)
    except Exception:
        print(f"Error: Could not connect to server.py at http://127.0.0.1:{port}")
        print("   Make sure server.py is running first, or pass --answer-url manually.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Make an outbound call via Vobiz",
        epilog="""
Examples:
  python make_call.py                              # Default: call TO_NUMBER, auto-detect server
  python make_call.py --to +919876543210           # Call a specific number
  python make_call.py --test-endpoint test-speak   # Jump directly to Speak test
  python make_call.py --test-endpoint test-record  # Jump directly to Record test

Available test endpoints (use with --test-endpoint):
  answer, test-speak, test-play, test-record, test-dial,
  test-stream, test-wait, test-hangup, test-gather-speech
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--to",
        type=str,
        default=TO_NUMBER,
        help="Destination phone number (e.g., +919876543210)",
    )
    parser.add_argument(
        "--from",
        dest="from_number",
        type=str,
        default=FROM_NUMBER,
        help="Caller ID / your Vobiz number (e.g., +919123456789)",
    )
    parser.add_argument(
        "--answer-url",
        type=str,
        default=None,
        help="Answer URL (auto-detected from server.py if not provided)",
    )
    parser.add_argument(
        "--test-endpoint",
        type=str,
        default=None,
        help="Jump directly to a specific test endpoint (e.g., test-speak, test-dial)",
    )

    args = parser.parse_args()

    to_number = args.to
    from_number = args.from_number
    answer_url = args.answer_url

    if not to_number:
        print("Error: --to number is required (or set TO_NUMBER in .env)")
        sys.exit(1)

    if not from_number:
        print("Error: --from number is required (or set FROM_NUMBER in .env)")
        sys.exit(1)

    if not answer_url:
        ngrok_url = _auto_detect_ngrok_url()

        if args.test_endpoint:
            # Point directly to a specific test endpoint
            endpoint = args.test_endpoint.lstrip("/")
            answer_url = f"{ngrok_url}/{endpoint}"
            print(f"   Direct test endpoint: {answer_url}")
        else:
            answer_url = f"{ngrok_url}/answer"
            print(f"   Answer URL: {answer_url}")

    make_call(to_number, from_number, answer_url)


if __name__ == "__main__":
    main()
