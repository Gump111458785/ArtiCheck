from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


@dataclass
class Claim:
    id: str
    text: str
    kind: str
    spec: dict[str, Any]
    source: str = "user_manifest"
    probe: list[str] | None = None

    def __post_init__(self):
        if not self.id or self.kind not in {"metric", "split_disjoint", "baseline_equal"}:
            raise ValueError("Invalid claim id/kind")
        if self.probe is not None and (not self.probe or not all(isinstance(x, str) for x in self.probe)):
            raise ValueError("Claim probe must be a nonempty argv list")
        if self.kind == "metric":
            for name in ("expected", "tolerance"):
                if not isinstance(self.spec.get(name), (int, float)) or not math.isfinite(self.spec[name]):
                    raise ValueError(f"metric requires finite {name}")
            if self.spec["tolerance"] < 0 or not self.spec.get("key"):
                raise ValueError("metric requires key and nonnegative tolerance")
        elif self.kind == "split_disjoint":
            if not self.spec.get("train_key") or not self.spec.get("test_key"):
                raise ValueError("split keys required")
        elif not self.spec.get("method_key") or not self.spec.get("baseline_key"):
            raise ValueError("baseline keys required")


@dataclass
class Task:
    paper_id: str
    repo_id: str
    repo: Path
    claims: list[Claim]
    probe: list[str]
    paper_text: str = ""
    cacheable: bool = False

    @classmethod
    def load(cls, path: Path):
        raw = json.loads(path.read_text())
        ids = [c["id"] for c in raw["claims"]]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate claim IDs")
        probe = raw["probe"]
        if not probe or not all(isinstance(x, str) for x in probe):
            raise ValueError("probe must be a nonempty argv list")
        repo = (path.parent / raw["repo"]).resolve()
        if not repo.is_dir():
            raise ValueError("Artifact repository not found")
        return cls(raw["paper_id"], raw["repo_id"], repo,
                   [Claim(**c) for c in raw["claims"]], probe, raw.get("paper_text", ""), raw.get("cacheable", False))


@dataclass
class Evidence:
    id: str
    tool: str
    success: bool
    payload: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class Finding:
    claim_id: str
    verdict: str  # supported | issue | inconclusive
    score: float  # issue confidence; not a calibrated probability
    reason: str
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
