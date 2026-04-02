"""
otp_store.py — OTP generation, storage, expiry and verification for 03_otp_call

Flow:
  1. generate(phone)       → creates a 6-digit OTP with 5-min TTL
  2. bind_call(phone, uuid) → links the Vobiz call UUID after outbound call is triggered
  3. get_by_call_uuid(uuid) → Vobiz /answer uses this to read the OTP aloud
  4. mark_delivered(uuid)   → called on /hangup to mark OTP as delivered
  5. verify(phone, otp)     → your app calls this to check what the user typed
"""

import random
import string
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

OTP_LENGTH = 6
OTP_EXPIRY_MINS = 5
MAX_ATTEMPTS = 3


@dataclass
class OTPRecord:
    phone: str
    otp: str
    created_at: datetime
    expires_at: datetime
    attempts: int = 0
    used: bool = False
    call_uuid: Optional[str] = None
    call_status: str = "pending"  # pending | calling | delivered | failed


class OTPStore:
    """
    In-memory OTP store keyed by phone number.
    Production swap: use Redis with TTL keys — one key per phone, auto-expire.
    """

    def __init__(self):
        self._store: dict[str, OTPRecord] = {}  # phone → OTPRecord

    # ── Generation ────────────────────────────────────────────────────────────

    def generate(self, phone: str) -> str:
        """Generate and store a new OTP. Overwrites any existing record for this phone."""
        otp = "".join(random.choices(string.digits, k=OTP_LENGTH))
        now = datetime.utcnow()
        self._store[phone] = OTPRecord(
            phone=phone,
            otp=otp,
            created_at=now,
            expires_at=now + timedelta(minutes=OTP_EXPIRY_MINS),
        )
        return otp

    # ── Call binding ──────────────────────────────────────────────────────────

    def bind_call(self, phone: str, call_uuid: str):
        """Link the Vobiz call UUID once the outbound call is initiated."""
        record = self._store.get(phone)
        if record:
            record.call_uuid = call_uuid
            record.call_status = "calling"

    def get_by_call_uuid(self, call_uuid: str) -> Optional[OTPRecord]:
        """Vobiz /answer uses this to look up which OTP to read aloud."""
        for record in self._store.values():
            if record.call_uuid == call_uuid:
                return record
        return None

    def mark_delivered(self, call_uuid: str):
        record = self.get_by_call_uuid(call_uuid)
        if record:
            record.call_status = "delivered"

    def mark_failed(self, call_uuid: str):
        record = self.get_by_call_uuid(call_uuid)
        if record:
            record.call_status = "failed"

    # ── Verification ──────────────────────────────────────────────────────────

    def verify(self, phone: str, otp: str) -> tuple[bool, str]:
        """
        Verify OTP entered by user.
        Returns (success: bool, reason: str).
        reason values: verified | not_found | expired | already_used | max_attempts | invalid
        """
        record = self._store.get(phone)
        if not record:
            return False, "not_found"
        if record.used:
            return False, "already_used"
        if datetime.utcnow() > record.expires_at:
            return False, "expired"
        if record.attempts >= MAX_ATTEMPTS:
            return False, "max_attempts"

        record.attempts += 1

        if record.otp != otp:
            remaining = MAX_ATTEMPTS - record.attempts
            return False, f"invalid — {remaining} attempt(s) remaining"

        record.used = True
        return True, "verified"

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self, phone: str) -> dict:
        record = self._store.get(phone)
        if not record:
            return {"phone": phone, "status": "not_found"}
        now = datetime.utcnow()
        if record.used:
            status = "used"
        elif now > record.expires_at:
            status = "expired"
        else:
            status = record.call_status
        return {
            "phone": phone,
            "status": status,
            "expires_at": record.expires_at.isoformat(),
            "attempts_used": record.attempts,
            "attempts_remaining": max(0, MAX_ATTEMPTS - record.attempts),
            "call_uuid": record.call_uuid,
        }

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup_expired(self):
        """Remove used + expired records. Call periodically in production."""
        now = datetime.utcnow()
        stale = [p for p, r in self._store.items() if r.used and now > r.expires_at]
        for p in stale:
            del self._store[p]
