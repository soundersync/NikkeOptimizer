"""Tia — B1 Iron RL defender/buffer, Missilis. The Tia/Naga burst-gen core.

Encoded from the live ``Character`` skill descriptions in the DB.
Tia's value comes from her cover-heal that triggers her S1 (burst CD
reduction + team Attack-damage buff) — paired with Naga, who heals
covers, this becomes a constant-uptime burst-gen loop.

**Source description (S1)**:

    Activates when recovering Cover's HP. Affects self.
    Cooldown of Burst Skill ▼ 13 sec, stacks up to 2 time(s) and lasts for 12 sec.

    Activates when recovering Cover's HP. Affects all allies.
    Attack damage ▲ 32.11% for 10 sec.

**Source description (S2)**:

    Activates after landing 5 normal attack(s). Affects self.
    Cover's Max HP ▲ 32.75% of the caster's Max HP, lasts for 5 sec.
    Attract: Taunt all enemies for 5 sec.

    Activates when using Burst Skill. Affects self.
    Recovery of Cover's HP ▲ 21.41% of the caster's final Max HP.
    Recovers 21.96% of attack damage for 10 sec.

**Source description (Burst)**:

    Affects self. Generates a Shield with 35.07% of the caster's final
    Max HP for 10 sec.

    Affects all allies (except self). Generates a Shield with 10.21%
    of the caster's final Max HP for 10 sec.

    Affects all allies. Re-enter Burst Skill Stage 1.

**DSL gaps**:

  * "Cover's HP" mechanic is distinct from member HP — encoded as a
    note on the burst-cooldown reduction; simulator must model cover.
  * "Re-enter Burst Skill Stage 1" is a major effect (lets the team
    burst again) — encoded with a placeholder GAIN_BURST_GAUGE +
    detailed note since the DSL has no RE_ENTER_BURST kind.
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
    character_name="Tia",
    skill1=(
        SkillEffect(
            description=(
                "On Cover-HP recovery: self burst CD -13 sec (×2 stacks, "
                "12 sec). Triggered most often by Naga's cover heal."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="any ally restores Cover HP (Naga + Tia chain)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=13.0,
                    duration_seconds=12.0,
                    stacks_max=2,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Cover-HP recovery: all allies Attack damage +32.11% "
                "for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="any ally restores Cover HP",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=32.11,
                    duration_seconds=10.0,
                    notes="actually 'Attack damage', not 'ATK' — ATK_DAMAGE gap",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 5 normal attacks: self Cover Max HP +32.75%, "
                "Taunt all enemies for 5 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=5),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=32.75,
                    duration_seconds=5.0,
                    notes="actually 'Cover Max HP', not unit HP",
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=5.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On burst: self Cover-HP recovery +21.41%, plus 21.96% "
                "of attack damage recovered for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.196,  # 21.96% / 10s proxy
                    duration_seconds=10.0,
                    notes=(
                        "lifesteal-style: 21.96% of attack damage as HP. "
                        "Cover-HP recovery component encoded separately."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Self shield 35.07% max HP, 10s. All allies (except self) "
                "shield 10.21% max HP, 10s. All allies re-enter Burst Stage 1."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=35.07,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.21,
                    duration_seconds=10.0,
                    notes="actually all-allies-EXCEPT-self; DSL gap",
                ),
                # The burst-stage reset — major mechanic, no DSL kind for it.
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    notes=(
                        "actually 'Re-enter Burst Skill Stage 1' — full "
                        "burst rotation reset. DSL has no RE_ENTER_BURST."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Tia's signature is the Naga-pair burst-gen loop: Naga heals "
        "covers → triggers Tia S1 → burst CD reduction + team ATK buff. "
        "Combined with her burst's 're-enter Stage 1' effect, the team "
        "can burst much more frequently than baseline."
    ),
)
register_character(_SKILL)
