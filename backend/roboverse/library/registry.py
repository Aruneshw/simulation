"""Versioned, searchable component registry plus the import/validation pipeline."""
from __future__ import annotations

import csv
import io
from typing import Iterable, Optional

from pydantic import ValidationError

from ..schemas.library import Component, Provenance, SupportStatus
from .builtin import builtin_components

LIBRARY_VERSION = "2026.10.0"


def _vkey(v: str) -> tuple:
    out = []
    for part in v.split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out)


class Registry:
    def __init__(self, components: Iterable[Component] = ()):  # noqa: D401
        self._by_id: dict[str, dict[str, Component]] = {}
        for c in components:
            self.add(c)

    # ----------------------------------------------------------- storage --
    def add(self, c: Component) -> None:
        self._by_id.setdefault(c.id, {})[c.version] = c

    def get(self, cid: str, version: Optional[str] = None) -> Optional[Component]:
        versions = self._by_id.get(cid)
        if not versions:
            return None
        if version:
            return versions.get(version)
        return versions[max(versions, key=_vkey)]

    def versions(self, cid: str) -> list[str]:
        return sorted(self._by_id.get(cid, {}), key=_vkey)

    def all(self) -> list[Component]:
        return [self.get(cid) for cid in self._by_id]  # type: ignore[misc]

    def __len__(self) -> int:
        return len(self._by_id)

    # ------------------------------------------------------------ search --
    def search(self, q: str = "", category: Optional[str] = None, status: Optional[str] = None,
               tag: Optional[str] = None, interface: Optional[str] = None,
               ids: Optional[set[str]] = None) -> list[Component]:
        terms = [t for t in q.lower().split() if t]
        out = []
        for c in self.all():
            if ids is not None and c.id not in ids:
                continue
            if category and c.category.value != category:
                continue
            if status and c.support_status.value != status:
                continue
            if tag and tag.lower() not in [t.lower() for t in c.tags]:
                continue
            if interface and interface.lower() not in [i.lower() for i in c.interfaces]:
                continue
            hay = " ".join([c.id, c.name, c.manufacturer or "", c.part_number or "", c.description, *c.tags]).lower()
            if all(t in hay for t in terms):
                out.append(c)
        # rank: exact name/part-number hits first
        def score(c: Component) -> tuple:
            name = c.name.lower()
            return (0 if q and q.lower() in name else 1, name)
        return sorted(out, key=score)

    def stats(self) -> dict:
        by_status: dict[str, int] = {}
        by_cat: dict[str, int] = {}
        for c in self.all():
            by_status[c.support_status.value] = by_status.get(c.support_status.value, 0) + 1
            by_cat[c.category.value] = by_cat.get(c.category.value, 0) + 1
        return {"library_version": LIBRARY_VERSION, "total": len(self), "by_status": by_status, "by_category": by_cat}

    # ------------------------------------------------------ dependencies --
    def dependency_issues(self, c: Component) -> list[str]:
        return [f"{c.id} depends on missing component '{d}'" for d in c.dependencies if not self.get(d)]


# ------------------------------------------------------- import pipeline --

def validate_component(raw: dict, registry: Registry, source: str = "user_import") -> tuple[Optional[Component], list[str]]:
    """Validate a user/community component definition.

    Imported parts never get a 'verified' support status automatically: they
    land as imported_unverified (or user_defined) until a reviewer promotes them.
    """
    errors: list[str] = []
    try:
        c = Component.model_validate(raw)
    except ValidationError as e:
        return None, [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
    pin_ids = [p.id for p in c.pins]
    if len(pin_ids) != len(set(pin_ids)):
        errors.append("duplicate pin ids")
    for p in c.pins:
        if p.type == "power_in" and p.v_min is not None and p.v_max is not None and p.v_min > p.v_max:
            errors.append(f"pin {p.id}: v_min > v_max")
        if p.type == "power_out" and p.v_nominal is None:
            errors.append(f"pin {p.id}: power_out requires v_nominal")
    for k, r in c.ratings.items():
        if r.value is not None and r.source == "unknown":
            errors.append(f"rating '{k}' has a value but no source — mark it datasheet, assumption or user")
    errors += registry.dependency_issues(c)
    if source == "user_defined":
        c.support_status = SupportStatus.user_defined
    elif c.support_status not in (SupportStatus.user_defined, SupportStatus.cad_only, SupportStatus.schematic_only):
        c.support_status = SupportStatus.imported_unverified
    c.provenance = Provenance(source="user_import" if source != "community" else "community",
                              author=c.provenance.author, license=c.provenance.license,
                              url=c.provenance.url, verified=False,
                              notes=(c.provenance.notes + " | imported, pending review").strip(" |"))
    return (c if not errors else None), errors


def import_passives_csv(text: str, registry: Registry) -> tuple[list[Component], list[str]]:
    """Import a BOM-style CSV of passives: id,name,kind,value,manufacturer,part_number,footprint,datasheet."""
    kinds = {"resistor": ("passive.resistor", "resistance"), "capacitor": ("passive.capacitor", "capacitance"),
             "inductor": ("passive.inductor", "inductance")}
    ok, errs = [], []
    for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        kind = (row.get("kind") or "").strip().lower()
        if kind not in kinds:
            errs.append(f"line {i}: unknown kind '{kind}'")
            continue
        base = registry.get(kinds[kind][0])
        try:
            value = float(row["value"])
        except (KeyError, ValueError):
            errs.append(f"line {i}: invalid value")
            continue
        raw = base.model_dump()
        raw.update({"id": row.get("id") or f"{kind}.{row.get('part_number') or value}", "name": row.get("name") or f"{kind} {value}",
                    "manufacturer": row.get("manufacturer") or None, "part_number": row.get("part_number") or None,
                    "footprint": row.get("footprint") or base.footprint, "datasheet": row.get("datasheet") or None})
        raw["params"] = {**base.params, kinds[kind][1]: value}
        c, e = validate_component(raw, registry)
        if c:
            ok.append(c)
        errs += [f"line {i}: {m}" for m in e]
    return ok, errs


REGISTRY = Registry(builtin_components())
