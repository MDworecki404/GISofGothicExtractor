def test_royal_sorrel_polish_name(catalog):
    assert catalog["ITPL_PERM_HERB"].name == "Szczaw królewski"


def test_catalog_size(catalog):
    assert len(catalog) > 500


def test_gold_category(catalog):
    assert catalog["ITMI_GOLD"].category


def test_herb_is_plant(catalog):
    assert catalog["ITPL_HEALTH_HERB_01"].category == "Rośliny"
