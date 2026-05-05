"""Pascal — B1 Iron RL Abnormal (Chainsaw Man collab). Healer support.

Encoded from the live ``Character`` skill descriptions in the DB.
Pascal is a simple but reliable B1 healer — periodic single-target
heal on the highest-DEF ally, on-burst-stage heal-amplifier on the 3
lowest-HP allies, and a burst-team heal.

**Source description (S1)**:

    Activates after firing 10 times. Affects 1 ally unit with the
    highest DEF. Recovers 6.28% of caster's Final Max HP as HP.

**Source description (S2)**:

    Activates when entering Burst stage I. Affects 3 ally units with
    the lowest HP. HP Potency ▲ 38.4% for 10 sec.

**Source description (Burst)**:

    Affects 3 ally units with the lowest HP.
    Recovers 55.29% of caster's Final Max HP as HP.
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
    character_name="Pascal",
    skill1=(
        SkillEffect(
            description=(
                "Every 10 normal attacks: highest-DEF ally heals "
                "6.28% of caster Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=10),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_HIGHEST_ATK),
                    magnitude=6.28,
                    notes=(
                        "actually 'highest-DEF ally' — DSL has no "
                        "ALLY_HIGHEST_DEF target. ALLY_HIGHEST_ATK proxy."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Burst Stage 1 entry: 3 lowest-HP allies HP "
                "Potency +38.4% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="any burst stage 1 entered",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=38.4,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'HP Potency +38.4%' on 3 lowest-HP "
                        "allies — heal-amplifier. DSL gap; "
                        "HEAL_PER_SECOND proxy."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 3 lowest-HP allies heal 55.29% of caster Max HP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALLY_LOWEST_HP),
                    magnitude=55.29,
                    notes="actually '3 lowest-HP allies' — DSL single-target proxy",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Pascal is the rare B1 collab healer — periodic heal on the "
        "team's tank (highest-DEF), heal-amplifier on the 3 weakest "
        "allies during burst rotation, and a strong on-burst team "
        "heal. Pairs with damage-soak comps that need topup heals."
    ),
)
register_character(_SKILL)
