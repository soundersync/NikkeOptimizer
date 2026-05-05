"""Maiden: Ice Rose — B3 Electric RL Elysion. MP-scaling burst nuker.

Encoded from the live ``Character`` skill descriptions in the DB. MIR's
identity is the MP gauge — accumulated on Burst Stage 1 and Full Burst
entries, spent on her own Burst Skill to scale her single-target nuke.

**Source description (S1)**:

    Activates when entering Burst Stage 1. Affects self when MP is 0.
    MP recovers by 1. MP can be accumulated up to a maximum of 12.
    All accumulated MP is consumed when using Burst Skill.

    Activates when entering Full Burst. Affects self when MP is above 1.
    MP replenishes by 1. MP can be accumulated up to a maximum of 12.
    All accumulated MP is consumed when using Burst Skill.

    Activates when attacking with Full Charge for 6 time(s). Affects
    self. Max HP ▲ 6.34% without restoring HP for 15 sec, stacks up to
    10 time(s).

**Source description (S2)**:

    Activates when MP is replenished. Affects all Electric Code allies
    except for self. Damage as strong element ▲ 40.9% for 10 sec.
    ATK ▲ 20.9% of caster's ATK for 10 sec.

    Activates when MP is used. Affects self.
    Damage as strong element ▲ 31.68% for 10 sec.
    ATK ▲ 3.2% of caster's final Max HP for 10 sec.

    Activates when attacking with Full Charge for 1 time(s).
    Affects 1 enemy unit nearest to the crosshair.
    Deals 547.62% of final ATK as damage.

**Source description (Burst)**:

    Affects 1 enemy unit nearest to the crosshair. Deals damage equal
    to 1372.8% of ATK that is calculated based on 10% of the caster's
    final Max HP. Attacks continuously based on the current MP.
"""

from __future__ import annotations

from ..dsl import (
    CharacterSkillSet,
    Effect,
    EffectKind,
    Element,
    ScalingSource,
    SkillEffect,
    Target,
    TargetKind,
    Trigger,
    TriggerKind,
)
from ..registry import register_character


_SKILL = CharacterSkillSet(
    character_name="Maiden: Ice Rose",
    skill1=(
        SkillEffect(
            description=(
                "On Burst Stage 1 entry (MP=0): self gain 1 MP "
                "(cap 12, consumed on burst)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="MP == 0",
                notes="MP gauge — DSL gap, encoded as note",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    notes=(
                        "actually 'gain 1 MP' — DSL has no MP/charge "
                        "stat. Captured as GAIN_BURST_GAUGE proxy; "
                        "simulator must track separate MP gauge."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry (MP≥1): self gain 1 MP (cap 12)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="MP >= 1",
                notes="MP gauge — DSL gap, encoded as note",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    notes=(
                        "actually 'gain 1 MP' — DSL has no MP/charge "
                        "stat. Captured as GAIN_BURST_GAUGE proxy."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 6 full charge attacks: self Max HP +6.34% "
                "(no heal), stacks 10x, 15 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=6,
                condition="full charge attacks",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=6.34,
                    duration_seconds=15.0,
                    stacks_max=10,
                    notes="'without restoring HP' — Max HP grows but not current HP",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On MP gain: all Electric allies (not self) get "
                "DamageAsStrong +40.9% and ATK +20.9% of caster's ATK "
                "for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="MP replenished — DSL gap",
                notes="MP gauge — DSL has no MP trigger",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.ELECTRIC,
                    ),
                    magnitude=40.9,
                    duration_seconds=10.0,
                    notes="excludes self — DSL gap",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(
                        kind=TargetKind.ALL_ALLIES,
                        filter_element=Element.ELECTRIC,
                    ),
                    magnitude=20.9,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="excludes self — DSL gap",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On MP use: self DamageAsStrong +31.68%, ATK +3.2% of "
                "caster's final Max HP for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                notes="MP-use trigger — burst is the only consumer",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=31.68,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.2,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_MAX_HP,
                    notes="ATK +3.2% of caster's final Max HP (HP→ATK conversion)",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On every full charge: nearest enemy takes 547.62% of "
                "ATK damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                condition="full charge attack",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=5.4762,
                    notes="actually 'nearest to crosshair' — DSL has no spatial target",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: nearest enemy takes 1372.8% of ATK as HP-scaled "
                "damage (10% of caster's Max HP). Continuous attacks "
                "based on current MP."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=13.728,
                    notes=(
                        "actually 1372.8% of ATK scaled by 10% Max HP — "
                        "cross-stat damage (HP→damage); fires N times "
                        "based on current MP (1–12). DSL gap."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Maiden: Ice Rose is an MP-stacking nuker. She charges MP on "
        "Burst Stage 1 and Full Burst entries (cap 12), and her burst "
        "fires N hits scaled by MP, each hit at 1372.8% of ATK plus "
        "10% Max HP. Pairs especially well with characters that boost "
        "her Max HP (Centi shields, Liter / Crown buffs aren't HP)."
    ),
)
register_character(_SKILL)
