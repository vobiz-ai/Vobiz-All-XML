"""
lead_store.py — Captured phone number (lead) storage for 08_number_capture
"""

import csv
import io
import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class Lead:
    id: str
    captured_number: str  # the number the caller entered
    caller_number: str  # the From number (caller's own number)
    call_uuid: str
    timestamp: datetime
    confirmed: bool = True
    is_duplicate: bool = False  # True if this number was captured before

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "captured_number": self.captured_number,
            "caller_number": self.caller_number,
            "call_uuid": self.call_uuid,
            "timestamp": self.timestamp.isoformat(),
            "confirmed": self.confirmed,
            "is_duplicate": self.is_duplicate,
        }


class LeadStore:
    """
    In-memory lead store with duplicate detection.
    Production swap: write to Postgres/MySQL — check for existing number before INSERT.
    """

    def __init__(self):
        self._store: dict[str, Lead] = {}  # lead id → Lead
        self._seen: set[str] = set()  # captured_numbers seen so far

    def save(
        self,
        captured_number: str,
        caller_number: str,
        call_uuid: str,
    ) -> Lead:
        is_dup = captured_number in self._seen
        lead = Lead(
            id=str(uuid.uuid4()),
            captured_number=captured_number,
            caller_number=caller_number,
            call_uuid=call_uuid,
            timestamp=datetime.utcnow(),
            confirmed=True,
            is_duplicate=is_dup,
        )
        self._store[lead.id] = lead
        self._seen.add(captured_number)
        return lead

    def get(self, lead_id: str) -> Optional[Lead]:
        return self._store.get(lead_id)

    def delete(self, lead_id: str) -> bool:
        lead = self._store.pop(lead_id, None)
        if not lead:
            return False
        # Only remove from seen-set if no other lead has the same number
        still_exists = any(
            l.captured_number == lead.captured_number for l in self._store.values()
        )
        if not still_exists:
            self._seen.discard(lead.captured_number)
        return True

    def list_all(self, include_duplicates: bool = True) -> list[dict]:
        items = list(self._store.values())
        if not include_duplicates:
            items = [l for l in items if not l.is_duplicate]
        return [
            l.to_dict() for l in sorted(items, key=lambda x: x.timestamp, reverse=True)
        ]

    def export_csv(self) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "captured_number",
                "caller_number",
                "call_uuid",
                "timestamp",
                "is_duplicate",
            ]
        )
        for l in sorted(self._store.values(), key=lambda x: x.timestamp):
            writer.writerow(
                [
                    l.id,
                    l.captured_number,
                    l.caller_number,
                    l.call_uuid,
                    l.timestamp.isoformat(),
                    l.is_duplicate,
                ]
            )
        return output.getvalue()

    def analytics(self) -> dict:
        total = len(self._store)
        unique = len(self._seen)
        today = datetime.utcnow().date()
        today_count = sum(
            1 for l in self._store.values() if l.timestamp.date() == today
        )
        return {
            "total": total,
            "unique": unique,
            "duplicates": total - unique,
            "today": today_count,
        }
