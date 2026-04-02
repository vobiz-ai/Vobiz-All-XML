"""
survey_store.py — Survey result storage + CSV export + aggregated summary for 05_survey
"""

import csv
import io
import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class SurveyResult:
    id: str
    call_uuid: str
    phone: str
    q1_rating: Optional[str]  # "1"–"5"
    q2_recommend: Optional[str]  # "yes" | "no"
    q3_experience: Optional[str]  # "excellent" | "good" | "needs improvement"
    completed: bool
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "call_uuid": self.call_uuid,
            "phone": self.phone,
            "q1_service_rating": self.q1_rating,
            "q2_recommend": self.q2_recommend,
            "q3_experience": self.q3_experience,
            "completed": self.completed,
            "timestamp": self.timestamp.isoformat(),
        }


class SurveyStore:
    """
    In-memory survey store.
    Answers are collected incrementally per call UUID (pending dict),
    then finalized into SurveyResult on /survey-done.

    Production swap: write each answer as it arrives to a DB row,
    finalize with a completed=True flag.
    """

    def __init__(self):
        self._store: dict[str, SurveyResult] = {}  # result id → result
        self._call_index: dict[str, str] = {}  # call_uuid → result id
        self._pending: dict[str, dict] = {}  # call_uuid → partial answers

    def start(self, call_uuid: str, phone: str):
        """Called when the survey call begins."""
        self._pending[call_uuid] = {"phone": phone}

    def update_answer(self, call_uuid: str, question: str, answer: str):
        """Update one answer as the call progresses (q1_rating, q2_recommend, q3_experience)."""
        if call_uuid in self._pending:
            self._pending[call_uuid][question] = answer

    def complete(self, call_uuid: str) -> Optional[SurveyResult]:
        """Finalize the survey and move from pending → permanent store."""
        data = self._pending.pop(call_uuid, None)
        if not data:
            return None
        result = SurveyResult(
            id=str(uuid.uuid4()),
            call_uuid=call_uuid,
            phone=data.get("phone", "unknown"),
            q1_rating=data.get("q1_rating"),
            q2_recommend=data.get("q2_recommend"),
            q3_experience=data.get("q3_experience"),
            completed=True,
            timestamp=datetime.utcnow(),
        )
        self._store[result.id] = result
        self._call_index[call_uuid] = result.id
        return result

    def get(self, result_id: str) -> Optional[SurveyResult]:
        return self._store.get(result_id)

    def list_all(self) -> list[dict]:
        return [
            r.to_dict()
            for r in sorted(
                self._store.values(), key=lambda x: x.timestamp, reverse=True
            )
        ]

    def export_csv(self) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "call_uuid",
                "phone",
                "q1_service_rating",
                "q2_recommend",
                "q3_experience",
                "completed",
                "timestamp",
            ]
        )
        for r in sorted(self._store.values(), key=lambda x: x.timestamp):
            writer.writerow(
                [
                    r.id,
                    r.call_uuid,
                    r.phone,
                    r.q1_rating,
                    r.q2_recommend,
                    r.q3_experience,
                    r.completed,
                    r.timestamp.isoformat(),
                ]
            )
        return output.getvalue()

    def summary(self) -> dict:
        results = list(self._store.values())
        total = len(results)
        if total == 0:
            return {"total_responses": 0}

        q1_vals = [
            int(r.q1_rating) for r in results if r.q1_rating and r.q1_rating.isdigit()
        ]
        avg_rating = round(sum(q1_vals) / len(q1_vals), 2) if q1_vals else None

        q2_yes = sum(1 for r in results if r.q2_recommend == "yes")
        recommend_pct = round(q2_yes / total * 100, 1)

        q3_dist: dict[str, int] = {}
        for r in results:
            if r.q3_experience:
                q3_dist[r.q3_experience] = q3_dist.get(r.q3_experience, 0) + 1

        return {
            "total_responses": total,
            "avg_service_rating": avg_rating,
            "recommend_rate_pct": recommend_pct,
            "experience_distribution": q3_dist,
        }
