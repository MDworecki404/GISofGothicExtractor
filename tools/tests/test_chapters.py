import pytest

from gothic_extract.chapters import function_chapters
from gothic_extract.config import load_game
from gothic_extract.script_vm import make_vm


@pytest.fixture(scope="module")
def g1_vm():
    cfg = load_game("g1")
    if not cfg.script_dat.exists():
        pytest.skip("Gothic folder not present")
    return make_vm(cfg.script_dat)


def test_g1_dispatcher_configured():
    cfg = load_game("g1")
    assert cfg.chapter_dispatcher == "B_KAPITELWECHSEL"
    assert cfg.worlds["WORLD"].slug == "kolonia"
    assert set(cfg.worlds) == set(cfg.world_roots)


def test_function_called_only_from_a_chapter_block_gets_that_chapter(g1_vm):
    chapters = function_chapters(g1_vm, "B_KAPITELWECHSEL")
    assert chapters["B_STORY_RESPAWNOW"] == 2  # monsters respawn at the start of chapter 2


def test_function_also_called_from_dialogs_has_no_chapter(g1_vm):
    chapters = function_chapters(g1_vm, "B_KAPITELWECHSEL")
    assert "B_STORY_GOTOORCGRAVEYARD" not in chapters


def test_unknown_dispatcher_gives_nothing(g1_vm):
    assert function_chapters(g1_vm, "NO_SUCH_FUNCTION") == {}
