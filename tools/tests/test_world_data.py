import zenkit

from gothic_extract.world_data import PointResolver, parse_contents


def test_parse_contents_variants():
    assert parse_contents("ItMi_Gold:50, ItFo_Apple") == [("ITMI_GOLD", 50), ("ITFO_APPLE", 1)]
    assert parse_contents(" itpl_health_herb_01:2 ,") == [("ITPL_HEALTH_HERB_01", 2)]
    assert parse_contents("") == []


def test_parse_contents_semicolons():
    # real NEWWORLD containers mix ',' and ';'
    assert parse_contents("ItRw_Arrow:17,ItMi_Gold:20;ItPo_Health_03") == [
        ("ITRW_ARROW", 17), ("ITMI_GOLD", 20), ("ITPO_HEALTH_03", 1)]


def test_world_has_expected_counts(newworld):
    _, wd = newworld
    assert len(wd.vobs) > 5000
    assert len(wd.waypoints) > 1000
    assert len(wd.containers) > 50


def test_items_found_recursively(newworld):
    world, wd = newworld
    root_only = sum(1 for v in world.root_objects if v.type == zenkit.VobType.oCItem)
    assert len([i for i in wd.items if i.source == "zen"]) >= root_only
    assert any(i.code == "ITPL_PERM_HERB" for i in wd.items)


def test_resolver_case_insensitive_and_freepoints(newworld):
    _, wd = newworld
    r = PointResolver(wd.waypoints, wd.freepoints)
    wp = wd.waypoints[0].name
    assert r.resolve(wp.lower()) == r.resolve(wp.upper())
    assert r.resolve(wp) is not None
    fp = wd.freepoints[0].name
    assert r.resolve(fp) is not None
    assert r.resolve("NIE_ISTNIEJE_123") is None
