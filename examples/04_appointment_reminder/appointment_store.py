"""
appointment_store.py — Appointment storage with status lifecycle for 04_appointment_reminder

Status lifecycle:
  pending → calling → confirmed
                    → reschedule_requested
                    → cancelled
                    → no_answer
  pending → aborted  (manually cancelled before call is made)
"""

import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

STATUS_PENDING = "pending"
STATUS_CALLING = "calling"
STATUS_CONFIRMED = "confirmed"
STATUS_RESCHEDULE = "reschedule_requested"
STATUS_CANCELLED = "cancelled"
STATUS_NO_ANSWER = "no_answer"
STATUS_ABORTED = "aborted"


@dataclass
class Appointment:
    id: str
    phone: str
    name: str
    date: str
    time: str
    status: str
    created_at: datetime
    called_at: Optional[datetime] = None
    outcome_at: Optional[datetime] = None
    call_uuid: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "phone": self.phone,
            "name": self.name,
            "date": self.date,
            "time": self.time,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "called_at": self.called_at.isoformat() if self.called_at else None,
            "outcome_at": self.outcome_at.isoformat() if self.outcome_at else None,
            "call_uuid": self.call_uuid,
        }


class AppointmentStore:
    """
    In-memory appointment store.
    Production swap: write to Postgres/MySQL — one row per appointment,
    updated in-place as status changes.
    """

    def __init__(self):
        self._store: dict[str, Appointment] = {}  # id → Appointment
        self._call_index: dict[str, str] = {}  # call_uuid → appt id

    def create(self, phone: str, name: str, date: str, time: str) -> Appointment:
        appt = Appointment(
            id=str(uuid.uuid4()),
            phone=phone,
            name=name,
            date=date,
            time=time,
            status=STATUS_PENDING,
            created_at=datetime.utcnow(),
        )
        self._store[appt.id] = appt
        return appt

    def bind_call(self, appt_id: str, call_uuid: str):
        """Link the Vobiz call UUID once the outbound call is initiated."""
        appt = self._store.get(appt_id)
        if appt:
            appt.call_uuid = call_uuid
            appt.status = STATUS_CALLING
            appt.called_at = datetime.utcnow()
            self._call_index[call_uuid] = appt_id

    def get_by_call_uuid(self, call_uuid: str) -> Optional[Appointment]:
        appt_id = self._call_index.get(call_uuid)
        return self._store.get(appt_id) if appt_id else None

    def get(self, appt_id: str) -> Optional[Appointment]:
        return self._store.get(appt_id)

    def update_status(self, call_uuid: str, status: str) -> bool:
        appt = self.get_by_call_uuid(call_uuid)
        if not appt:
            return False
        appt.status = status
        appt.outcome_at = datetime.utcnow()
        return True

    def abort(self, appt_id: str) -> bool:
        """Cancel a pending appointment before the call is made."""
        appt = self._store.get(appt_id)
        if not appt or appt.status != STATUS_PENDING:
            return False
        appt.status = STATUS_ABORTED
        appt.outcome_at = datetime.utcnow()
        return True

    def list_all(self, status_filter: str = None) -> list[dict]:
        items = list(self._store.values())
        if status_filter:
            items = [a for a in items if a.status == status_filter]
        return [
            a.to_dict() for a in sorted(items, key=lambda x: x.created_at, reverse=True)
        ]

    def stats(self) -> dict:
        counts: dict[str, int] = {}
        for appt in self._store.values():
            counts[appt.status] = counts.get(appt.status, 0) + 1
        return {"total": len(self._store), "by_status": counts}
