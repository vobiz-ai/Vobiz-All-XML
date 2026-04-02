"""
queue_store.py — Agent pool, round-robin routing and queue metrics for 06_call_queue
"""

from datetime import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class Agent:
    number: str
    name: str
    added_at: datetime
    calls_handled: int = 0
    last_call_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "name": self.name,
            "calls_handled": self.calls_handled,
            "last_call_at": self.last_call_at.isoformat()
            if self.last_call_at
            else None,
            "added_at": self.added_at.isoformat(),
        }


@dataclass
class QueueMetric:
    call_uuid: str
    joined_at: datetime
    connected_at: Optional[datetime] = None
    agent_number: Optional[str] = None
    abandoned: bool = False

    @property
    def wait_secs(self) -> Optional[int]:
        if self.connected_at:
            return int((self.connected_at - self.joined_at).total_seconds())
        return None


class QueueStore:
    """
    Manages a pool of available agents with round-robin dispatch,
    plus per-call queue metrics.

    Production swap:
    - Store agents in Redis SET (online/offline via expiring heartbeat keys)
    - Store metrics in Postgres for historical reporting
    """

    def __init__(self, fallback_number: str = ""):
        self._agents: dict[str, Agent] = {}  # number → Agent
        self._rr_index: int = 0  # round-robin pointer
        self._metrics: list[QueueMetric] = []
        self._active: dict[str, QueueMetric] = {}  # call_uuid → active metric
        self._fallback_number = fallback_number

    # ── Agent management ──────────────────────────────────────────────────────

    def add_agent(self, number: str, name: str) -> Agent:
        agent = Agent(number=number, name=name, added_at=datetime.utcnow())
        self._agents[number] = agent
        return agent

    def remove_agent(self, number: str) -> bool:
        if number not in self._agents:
            return False
        del self._agents[number]
        return True

    def list_agents(self) -> list[dict]:
        return [a.to_dict() for a in self._agents.values()]

    def agent_count(self) -> int:
        return len(self._agents)

    def next_agent_number(self) -> Optional[str]:
        """
        Round-robin: returns the next available agent's phone number.
        Falls back to fallback_number if no agents are registered.
        """
        numbers = list(self._agents.keys())
        if not numbers:
            return self._fallback_number or None
        self._rr_index = self._rr_index % len(numbers)
        number = numbers[self._rr_index]
        self._rr_index += 1
        return number

    # ── Queue tracking ────────────────────────────────────────────────────────

    def caller_joined(self, call_uuid: str):
        m = QueueMetric(call_uuid=call_uuid, joined_at=datetime.utcnow())
        self._active[call_uuid] = m
        self._metrics.append(m)

    def caller_connected(self, call_uuid: str, agent_number: str):
        m = self._active.pop(call_uuid, None)
        if m:
            m.connected_at = datetime.utcnow()
            m.agent_number = agent_number
            agent = self._agents.get(agent_number)
            if agent:
                agent.calls_handled += 1
                agent.last_call_at = datetime.utcnow()

    def caller_abandoned(self, call_uuid: str):
        m = self._active.pop(call_uuid, None)
        if m:
            m.abandoned = True

    # ── Status + metrics ──────────────────────────────────────────────────────

    def queue_status(self) -> dict:
        return {
            "callers_waiting": len(self._active),
            "agents_available": self.agent_count(),
            "agents": self.list_agents(),
        }

    def metrics(self) -> dict:
        total = len(self._metrics)
        if total == 0:
            return {
                "total_calls": 0,
                "connected": 0,
                "abandoned": 0,
                "abandonment_rate_pct": 0,
                "avg_wait_secs": 0,
            }

        connected = [m for m in self._metrics if m.connected_at]
        abandoned = [m for m in self._metrics if m.abandoned]
        wait_times = [m.wait_secs for m in connected if m.wait_secs is not None]
        avg_wait = round(sum(wait_times) / len(wait_times), 1) if wait_times else 0

        return {
            "total_calls": total,
            "connected": len(connected),
            "abandoned": len(abandoned),
            "abandonment_rate_pct": round(len(abandoned) / total * 100, 1),
            "avg_wait_secs": avg_wait,
        }
