"""Alice — B3 Fire SR Tetra hyper-DPS / charge-speed self-buffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Alice is a relatively compact carry: Charge Speed self-buffs + a
conditional self-Pierce above 80% HP, plus team Charge Speed support
for the two highest-ATK allies on Full Burst entry.

**Source description (S1)**:

    Activates when entering Full Burst. Affects 2 ally units with
    the highest ATK.
    Charge Speed ▲ 11.67% of caster's Charge Speed for 10 sec.
    Charge Damage ▲ 7% for 10 sec.

**Source description (S2)**:

    Affects self. Activates when above 80% HP. Gains continuous Pierce.

    Affects self. Activates when HP falls below 80%.
    Continuously recover HP by 8.12% of attack damage.

**Source description (Burst)**:

    Affects self. Charging Speed ▲ 80.15% for 10 sec.
    ATK ▲ 55.12% for 10 sec.

**DSL gaps**:

  * "2 ally units with the highest ATK" — TargetKind.ALLY_HIGHEST_ATK
    targets only 1 today. Encoded with count=2 and a note.
  * Above-80% / below-80% HP conditional — encoded as CONDITIONAL.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Alice",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: top-2 ATK allies get Charge Speed "
                "+11.67% and Charge Damage +7% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=11.67,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK, count=2),
                    magnitude=7.0,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "While Alice's HP is above 80%: self gains Pierce continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Alice's HP > 80% (high-HP gating)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=86400.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While Alice's HP is below 80%: self lifesteal 8.12% "
                "of attack damage as HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Alice's HP < 80% (low-HP gating)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.812,
                    duration_seconds=86400.0,
                    notes="actually 'recover 8.12% of attack damage as HP'",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Charge Speed +80.15% and ATK +55.12% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=80.15,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=55.12,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Alice's appeal is the compact Charge-Speed kit + the HP-gated "
        "Pierce/lifesteal — she rewards teams that can keep her at high "
        "HP during the burst window."
    ),
)
register_character(_SKILL)
