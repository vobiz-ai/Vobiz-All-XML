"""
background_store.py — State management and Vobiz Conference API helpers
for 09_background_audio

Responsibilities:
  - Track which conference is active and how many members are in it
  - Call the Vobiz Conference Member Play API to start/stop background audio
  - Expose a clean interface so server.py stays focused on HTTP handling

Production swap notes:
  - Replace _members / _conference_active with Redis keys with TTLs
  - Replace _play_task with a Celery / ARQ background job
"""

import logging
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger("background_store")

VOBIZ_API_BASE = "https://api.vobiz.ai/api/v1"


class ConferencePlayAPI:
    """
    Thin wrapper around the Vobiz Conference Member Play REST API.

    Endpoints used:
      POST   /Account/{auth_id}/Conference/{name}/Member/{member_id}/Play/
             → start playing audio URL to one/all members
      DELETE /Account/{auth_id}/Conference/{name}/Member/{member_id}/Play/
             → stop playback for one/all members
    """

    def __init__(self, auth_id: str, auth_token: str):
        self._auth_id = auth_id
        self._auth_token = auth_token
        self._headers = {
            "X-Auth-ID": auth_id,
            "X-Auth-Token": auth_token,
            "Content-Type": "application/json",
        }

    def _play_url(self, conference_name: str, member_id: str = "all") -> str:
        return (
            f"{VOBIZ_API_BASE}/Account/{self._auth_id}"
            f"/Conference/{conference_name}/Member/{member_id}/Play/"
        )

    def play(
        self,
        conference_name: str,
        audio_url: str,
        member_id: str = "all",
    ) -> dict:
        """
        Start playing audio_url to member_id (default: all members).
        Returns the parsed JSON response or an error dict.
        """
        url = self._play_url(conference_name, member_id)
        try:
            resp = requests.post(
                url,
                json={"url": audio_url},
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                f"ConferencePlay started — conf={conference_name} "
                f"member={member_id} audio={audio_url} resp={data}"
            )
            return data
        except requests.RequestException as exc:
            logger.error(f"ConferencePlay.play failed — {exc}")
            return {"error": str(exc)}

    def stop(self, conference_name: str, member_id: str = "all") -> dict:
        """
        Stop current audio playback for member_id (default: all members).
        """
        url = self._play_url(conference_name, member_id)
        try:
            resp = requests.delete(url, headers=self._headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                f"ConferencePlay stopped — conf={conference_name} member={member_id}"
            )
            return data
        except requests.RequestException as exc:
            logger.error(f"ConferencePlay.stop failed — {exc}")
            return {"error": str(exc)}


class BackgroundAudioStore:
    """
    Tracks the state of the active conference and background audio loop.

    State machine:
      idle  ──join──▶  waiting  ──conference_started──▶  playing
                                                           │  ▲
                                                     stop  │  │ re-trigger
                                                           ▼  │
                                                          stopped
      Any state ──conference_ended──▶ idle
    """

    def __init__(self, play_api: ConferencePlayAPI):
        self._api = play_api

        # Conference state
        self._conference_name: Optional[str] = None
        self._members: dict[str, dict] = {}  # member_id → {call_uuid, joined_at}
        self._conference_active: bool = False
        self._conference_started_at: Optional[datetime] = None

        # Audio state
        self._audio_url: Optional[str] = None
        self._audio_playing: bool = False
        self._play_count: int = 0  # total times Play API was called
        self._last_play_at: Optional[datetime] = None

        # Loop control — asyncio.Event set by server.py to stop the loop task
        self.stop_loop: bool = False

    # ── Conference lifecycle ───────────────────────────────────────────────────

    def set_conference(self, name: str):
        """Set the active conference room name."""
        self._conference_name = name
        self.stop_loop = False

    def member_joined(self, member_id: str, call_uuid: str):
        """Record a new member joining the conference."""
        self._members[member_id] = {
            "call_uuid": call_uuid,
            "joined_at": datetime.utcnow().isoformat(),
        }
        self._conference_active = True
        if self._conference_started_at is None:
            self._conference_started_at = datetime.utcnow()
        logger.info(
            f"Member joined — id={member_id} uuid={call_uuid} "
            f"total_members={len(self._members)}"
        )

    def member_left(self, member_id: str):
        """Record a member leaving the conference."""
        self._members.pop(member_id, None)
        logger.info(f"Member left — id={member_id} remaining={len(self._members)}")
        if not self._members:
            self.conference_ended()

    def conference_ended(self):
        """Mark conference as ended, signal the loop task to stop."""
        logger.info(f"Conference ended — {self._conference_name}")
        self._conference_active = False
        self._audio_playing = False
        self.stop_loop = True

    # ── Audio control ──────────────────────────────────────────────────────────

    def start_audio(self, audio_url: Optional[str] = None) -> dict:
        """
        Trigger background audio playback to all members via the Play API.
        Optionally override the audio_url for this call.
        """
        if not self._conference_name:
            return {"error": "No active conference"}
        if not self._conference_active:
            return {"error": "Conference is not active"}

        url = audio_url or self._audio_url
        if not url:
            return {"error": "No audio URL configured"}

        self._audio_url = url
        result = self._api.play(self._conference_name, url, member_id="all")
        if "error" not in result:
            self._audio_playing = True
            self._play_count += 1
            self._last_play_at = datetime.utcnow()
        return result

    def stop_audio(self) -> dict:
        """Stop background audio for all members."""
        if not self._conference_name:
            return {"error": "No active conference"}

        result = self._api.stop(self._conference_name, member_id="all")
        self._audio_playing = False
        self.stop_loop = True  # also stop the auto-loop task
        return result

    # ── Status ─────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "conference_name": self._conference_name,
            "conference_active": self._conference_active,
            "conference_started_at": (
                self._conference_started_at.isoformat()
                if self._conference_started_at
                else None
            ),
            "member_count": len(self._members),
            "members": self._members,
            "audio_url": self._audio_url,
            "audio_playing": self._audio_playing,
            "play_count": self._play_count,
            "last_play_at": (
                self._last_play_at.isoformat() if self._last_play_at else None
            ),
            "loop_active": not self.stop_loop,
        }

    def reset(self):
        """Full reset — call between tests or after conference ends."""
        self._conference_name = None
        self._members = {}
        self._conference_active = False
        self._conference_started_at = None
        self._audio_url = None
        self._audio_playing = False
        self._play_count = 0
        self._last_play_at = None
        self.stop_loop = True
