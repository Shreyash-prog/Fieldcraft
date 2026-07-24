"""A Task manifest — what the loop needs to run any coding task, not just redact.

Each task dir may carry a `task.json`; absent one, it defaults to the original
redact task so existing behavior is unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Task:
    dir: str
    name: str = "redact_pii"
    module: str = "redact"
    target_file: str = "redact.py"
    test_file: str = "test_redact.py"
    criteria_file: str = "criteria.json"
    stages: list[str] = field(default_factory=lambda: [".stages/stage1_emails.py"])
    solution: str = ".solution/redact_fixed.py"
    trap_keywords: list[str] = field(default_factory=lambda: ["phone", "bare", "dashed"])

    @classmethod
    def load(cls, task_dir: str | Path) -> "Task":
        d = Path(task_dir)
        f = d / "task.json"
        if f.exists():
            data = json.loads(f.read_text())
            data = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            data["dir"] = str(d)
            return cls(**data)
        return cls(dir=str(d))

    def stage_path(self, i: int) -> Path:
        return Path(self.dir) / self.stages[min(i, len(self.stages) - 1)]

    def solution_path(self) -> Path:
        return Path(self.dir) / self.solution
