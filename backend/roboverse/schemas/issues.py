"""Common issue format used by every validator (robot, electrical, twin, export)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["critical", "error", "warning", "info"]
SEVERITY_ORDER = {"critical": 0, "error": 1, "warning": 2, "info": 3}


class SpecRef(BaseModel):
    component: str
    field: str
    value: Optional[float | str] = None
    unit: str = ""
    source: str = "unknown"  # datasheet | assumption | user | unknown | computed
    url: Optional[str] = None


class Issue(BaseModel):
    code: str
    severity: Severity
    domain: Literal["mechanical", "robot", "electrical", "power", "twin", "firmware", "simulation", "export", "world", "cad"]
    title: str
    message: str  # why it is a problem
    connection: Optional[str] = None  # exact connection / location, e.g. "U1.GPIO21 -> U3.SDA (net N4)"
    refs: list[str] = Field(default_factory=list)  # entity ids for UI highlighting
    specs: list[SpecRef] = Field(default_factory=list)
    fix: str = ""


def sort_issues(issues: list[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: (SEVERITY_ORDER[i.severity], i.domain, i.code))


def summarize(issues: list[Issue]) -> dict:
    out = {k: 0 for k in SEVERITY_ORDER}
    for i in issues:
        out[i.severity] += 1
    out["passed"] = out["critical"] == 0 and out["error"] == 0
    return out
