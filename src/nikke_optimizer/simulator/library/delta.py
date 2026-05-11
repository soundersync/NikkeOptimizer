"""Delta — B2 Wind SR Elysion. Decoy/taunt defender.

Encoded from the live ``Character`` skill descriptions in the DB.
Delta is a budget Noise-style decoy: her burst spawns a tanky avatar
that taunts all enemies, soaking damage off her team for 10 seconds.

**Source description (S1)**:

    Activates when hitting a target with Full Charge. Affects self.
    Max HP ▲ 8.82% for 10 sec.

**Source description (S2)**:

    Activates when using Burst Skills. Affects self. DEF ▲ 51.42% for 20 sec.

**Source description (Burst)**:

    Affects self. Decoy: Creates an avatar with 91.68% of caster's
    final Max HP for 10 sec. Attract: Taunt all enemies for 10 sec.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Delta",
    skill1=(
        SkillEffect(
            description="On Full Charge hit: self Max HP +8.82% for 10 sec.",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge hit lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=8.82,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="On any burst use: self DEF +51.42% for 20 sec.",
            trigger=Trigger(kind=TriggerKind.ON_ALLY_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=51.42,
                    duration_seconds=20.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: spawn Decoy with 91.68% of caster's Max HP and "
                "taunt all enemies for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=91.68,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes=(
                        "Decoy avatar — DSL has no DECOY/SPAWN_ENTITY kind. "
                        "Approximated as a large shield on caster."
                    ),
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Delta is a budget B2 decoy/taunt defender. Decoy avatar isn't "
        "natively modeled in the DSL — encoded as a self-shield."
    ),
)
register_character(_SKILL)
