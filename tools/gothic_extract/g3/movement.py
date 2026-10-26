"""Player movement speeds of Gothic 3 (m/s), from the hero's gCCharacterMovement_PS.

G1/G2 measure speeds from animation loops; G3 has the speeds as parameters of the hero template (PC_Hero):
ForwardSpeedMax (running, cm/s), SlowModifier (walking = running × it) and SneakModifier (applied to walking).
G3 has no separate armed walk, so walk_armed = walk.
"""
from .templates import TemplateRec

HERO = "PC_Hero"
PARAMETERS = ["ForwardSpeedMax", "SlowModifier", "SneakModifier"]


def movement_speeds(templates: dict[str, TemplateRec]) -> dict[str, float]:
    hero = next(t for t in templates.values() if t.name == HERO)
    p = {k: v.value for k, v in hero.entity.props["gCCharacterMovement_PS"].props.items()}
    run = p["ForwardSpeedMax"] / 100
    walk = run * p["SlowModifier"]
    return {"walk": round(walk, 3), "run": round(run, 3), "sneak": round(walk * p["SneakModifier"], 3),
            "walk_armed": round(walk, 3)}
