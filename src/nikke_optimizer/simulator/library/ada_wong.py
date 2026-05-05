"""Ada Wong — B3 Electric RL Abnormal (Resident Evil collab).

Encoded from the live ``Character`` skill descriptions in the DB. Ada
is a true-damage RL carry — Flash Grenade Toss every 2 sec during Full
Burst, Special Modification charge-trade burst (-300% Charge Speed for
+1500% Charge Damage on the next shot), and team true-damage support.

**Source description (S1)**:

    Activates when entering Full Burst. Affects all Burst Stage 3
    allies who previously cast their Burst Skill.
    ATK ▲ 60% of caster's ATK for 10 sec.
    True Damage ▲ 50% for 10 sec.
    Recovers 10% of damage as HP for 10 sec.

**Source description (S2)**:

    Activates during Full Burst. Affects enemies within attack range
    nearest to the crosshair every 2 sec.
    Flash Grenade Toss: Deals 420% of final ATK as True Damage.

    Activates when using Burst Skill. Affects self.
    Flash Grenade Toss activation time condition ▼ 1 sec for 10 sec.

**Source description (Burst)**:

    Affects self. ATK ▲ 40% for 10 sec. True Damage ▲ 42% for 10 sec.
    Special Modification:
        Function: Decreases Charge Speed but increases Charge Damage
        for 1 round.
        Effect 1: Charge Speed ▼ 300%.
        Effect 2: Charge Damage ▲ 1500%.
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
    character_name="Ada Wong",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst entry: B3 allies who already bursted "
                "get ATK +60% of caster's ATK, True Damage +50%, "
                "lifesteal 10% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=60.0,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes=(
                        "B3 allies who previously cast burst — "
                        "burst-history filter, DSL gap"
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=50.0,
                    duration_seconds=10.0,
                    notes="B3-allies-who-bursted filter — DSL gap",
                ),
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'recover 10% of damage as HP' — "
                        "lifesteal. DSL gap; HEAL_PER_SECOND proxy."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 2 sec during Full Burst: nearest enemy takes "
                "420% of ATK true damage (Flash Grenade)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER,
                cooldown_seconds=2.0,
                condition="during Full Burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=4.2,
                    notes="actually 'nearest to crosshair' — DSL no spatial target",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst use: self Flash Grenade activation time "
                "-1 sec for 10 sec (every-1-sec instead of every-2-sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Flash Grenade activation time -1 "
                        "sec' — speeds up the timed S2. DSL has no "
                        "TIMER_SPEEDUP kind. 0-mag with note flag."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self ATK +40%, True Damage +42% 10 sec; "
                "Special Modification: next shot Charge Speed -300% "
                "but Charge Damage +1500%."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=42.0,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Charge Speed -300% for 1 round' — "
                        "DSL invariants reject negative magnitude. "
                        "0-mag with note flag (paired with the "
                        "+1500% Charge Damage on the same shot)."
                    ),
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1500.0,
                    duration_seconds=10.0,
                    notes=(
                        "Special Modification single-shot bonus — '1 "
                        "round' duration is encoded as 10 sec. DSL gap."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Ada is the RE collab B3 RL true-damage carry — Flash Grenade "
        "every 2 sec (or every 1 sec post-burst) compounds with team "
        "lifesteal + true damage buffs, and her Special Modification "
        "delivers a 1500% Charge Damage payout on a single slow shot "
        "(similar pattern to Emilia's Freezing Witch)."
    ),
)
register_character(_SKILL)
