def test_patch_overrides_base(g3_fs):
    assert g3_fs.source("stringtable.ini").lower() == "strings.p00"
    assert g3_fs.find("STRINGTABLE.INI")[:2] == b"\xff\xfe"


def test_file_only_in_patch(g3_fs):
    assert g3_fs.source("compiledinfos_G3_World_01.bin").lower() == "projects_compiled.p01"


def test_stored_and_zlib_files(g3_fs):
    assert g3_fs.find("Items/Items/Items_Story/Plants_Story_It_Plant_Perm_01.tple")[:8] == b"GENOMFLE"
    assert len(g3_fs.list("G3_World_01/", ".lrentdat")) >= 100
    assert g3_fs.find("G3_World_01/G3_World_01.wrldatasc").startswith(b"[Common]")


def test_missing_file(g3_fs):
    assert g3_fs.find("nie/ma/takiego.pliku") is None


def test_speech_not_mounted(g3_cfg):
    assert not any("speech" in p.lower() for p in g3_cfg.pak_files)
