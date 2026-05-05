"""Chisato Nishikigi — B3 Iron SMG Abnormal (Lycoris Recoil collab).

Encoded from the live ``Character`` skill descriptions in the DB.
Chisato's identity is the Extrasensory gauge (charged to 100% on
battle start, decays 1%/2sec) — different threshold tiers grant
different undispellable buffs that stack.

**Source description (S1)**:

    Activates at the start of battle. Affects self.
    Charges Extrasensory to 100% continuously, up to 100%.
    This effect cannot be dispelled.

    Activates while in Extrasensory status. Affects self.
    Effect changes according to the charge level of Extrasensory.
    Previous effects trigger repeatedly.
        Only when at 100%: Dodging Bullets: Invulnerable for 2 sec.
        Only when above 70%: ATK ▲ 53.59% continuously.
                              This effect cannot be dispelled.
        Only when above 55%: True Damage ▲ 48.62% continuously.
                              This effect cannot be dispelled.
        Only when above 25%: Hit Rate ▲ 22.37% continuously.
                              This effect cannot be dispelled.

    Affects self every 2 sec. Extrasensory ▼ 1%.

**Source description (S2)**:

    Activates when using Burst Skill. Affects self.
    Normal attacks deal true damage for 10 sec.

    Activates after landing 48 normal attack(s). Affects the target.
    Deals 472.18% of final ATK as true damage.

**Source description (Burst)**:

    Affects self. Charges Extrasensory to 100%. ATK ▲ 73.16% for 10 sec.
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
    character_name="Chisato Nishikigi",
    skill1=(
        SkillEffect(
            description=(
                "Battle start: self Extrasensory charges to 100% "
                "(undispellable)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    notes=(
                        "actually 'Extrasensory charged to 100%' — DSL "
                        "has no Extrasensory gauge. GAIN_BURST_GAUGE "
                        "proxy; simulator must track separate gauge."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While Extrasensory at 100%: self Invulnerable 2 sec "
                "(undispellable)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Extrasensory == 100%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=2.0,
                    notes=(
                        "actually 'Invulnerable for 2 sec' — DSL has "
                        "no INVULNERABILITY kind. 0-mag BUFF_DEFENSE "
                        "with note flag."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While Extrasensory > 70%: self ATK +53.59% continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Extrasensory > 70%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=53.59,
                    duration_seconds=999.0,
                    notes="continuous undispellable while in tier",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While Extrasensory > 55%: self True Damage +48.62% "
                "continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Extrasensory > 55%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=48.62,
                    duration_seconds=999.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While Extrasensory > 25%: self Hit Rate +22.37% "
                "continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Extrasensory > 25%",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=22.37,
                    duration_seconds=999.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 2 sec: self Extrasensory -1% (gauge decay)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER,
                cooldown_seconds=2.0,
            ),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    notes=(
                        "actually 'Extrasensory -1% every 2 sec' — DSL "
                        "has no Extrasensory gauge. 0-mag with note flag."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On burst use: self normal attacks deal true damage "
                "for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=10.0,
                    notes=(
                        "'normal attacks deal true damage for 10 sec' — "
                        "encoded as full true-damage conversion (+100%) "
                        "for the burst window."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 48 normal attacks: target takes 472.18% true "
                "damage."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=48),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_TRUE_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=4.7218,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: self Extrasensory → 100%; ATK +73.16% 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    notes="actually 'Extrasensory to 100%' — gauge refresh",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=73.16,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Chisato is a self-buff carry built around the Extrasensory "
        "gauge — battle start grants 100% (= all 4 tiers active), gauge "
        "decays 1%/2 sec, burst refreshes to 100%. Her S2 converts all "
        "normal attacks to true damage during burst, making her a hard "
        "counter to high-DEF defenders."
    ),
)
register_character(_SKILL)
