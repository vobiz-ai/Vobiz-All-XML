"""
voicemail_store.py — Voicemail storage for 02_voicemail
"""

import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class Voicemail:
    id: str
    call_uuid: str
    from_number: str
    duration: int  # seconds
    record_url: str  # updated when MP3 is ready via /voicemail-file
    timestamp: datetime
    is_read: bool = False
    transcription: Optional[str] = None  # hook: fill via Whisper/Deepgram

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "call_uuid": self.call_uuid,
            "from": self.from_number,
            "duration_secs": self.duration,
            "record_url": self.record_url,
            "timestamp": self.timestamp.isoformat(),
            "is_read": self.is_read,
            "transcription": self.transcription,
        }


class VoicemailStore:
    """
    In-memory voicemail store.
    Production swap: replace dict with DB (Postgres, DynamoDB, etc.)
    and upload MP3 to S3 / GCS from the record_url.
    """

    def __init__(self):
        self._store: dict[str, Voicemail] = {}  # id → Voicemail
        self._call_index: dict[str, str] = {}  # call_uuid → id

    def save(
        self,
        call_uuid: str,
        from_number: str,
        duration: int,
        record_url: str,
    ) -> Voicemail:
        vm = Voicemail(
            id=str(uuid.uuid4()),
            call_uuid=call_uuid,
            from_number=from_number,
            duration=duration,
            record_url=record_url,
            timestamp=datetime.utcnow(),
        )
        self._store[vm.id] = vm
        self._call_index[call_uuid] = vm.id
        return vm

    def update_url(self, call_uuid: str, record_url: str):
        """Called from /voicemail-file when the final MP3 URL is ready."""
        vm_id = self._call_index.get(call_uuid)
        if vm_id and vm_id in self._store:
            self._store[vm_id].record_url = record_url

    def get(self, vm_id: str) -> Optional[Voicemail]:
        return self._store.get(vm_id)

    def list_all(self) -> list[dict]:
        return [
            vm.to_dict()
            for vm in sorted(
                self._store.values(), key=lambda x: x.timestamp, reverse=True
            )
        ]

    def mark_read(self, vm_id: str) -> bool:
        vm = self._store.get(vm_id)
        if not vm:
            return False
        vm.is_read = True
        return True

    def delete(self, vm_id: str) -> bool:
        vm = self._store.pop(vm_id, None)
        if not vm:
            return False
        self._call_index.pop(vm.call_uuid, None)
        return True

    def stats(self) -> dict:
        total = len(self._store)
        unread = sum(1 for vm in self._store.values() if not vm.is_read)
        return {"total": total, "unread": unread, "read": total - unread}
