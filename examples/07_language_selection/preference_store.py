"""
preference_store.py — Caller language preference storage for 07_language_selection

Stores the language a caller chose last time so /answer can skip the menu
and route them directly on repeat calls.
"""

from datetime import datetime
from dataclasses import dataclass
from typing import Optional


SUPPORTED_LANGUAGES: dict[str, dict] = {
    "en": {"label": "English", "tts_code": "en-US"},
    "hi": {"label": "Hindi", "tts_code": "hi-IN"},
}


@dataclass
class CallerPreference:
    phone: str
    language: str  # "en" | "hi"
    call_count: int
    first_seen: datetime
    last_seen: datetime

    def to_dict(self) -> dict:
        lang_info = SUPPORTED_LANGUAGES.get(self.language, {})
        return {
            "phone": self.phone,
            "language": self.language,
            "language_label": lang_info.get("label", self.language),
            "call_count": self.call_count,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
        }


class PreferenceStore:
    """
    In-memory preference store keyed by phone number.
    Production swap: use Redis HSET per phone, or a DB table with upsert.
    """

    def __init__(self):
        self._store: dict[str, CallerPreference] = {}  # phone → preference

    def save(self, phone: str, language: str):
        """Store or update the language preference for a phone number."""
        now = datetime.utcnow()
        if phone in self._store:
            pref = self._store[phone]
            pref.language = language
            pref.call_count += 1
            pref.last_seen = now
        else:
            self._store[phone] = CallerPreference(
                phone=phone,
                language=language,
                call_count=1,
                first_seen=now,
                last_seen=now,
            )

    def get(self, phone: str) -> Optional[str]:
        """Returns the stored language code (e.g. 'en', 'hi') or None if unknown."""
        pref = self._store.get(phone)
        return pref.language if pref else None

    def delete(self, phone: str) -> bool:
        """Remove stored preference — caller will see language menu again next time."""
        if phone not in self._store:
            return False
        del self._store[phone]
        return True

    def list_all(self) -> list[dict]:
        return [
            p.to_dict()
            for p in sorted(
                self._store.values(), key=lambda x: x.last_seen, reverse=True
            )
        ]

    def analytics(self) -> dict:
        total = len(self._store)
        if total == 0:
            return {"total_callers": 0, "by_language": {}}

        by_lang: dict[str, int] = {}
        for pref in self._store.values():
            by_lang[pref.language] = by_lang.get(pref.language, 0) + 1

        return {
            "total_callers": total,
            "by_language": {
                lang: {
                    "count": count,
                    "label": SUPPORTED_LANGUAGES.get(lang, {}).get("label", lang),
                    "percentage": round(count / total * 100, 1),
                }
                for lang, count in sorted(
                    by_lang.items(), key=lambda x: x[1], reverse=True
                )
            },
        }
