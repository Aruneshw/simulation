"""Build electrical nets from pin-to-pin wires (union-find)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ...library.registry import Registry
from ...schemas.library import Component, Pin
from ...schemas.project import Circuit, ComponentInstance

PinKey = tuple[str, str]  # (instance id, pin id)


@dataclass
class NetPin:
    instance: ComponentInstance
    component: Component
    pin: Pin

    @property
    def key(self) -> PinKey:
        return (self.instance.id, self.pin.id)

    @property
    def label(self) -> str:
        return f"{self.instance.id}.{self.pin.id}"


@dataclass
class Net:
    id: str
    pins: list[NetPin] = field(default_factory=list)
    name: Optional[str] = None

    def of_type(self, *types: str) -> list[NetPin]:
        return [p for p in self.pins if p.pin.type in types]


@dataclass
class NetGraph:
    nets: list[Net]
    pin_to_net: dict[PinKey, str]
    instances: dict[str, ComponentInstance]
    components: dict[str, Component]  # instance id -> component
    unknown: list[str]  # instance ids whose component is not in the library
    bad_wires: list[str]

    def net_of(self, inst: str, pin: str) -> Optional[Net]:
        nid = self.pin_to_net.get((inst, pin))
        return next((n for n in self.nets if n.id == nid), None) if nid else None


def build_nets(circuit: Circuit, registry: Registry) -> NetGraph:
    parent: dict[PinKey, PinKey] = {}

    def find(k: PinKey) -> PinKey:
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: PinKey, b: PinKey) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    instances = {i.id: i for i in circuit.instances}
    components: dict[str, Component] = {}
    unknown: list[str] = []
    for inst in circuit.instances:
        comp = registry.get(inst.component_id)
        if comp is None:
            unknown.append(inst.id)
            continue
        components[inst.id] = comp
        for p in comp.pins:
            find((inst.id, p.id))

    bad: list[str] = []
    labels: dict[PinKey, str] = {}
    for w in circuit.wires:
        ok = True
        for end in (w.a, w.b):
            comp = components.get(end.instance)
            if comp is None or comp.pin(end.pin) is None:
                bad.append(f"wire {w.id}: {end.instance}.{end.pin} does not exist")
                ok = False
        if ok:
            union((w.a.instance, w.a.pin), (w.b.instance, w.b.pin))
            if w.label:
                labels[(w.a.instance, w.a.pin)] = w.label

    groups: dict[PinKey, list[PinKey]] = {}
    for k in list(parent):
        groups.setdefault(find(k), []).append(k)

    nets: list[Net] = []
    pin_to_net: dict[PinKey, str] = {}
    for idx, (_, keys) in enumerate(sorted(groups.items(), key=lambda kv: sorted(kv[1])[0])):
        nid = f"N{idx + 1}"
        net = Net(id=nid)
        for k in sorted(keys):
            inst = instances[k[0]]
            comp = components[k[0]]
            net.pins.append(NetPin(inst, comp, comp.pin(k[1])))  # type: ignore[arg-type]
            pin_to_net[k] = nid
            if k in labels:
                net.name = labels[k]
        if net.name is None:
            if any(p.pin.type == "ground" for p in net.pins):
                net.name = "GND"
            else:
                src = next((p for p in net.pins if p.pin.type == "power_out"), None)
                if src is not None:
                    net.name = f"{src.instance.id}_{src.pin.id}"
        nets.append(net)
    return NetGraph(nets, pin_to_net, instances, components, unknown, bad)
