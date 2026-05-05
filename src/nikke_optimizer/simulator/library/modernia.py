"""Modernia — B3 Fire MG hyper-DPS, Pilgrim. Sustained-fire main carry.

Encoded from the live ``Character`` skill descriptions in the DB
(scraped from Prydwen).

**Source description (S1)**:

    Activates when normal attack hits. Affects the target(s).
    Deals 3.05% of final ATK as additional damage.

    Activates when normal attack hits 200 time(s). Affects self.
    Critical Damage ▲ 14.25%, stacks up to 5 time(s) and lasts for 10 sec.
    Max Ammunition Capacity ▼ 5.04%, stacks up to 5 time(s) and lasts for 10 sec.

**Source description (S2)**:

    Affects all allies. Activates when entering Full Burst.
    Hit Rate ▲ 8.56% for 15 sec.

    Affects self. Activates when normal attack hits 200 time(s) during
    increasing Hit Rate status. ATK ▲ 29.38% for 10 sec.

**Source description (Burst)**:

    Affects all allies. Full Burst Time ▲ 5 sec.

    Affects self. Grants unlimited ammunition for 15 sec.
    Destroy Mode: Extending the line of sight and auto-aim at all
    enemies within fire range. Stage target will be recognized as a
    single enemy regardless of its interruption parts.
    Deals 2.24% of ATK as damage for 15 sec.

**DSL gaps**:

  * "Unlimited ammunition" and "Destroy Mode auto-aim" are runtime-only
    states the simulator must model — encoded as a per-shot DEAL_DAMAGE
    that runs for the burst duration, with notes for the auto-aim part.
  * "Full Burst Time +5 sec" extends the team's Full Burst window;
    the DSL doesn't yet have a TUNE_FULL_BURST_DURATION effect, so
    this is captured as a note on the burst skill rather than a typed
    effect. Track in BACKLOG → DSL semantics gaps.
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
    character_name="Modernia",
    skill1=(
        SkillEffect(
            description=(
                "Every normal attack hit deals 3.05% of final ATK as "
                "additional damage to the target."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=1),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.0305,
                    notes="3.05% of final ATK; per-hit",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 200 normal attacks: self crit damage +14.25% "
                "(stacks ×5, 10 sec) plus max ammo -5.04% (stacks ×5, 10 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=200),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=14.25,
                    duration_seconds=10.0,
                    stacks_max=5,
                ),
                # The ammo penalty is a real *negative* magnitude — the DSL
                # has no DEBUFF_AMMO_CAPACITY kind, so we stash it as a note
                # on the buff effect and let the simulator resolve later.
                Effect(
                    kind=EffectKind.BUFF_AMMO_CAPACITY,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,  # placeholder; real value is -5.04
                    duration_seconds=10.0,
                    stacks_max=5,
                    notes="actually -5.04%; DSL lacks DEBUFF_AMMO_CAPACITY",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On entering Full Burst: all allies gain Hit Rate +8.56% "
                "for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=8.56,
                    duration_seconds=15.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 200 normal attacks during the Hit Rate buff: "
                "self ATK +29.38% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=200,
                condition="while own Hit Rate buff from S2 is active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=29.38,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "All allies: Full Burst time extended by 5 sec. "
                "Self: unlimited ammo + Destroy Mode auto-aim for 15 sec, "
                "with each shot dealing 2.24% of ATK."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                # Modernia's signature damage stream during burst — the
                # 2.24% applies per shot inside Destroy Mode, captured
                # here as a per-hit DEAL_DAMAGE that the simulator can
                # gate on the burst window.
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.0224,
                    notes=(
                        "during burst (15s); Destroy Mode auto-aims and "
                        "treats stage targets as single enemy. DSL doesn't "
                        "yet model auto-aim or ammo refunding."
                    ),
                ),
                # Full-burst extension is essential for Modernia comps but
                # not yet a typed DSL effect. Encoded as a note on a
                # placeholder GAIN_BURST_GAUGE effect at magnitude 0 so
                # the simulator sees it without applying a real gain.
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=0.0,
                    notes="Full Burst time +5 sec — DSL needs TUNE_FB_DURATION",
                ),
            ),
        ),
    ),
    burst_duration_seconds=15.0,  # Modernia extends FB to 15s for herself
    notes=(
        "Modernia's value is sustained DPS through Full Burst — the 2.24% "
        "per-shot during burst combined with Destroy Mode's auto-aim and "
        "unlimited ammo is what makes her the canonical Crown-comp carry. "
        "Two DSL gaps surfaced: DEBUFF_AMMO_CAPACITY kind and a "
        "FULL_BURST_TIME_EXTEND effect."
    ),
)
register_character(_SKILL)
