"""Character uniqueness and NPC assignment to worlds on concrete Gothic 1 cases."""
import dataclasses
import json

import pytest

from gothic_extract.config import load_game
from gothic_extract.daedalus_scan import other_world_functions
from gothic_extract.geoportal import unique_characters
from gothic_extract.npcs import extract_npcs
from gothic_extract.script_vm import make_vm
from gothic_extract.vfs import open_vfs
from gothic_extract.world_data import PointResolver, load_world
from gothic_extract.chapters import function_chapters


@pytest.fixture(scope="module")
def g1():
    cfg = load_game("g1")
    if not cfg.script_dat.exists():
        pytest.skip("Gothic folder not present")
    return cfg, make_vm(cfg.script_dat), open_vfs(cfg)


@pytest.fixture(scope="module")
def worlds(g1):
    cfg, vm, vfs = g1
    chapters = function_chapters(vm, cfg.chapter_dispatcher)
    out = {}
    for zen in cfg.worlds:
        _, wd = load_world(vfs, zen + ".ZEN", cfg.version)
        recs = extract_npcs(vm, PointResolver(wd.waypoints, wd.freepoints), other_world_functions(vm, cfg.world_roots, zen),
                            cfg.first_chapters.get(zen), chapters)
        feats = [{"properties": {**dataclasses.asdict(n), "is_human": n.is_human}} for n in recs]
        out[zen] = (recs, unique_characters(feats))
    return out


def test_same_instance_in_two_worlds_is_indexed_in_both(worlds):
    # Gor Na Bar and Gor Na Kosh are inserted both in the Colony and in the Old Mine
    for zen in ("WORLD", "OLDMINE"):
        unique = worlds[zen][1]
        assert unique["Gor Na Bar"] == ["TPL_1400_GORNABAR"]
        assert unique["Gor Na Kosh"] == ["TPL_1401_GORNAKOSH"]


def test_world_inserts_follow_waypoints(worlds):
    codes = {zen: {n.code for n in recs} for zen, (recs, _) in worlds.items()}
    assert "GUR_1211_BAALLUKOR" in codes["ORCGRAVEYARD"] and "GUR_1211_BAALLUKOR" not in codes["WORLD"]
    assert "ORC_PRIEST_1" in codes["ORCTEMPEL"] and "ORC_PRIEST_1" not in codes["WORLD"]
    assert "KDF_406_OTXARDAS" in codes["ORCTEMPEL"]


def test_generic_humans_are_not_unique(worlds):
    unique = worlds["WORLD"][1]
    for name in ("Strażnik", "Kopacz", "Nowicjusz", "Cień"):
        assert name not in unique


def test_monster_unique_in_game_is_unique(worlds):
    assert worlds["WORLD"][1]["Młody troll"] == ["YOUNGTROLL"]
    assert "Ścierwojad" not in worlds["WORLD"][1]  # a species, many instances


def test_chapter_of_respawn_monsters(worlds):
    recs = worlds["WORLD"][0]
    assert {n.chapter for n in recs if n.insert_function == "B_STORY_RESPAWNOW"} == {2}
    assert all(n.chapter is None for n in worlds["OLDMINE"][0])  # first_chapter unknown -> null
