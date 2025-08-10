from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import time
import uuid


@dataclass
class Objective:
    text: str
    estimate_mins: Optional[int] = None


@dataclass
class Quest:
    id: str
    created_ts: float
    title: str
    description: str = ""
    objectives: List[Objective] = field(default_factory=list)
    next_action: Optional[str] = None
    total_estimate_mins: Optional[int] = None

    @staticmethod
    def new(title: str, description: str = "", objectives: Optional[List[Objective]] = None,
            next_action: Optional[str] = None, total_estimate_mins: Optional[int] = None) -> "Quest":
        return Quest(
            id=str(uuid.uuid4()),
            created_ts=time.time(),
            title=title,
            description=description,
            objectives=objectives or [],
            next_action=next_action,
            total_estimate_mins=total_estimate_mins,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_ts": self.created_ts,
            "title": self.title,
            "description": self.description,
            "objectives": [
                {"text": o.text, "estimate_mins": o.estimate_mins}
                for o in self.objectives
            ],
            "next_action": self.next_action,
            "total_estimate_mins": self.total_estimate_mins,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Quest":
        return Quest(
            id=str(data.get("id", "")),
            created_ts=float(data.get("created_ts", time.time())),
            title=str(data.get("title", "Untitled Quest")),
            description=str(data.get("description", "")),
            objectives=[
                Objective(text=str(o.get("text", "")), estimate_mins=o.get("estimate_mins"))
                for o in (data.get("objectives") or [])
                if isinstance(o, dict)
            ],
            next_action=data.get("next_action"),
            total_estimate_mins=data.get("total_estimate_mins"),
        )
