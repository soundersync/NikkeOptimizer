"""Rapunzel: Pure Grace — B1 Iron SR Pilgrim shield-self-buffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Her kit is an unusual self-shield mechanic: she generates two stacking
self-shields and converts sustained Full Charge into ongoing team
attack-damage buff via a self-sacrifice loop (HP drains while shield
recovers).

**Source description (S1)**:

    Activates at the start of battle. Affects self.
    Creates a Shield equal to 20.59% of caster's final Max HP continuously.

    Activates when using Burst Skill. Affects self.
    Creates a Shield equal to 20.59% of caster's final Max HP continuously.

    Activates only when Full Charge status is maintained for more than
    1 sec and a Shield is present. Affects all allies.
    Attack Damage ▲ 10.41% continuously.

**Source description (S2)**:

    Activates when attacking with Full Charge. Affects self.
    Recovers 2% of caster's final Max HP.

    Activates only when Full Charge status is maintained for more than
    1 sec and a Shield is present. Affects self.
    Current HP ▼ 2% every 1 sec continuously.
    Recovers Shield HP equal to 3.16% of caster's final Max HP every Sec continuously.

**Source description (Burst)**:

    Affects self. Max HP ▲ 10.13% for 10 sec.
    Affects all allies. Attack Damage ▲ 15.24% for 10 sec.

**DSL gaps**:

  * Self-sacrifice loop (HP -2%/s + Shield +3.16%/s) — DSL has no
    self-damage effect kind. Captured as a note on the heal effect.
  * "Maintains Full Charge for more than 1 sec" — duration-condition
    on a sustained state. CONDITIONAL trigger.
  * Two stacking self-shields (battle-start + burst) — both encoded;
    simulator treats them additively.
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
    character_name="Rapunzel: Pure Grace",
    skill1=(
        SkillEffect(
            description=(
                "On battle start: self gains shield equal to 20.59% of "
                "max HP continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.59,
                    duration_seconds=86400.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst: self gains another 20.59%-max-HP shield "
                "continuously (stacks with battle-start shield)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.59,
                    duration_seconds=86400.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While Full Charge is held >1 sec AND a shield is "
                "present: all allies Attack Damage +10.41% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge held > 1s and Rapunzel has a shield",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.41,
                    duration_seconds=86400.0,
                    notes="active while charge held >1s + shield present",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Charge attack: self heals 2% of max HP."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge release",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While Full Charge held >1s AND shield present: self "
                "loses 2% HP/sec but gains 3.16% Shield HP/sec — "
                "self-sacrifice loop that converts HP into shield + "
                "team attack-damage uptime."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge held > 1s and shield present",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.16,
                    duration_seconds=86400.0,
                    notes=(
                        "shield recovery, NOT HP heal. Plus 'HP -2%/sec' "
                        "self-drain (DSL gap: SELF_DAMAGE). Net effect "
                        "trades HP for shield uptime."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Max HP +10.13% for 10 sec, all allies "
                "Attack Damage +15.24% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=10.13,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=15.24,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Rapunzel: Pure Grace pairs naturally with Naga (whose S1 + "
        "burst proc on shield application) — Rapunzel's persistent "
        "self-shields keep Naga's shield-conditional buffs active. "
        "Niche but high-impact when the comp clicks."
    ),
)
register_character(_SKILL)
