"""
menu_config.py — Dynamic menu configuration + call log for 01_ivr_menu
"""

import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class Department:
    id: str
    name: str
    number: str
    enabled: bool = True


@dataclass
class CallLogEntry:
    id: str
    call_uuid: str
    from_number: str
    digit: str
    department: Optional[str]
    dial_status: Optional[str]
    timestamp: datetime


class MenuConfig:
    """
    Stores department config (names, transfer numbers, enabled flags)
    and a log of every call + digit pressed.

    In production: replace _departments and _call_logs with DB reads/writes.
    """

    def __init__(self, default_operator_number: str = ""):
        self._departments: dict[str, Department] = {
            "sales": Department("sales", "Sales", default_operator_number, True),
            "support": Department(
                "support", "Technical Support", default_operator_number, True
            ),
            "billing": Department("billing", "Billing", default_operator_number, True),
            "account": Department(
                "account", "Account Management", default_operator_number, True
            ),
            "operator": Department(
                "operator", "Operator", default_operator_number, True
            ),
        }
        self._call_logs: list[CallLogEntry] = []

    # ── Department config ─────────────────────────────────────────────────────

    def get_department(self, dept_id: str) -> Optional[Department]:
        return self._departments.get(dept_id)

    def get_all(self) -> dict:
        return {
            k: {"id": v.id, "name": v.name, "number": v.number, "enabled": v.enabled}
            for k, v in self._departments.items()
        }

    def update_department(
        self,
        dept_id: str,
        number: str = None,
        enabled: bool = None,
        name: str = None,
    ) -> bool:
        dept = self._departments.get(dept_id)
        if not dept:
            return False
        if number is not None:
            dept.number = number
        if enabled is not None:
            dept.enabled = enabled
        if name is not None:
            dept.name = name
        return True

    # ── Call logging ──────────────────────────────────────────────────────────

    def log_call(
        self,
        call_uuid: str,
        from_number: str,
        digit: str,
        department: str = None,
    ) -> str:
        entry = CallLogEntry(
            id=str(uuid.uuid4()),
            call_uuid=call_uuid,
            from_number=from_number,
            digit=digit,
            department=department,
            dial_status=None,
            timestamp=datetime.utcnow(),
        )
        self._call_logs.append(entry)
        return entry.id

    def update_dial_status(self, call_uuid: str, status: str):
        for entry in reversed(self._call_logs):
            if entry.call_uuid == call_uuid:
                entry.dial_status = status
                break

    def get_logs(self) -> list[dict]:
        return [
            {
                "id": e.id,
                "call_uuid": e.call_uuid,
                "from": e.from_number,
                "digit": e.digit,
                "department": e.department,
                "dial_status": e.dial_status,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in sorted(self._call_logs, key=lambda x: x.timestamp, reverse=True)
        ]

    def get_analytics(self) -> dict:
        total = len(self._call_logs)
        if total == 0:
            return {"total_calls": 0, "by_department": {}}

        by_dept: dict[str, int] = {}
        for entry in self._call_logs:
            dept = entry.department or "unknown"
            by_dept[dept] = by_dept.get(dept, 0) + 1

        return {
            "total_calls": total,
            "by_department": {
                k: {"count": v, "percentage": round(v / total * 100, 1)}
                for k, v in sorted(by_dept.items(), key=lambda x: x[1], reverse=True)
            },
        }
