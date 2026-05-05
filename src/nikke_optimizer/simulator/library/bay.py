"""Bay — B2 Fire RL Tetra defender. Damage-share + team damage-reduction.

Encoded from the live ``Character`` skill descriptions in the DB. Bay's
identity is the damage-share mechanic — while she survives her own
burst window, all allies share damage taken proportionally with her,
turning her HP pool into a team-wide damage sponge. Her squad pairing
with Blanc (S2 burst-CD reduction) is canonical.

**Source description (S1)**:

    Activates if self survives when using Burst Skill. Affects all
    allies. Proportionally shares damage taken continuously.
    DEF ▲ 10.13% of caster's DEF continuously.

**Source description (S2)**:

    Activates if self survives when using Burst Skill. Affects all
    allies. Proportionally shares damage taken continuously.

    Activates when Full Burst ends. Affects self.
    Constantly recovers Cover's HP by 2.88% of caster's final Max HP
    every 1 sec for 5 sec.

**Source description (Burst)**:

    Affects self. Cover's Max HP ▲ 18% of the caster's Max HP,
    lasts for 20 sec.

    Affects all allies. Damage Taken ▼ 8.87% for 10 sec.

**DSL gaps**:

  * "Proportionally shares damage taken" — distinct mechanic from
    a defensive buff; absorbs incoming damage to allies and routes
    it through Bay. Encoded as a note on the DEF buff with a flag.
  * "Damage Taken ▼ 8.87%" — same gap as Noah / Blanc (sustained
    damage reduction vs DEF). Encoded as BUFF_DEFENSE proxy.
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
    character_name="Bay",
    skill1=(
        SkillEffect(
            description=(
                "Post-burst (if Bay survives): all allies share damage "
                "taken continuously, plus DEF +10.13% of caster's DEF."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="Bay survives the burst cast",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.13,
                    duration_seconds=86400.0,
                    scaling_source=ScalingSource.CASTER_DEF,
                    notes=(
                        "ALSO 'proportionally shares damage taken' — "
                        "Bay absorbs a fraction of all incoming ally "
                        "damage. DSL gap (DAMAGE_SHARE)."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On Full Burst end: self recovers Cover HP at 2.88% of "
                "max HP per second for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_END),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.88,
                    duration_seconds=5.0,
                    notes="Cover HP recovery — drives Tia/Naga combos",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Cover Max HP +18% (20s); all allies "
                "Damage Taken -8.87% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=18.0,
                    duration_seconds=20.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="Cover Max HP (cover pool, not member HP)",
                ),
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=8.87,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Damage Taken -8.87%' — multiplicative "
                        "reduction. Encoded as DEF buff proxy."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Bay's damage-share mechanic is unique in PvP: she effectively "
        "lets the team's combined DEF apply to all incoming damage by "
        "routing through her cover pool. Squad-pairs naturally with "
        "Blanc (whose S2 grants self burst CD -40s when a same-squad "
        "ally is on the team)."
    ),
)
register_character(_SKILL)
