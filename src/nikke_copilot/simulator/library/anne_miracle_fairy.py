"""Anne: Miracle Fairy — B2 Wind RL. Healer + revive supporter for
attacker comps.

Encoded from the live ``Character`` skill descriptions in the DB.
A:MF's identity is the once-per-battle revive on a fallen Attacker
ally + team ATK buff for Attackers. Niche but high-impact in fragile
attacker comps where losing a damage carry would otherwise lose the
match.

**Source description (S1)**:

    Every 3 normal hits: all Supporter allies recover 6.07% of
    attack damage as HP over 5 sec

**Source description (S2)**:

    Above 90% HP: all allies HP Potency +23.46%
    Last bullet hits target while >90% HP: all enemies HP Potency
    -78.93% for 10 sec

**Source description (Burst)**:

    1 random fallen Attacker ally (1×/battle): resurrect with 99% HP
    All Attacker allies: recover 38.61% of caster's max HP
    All Attacker allies: ATK +77.22% for 10 sec
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Role,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Anne: Miracle Fairy",
    skill1=(
        SkillEffect(
            description="Every 3 hits: Supporter allies recover 6.07% of attack damage 5s",
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=3),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.SUPPORTER,
                    ),
                    magnitude=6.07,
                    duration_seconds=5.0,
                    notes="6.07% of attack damage as HP over 5s — lifesteal-like",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="When >90% HP: all allies HP Potency +23.46% (passive)",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="caster HP > 90%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=23.46,
                    duration_seconds=999.0,
                    notes="HP Potency buff — captured as BUFF_HP",
                ),
            ),
        ),
        SkillEffect(
            description="Last bullet >90% HP: enemies HP Potency -78.93% 10s",
            trigger=Trigger(
                kind=TriggerKind.ON_LAST_AMMO,
                condition="caster HP > 90%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=78.93,
                    duration_seconds=10.0,
                    notes="HP Potency reduction — captured as DEBUFF_DEFENSE proxy",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: revive 1 fallen Attacker (1×) + Attackers heal + ATK +77.22%",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.ATTACKER,
                    ),
                    magnitude=99.0,
                    notes=(
                        "Revive a fallen Attacker — 99% HP, 1×/battle. "
                        "DSL gap (REVIVE); captured as full-team-heal placeholder."
                    ),
                ),
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.ATTACKER,
                    ),
                    magnitude=38.61,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_role=Role.ATTACKER,
                    ),
                    magnitude=77.22,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Wind RL B2 supporter. Once-per-battle Attacker revive plus "
        "+77.22% ATK on burst — a 'second life' for fragile DPS comps. "
        "Niche pick where losing the carry would otherwise be a wipe."
    ),
)
register_character(_SKILL)
