from gothic_extract.g3.movement import PARAMETERS, movement_speeds


def test_player_speeds_from_movement_parameters(g3_templates):
    # PC_Hero: ForwardSpeedMax 400 cm/s, SlowModifier 0.375, SneakModifier 0.7
    assert movement_speeds(g3_templates) == {"walk": 1.5, "run": 4.0, "sneak": 1.05, "walk_armed": 1.5}
    assert "ForwardSpeedMax" in PARAMETERS
