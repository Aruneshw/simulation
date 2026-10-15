from roboverse.library.registry import Registry, import_passives_csv, validate_component
from roboverse.schemas.library import SupportStatus


def test_library_is_honest_about_support(registry):
    stats = registry.stats()
    assert stats["total"] >= 80
    # not everything is fully modelled — the library must say so
    assert stats["by_status"]["fully_modeled"] < stats["total"] / 2
    assert stats["by_status"].get("schematic_only", 0) > 0
    for c in registry.all():
        for k, r in c.ratings.items():
            assert r.value is None or r.source != "unknown", f"{c.id}.{k} has a value without provenance"


def test_search_and_filters(registry):
    assert any(c.id == "mcu.esp32_devkitc" for c in registry.search("esp32"))
    drivers = registry.search(category="motor_drivers")
    assert drivers and all(c.category.value == "motor_drivers" for c in drivers)
    assert all(c.support_status.value == "fully_modeled" for c in registry.search(status="fully_modeled"))
    assert registry.search("i2c", interface="i2c")


def test_versions():
    reg = Registry()
    base = {"id": "x.part", "name": "X", "category": "sensors"}
    for v in ("1.0.0", "1.2.0", "1.10.0"):
        c, errs = validate_component({**base, "version": v}, reg)
        assert not errs
        reg.add(c)
    assert reg.get("x.part").version == "1.10.0"
    assert reg.versions("x.part") == ["1.0.0", "1.2.0", "1.10.0"]


def test_import_never_marks_verified(registry):
    raw = {"id": "user.sensor", "name": "My sensor", "category": "sensors", "support_status": "fully_modeled",
           "pins": [{"id": "VCC", "name": "VCC", "type": "power_in", "v_min": 3.0, "v_max": 5.5}]}
    c, errs = validate_component(raw, registry)
    assert not errs
    assert c.support_status == SupportStatus.imported_unverified
    assert c.provenance.verified is False


def test_import_rejects_bad_definitions(registry):
    _, errs = validate_component({"id": "bad", "name": "Bad", "category": "sensors",
                                  "pins": [{"id": "P", "name": "P", "type": "power_out"}],
                                  "ratings": {"x": {"value": 1.0}}, "dependencies": ["nope.missing"]}, registry)
    joined = " ".join(errs)
    assert "v_nominal" in joined and "no source" in joined and "missing component" in joined


def test_csv_import(registry):
    csv_text = "id,name,kind,value,manufacturer,part_number\nr.10k,10k 0603,resistor,10000,Yageo,RC0603FR-0710KL\n" \
               "bad,bad,transistor,1,,\n"
    ok, errs = import_passives_csv(csv_text, registry)
    assert [c.id for c in ok] == ["r.10k"] and ok[0].params["resistance"] == 10000
    assert any("unknown kind" in e for e in errs)
