"""Noah — B2 Wind RL defender/protector, Pilgrim. Defense quartet finisher.

Encoded from the live ``Character`` skill descriptions in the DB.
Noah's compact kit centers on her burst's 3-second invincibility window
+ massive DEF buff to all allies, plus a single-target taunt + ATK
debuff from S2. She fits naturally alongside Helm/Centi/Blanc as the
fourth wall in defensive PvP comps.

**Source description (S1)**:

    Affects all allies. 10% chance to cast when attacked.
    Sustained damage ▼ 8% for 10 sec.

**Source description (S2)**:

    Activates when attacking with Full Charge. Affects the target(s).
    Taunt for 2 sec. ATK ▼ 13.25% for 5 sec.

**Source description (Burst)**:

    Affects self. Attract: Taunt all enemies for 10 sec.

    Affects all allies. Invincible for 3 sec. DEF ▲ 133.48% for 10 sec.

**DSL gaps**:

  * "10% chance to cast when attacked" — probabilistic trigger; the
    DSL has no probability field. Encoded as ON_DAMAGE_TAKEN with a
    note about the 10% chance.
  * "Sustained damage ▼ 8%" — damage-taken reduction; the DSL has
    BUFF_DEFENSE which is mathematically similar but a distinct stat.
    Encoded as a BUFF_DEFENSE proxy with a note.
  * "Invincible for 3 sec" — full immunity to damage; same gap as
    Blanc's "indomitability" / Red Hood's "Solidify". Encoded as a
    high-magnitude BUFF_DEFENSE with a note since the DSL has no
    INVINCIBILITY effect kind.
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
    character_name="Noah",
    skill1=(
        SkillEffect(
            description=(
                "When taking damage (10% chance): all allies 'sustained "
                "damage taken' -8% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_DAMAGE_TAKEN,
                condition="10% chance to fire (probabilistic)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=8.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'sustained damage taken -8%'; encoded "
                        "as DEF buff proxy. Distinct stat in NIKKE "
                        "(damage-taken reduction multiplies incoming "
                        "damage; DEF is subtractive). Probabilistic — "
                        "10% chance per hit taken; simulator must roll."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Charge hit: target taunted 2 sec + ATK -13.25% "
                "for 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge hit lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.0,
                    duration_seconds=2.0,
                    notes=(
                        "actually a single-target taunt — not the "
                        "self-taunt that TAUNT usually represents. "
                        "Simulator must distinguish."
                    ),
                ),
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=13.25,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self taunts all enemies for 10 sec; all allies "
                "become Invincible for 3 sec and gain DEF +133.48% for "
                "10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=10.0,
                ),
                # Invincibility — no DSL kind. Encoded as a 0-magnitude
                # BUFF_DEFENSE with the duration set + a note flag. The
                # simulator must treat 'invincib' notes as full damage
                # immunity, not just stat buff. We use 0 instead of a
                # sentinel so the average DEF buff displayed in the
                # evaluator isn't polluted.
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    duration_seconds=3.0,
                    notes=(
                        "actually 'Invincible for 3 sec' — full damage "
                        "immunity, not DEF. DSL gap (INVINCIBILITY). "
                        "Simulator must check note flag rather than "
                        "magnitude."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=133.48,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Noah's burst window is the canonical 'panic button': 3 seconds "
        "of full team invincibility followed by 10 seconds of +133% DEF "
        "is enough to walk through almost any opposing burst. Slots in "
        "as the B2 in the Helm/Centi/Blanc/Noah defense quartet, with "
        "her S2 single-target taunt+debuff on Full Charges providing "
        "passive utility between bursts."
    ),
)
register_character(_SKILL)
