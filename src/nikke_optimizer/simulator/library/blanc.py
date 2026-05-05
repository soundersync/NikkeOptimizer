"""Blanc — B2 Wind AR healer/sustainer, Tetra. Defensive carry-enabler.

Encoded from the live ``Character`` skill descriptions in the DB.

Blanc is the canonical sustainer in PvP defense — periodic team shield,
post-Full-Burst regen tick, and a burst that grants indomitability to
the lowest-HP ally + a damage-taken debuff to enemies. Her squad-CD
reduction (S2) is what gives her near-constant uptime when paired with
fellow Tetra unit.

**Source description (S1)**:

    Activates after landing 120 normal attack(s).
    Creates a Shield, equivalent to 11.8% of the caster's final Max HP,
    which protects all allies from damage. Lasts for 5 sec.

**Source description (S2)**:

    Activates after Full Burst ends. Affects all allies.
    Constantly recovers 3.68% of caster's final Max HP every 1 sec for 5 sec.

    Activates when Full Burst ends with an ally from the same squad on
    the battlefield. Affects self.
    Cooldown of Burst Skill ▼ 40.76 sec.

**Source description (Burst)**:

    Affects all allies. Constantly recovers 3.84% of caster's final
    Max HP every 1 sec for 8 sec.

    Affects 1 ally unit(s) with the lowest HP (except caster).
    Gain indomitability for 10 sec. Max HP ▲ 31.68% for 10 sec.

    Affects all enemies. Damage Taken ▲ 39.26% for 10 sec.

**DSL gaps**:

  * "Indomitability" (a "can't drop below 1 HP" status) — no DSL effect
    kind. Encoded as a note on a placeholder BUFF_DEFENSE.
  * Burst CD reduction conditional on a same-squad ally being present —
    encoded with a CONDITIONAL trigger; simulator must check squad
    membership at fire time. Squad info is on Character.role_tags but
    not formally typed in the DSL.
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
    character_name="Blanc",
    skill1=(
        SkillEffect(
            description=(
                "Every 120 normal attacks: grants all allies a 5-sec "
                "shield equal to 11.8% of Blanc's max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=120),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=11.8,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "After Full Burst ends: all allies recover 3.68% of "
                "Blanc's max HP per second for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.68,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "When Full Burst ends with a same-squad ally on the "
                "battlefield: self burst CD -40.76 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_END,
                condition="at least one ally shares Blanc's Squad",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.76,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 8 sec team regen + indomitability + Max HP buff "
                "to lowest-HP ally + damage-taken debuff to all enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=3.84,
                    duration_seconds=8.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP, count=1),
                    magnitude=31.68,
                    duration_seconds=10.0,
                    notes=(
                        "lowest HP ally except caster; also grants "
                        "'indomitability' (can't drop below 1 HP) — "
                        "DSL has no IMMORTALITY effect kind"
                    ),
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=39.26,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Damage Taken +39.26%' on enemies — "
                        "encoded as DEBUFF_DEFENSE proxy; same downstream "
                        "math but distinct stat in NIKKE"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Blanc's defensive value comes from layered sustain: periodic "
        "shield (S1), post-Full-Burst regen + CD reduction (S2), and "
        "a burst that combines team regen + indomitability + damage-"
        "taken debuff. The squad-conditional CD reduction makes her "
        "uptime exceptional when paired with another Tetra unit "
        "(typically Modernia or Bay)."
    ),
)
register_character(_SKILL)
