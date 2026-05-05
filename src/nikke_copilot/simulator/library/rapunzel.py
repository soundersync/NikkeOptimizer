"""Rapunzel — B1 Iron RL Pilgrim. Healer + revive support.

Encoded from the live ``Character`` skill descriptions in the DB. Base
Rapunzel is the original B1 healer with a unique on-burst resurrect
+ low-HP enemy stun. Pre-Pure Grace, but still a viable PvE/PvP pick.

**Source description (S1)**:

    Activates when attacking with Full Charge. Affects 3 allied units
    with the lowest HP percentage. Recovers 4.03% of caster's final
    Max HP as HP.

**Source description (S2)**:

    Affects 2 allied units with the highest ATK.
    Max HP ▲ 8.19% for 15 sec. HP Potency ▲ 13.65% for 15 sec.

**Source description (Burst)**:

    Affects all allies. Recovers 40.83% of caster's final Max HP as HP.

    Affects 1 fallen ally unit with the highest ATK.
    Resurrect with 81.67% HP.

    Activates when HP falls below 30%. Affects all enemies. Stun for 1 sec.
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
    character_name="Rapunzel",
    skill1=(
        SkillEffect(
            description=(
                "On full charge: 3 lowest-HP allies heal 4.03% of "
                "caster Max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=4.03,
                    notes="actually '3 lowest-HP allies' — DSL gap (single target)",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic: 2 highest-ATK allies Max HP +8.19% and "
                "HP Potency +13.65% for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ALWAYS),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=8.19,
                    duration_seconds=15.0,
                    notes="actually '2 highest-ATK allies' — DSL single-target proxy",
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=13.65,
                    duration_seconds=15.0,
                    notes=(
                        "actually 'HP Potency +13.65%' — heal-amplifier. "
                        "DSL gap; HEAL_PER_SECOND proxy."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies heal 40.83% Max HP; 1 fallen "
                "highest-ATK ally resurrects with 81.67% HP; below "
                "30% HP, all enemies stun 1 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.83,
                ),
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=81.67,
                    notes=(
                        "actually 'resurrect fallen ally with 81.67% HP' "
                        "— DSL has no RESURRECT kind. HEAL_HP_FLAT proxy "
                        "with note flag (only meaningful if ally is dead)."
                    ),
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.0,
                    duration_seconds=1.0,
                    notes=(
                        "actually 'Stun for 1 sec' — HP < 30% conditional. "
                        "DSL has no STUN kind. 0-mag with note flag."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Base Rapunzel is the unique B1 healer with a resurrect — "
        "pulls a fallen carry back to 81% HP and stuns enemies on a "
        "low-HP panic. Pre-Pure Grace; still a viable pick for "
        "high-survival comps that benefit from team-wide HP recovery."
    ),
)
register_character(_SKILL)
