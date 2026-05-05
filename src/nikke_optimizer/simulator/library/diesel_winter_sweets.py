"""Diesel: Winter Sweets — B3 Fire RL. Sustained-damage attacker
with Highlight/Intro state machine.

Encoded from the live ``Character`` skill descriptions in the DB.
D:WS toggles between Intro (used burst) and Highlight (didn't burst)
states on Full Burst entry. Highlight gives a much larger sustained-
damage buff (+235.03% vs +60.19%) — the optimal play is to skip her
burst slot in favor of bigger Highlight damage. Burst inflicts +DT
debuff and a stage-target sustained DOT.

**Source description (S1)**:

    On entering FB after using Burst: self Intro — Crit Damage +20.28% (perm)
    On entering FB without using Burst: self Highlight — Crit Damage +20.28% (perm)
    On entering FB (Intro): self Sustained Damage +60.19% for 10s
    On entering FB (Highlight): self Sustained Damage +235.03% for 10s

**Source description (S2)**:

    On part destroyed: all allies (except self) Mute (Noise Pollution
    immunity, max 3 stacks)
    On part destroyed: self Sustained Damage +68.04% for 15s
    On Full Charge: self Sustained Damage +318.14% for 3s, max 2 stacks
    On entering FB: stage target — 63.33% of final ATK as sustained
    damage every 1s for 9s

**Source description (Burst)**:

    All enemies: Damage Taken +25.09% for 10s
    All enemies: 18.43% of final ATK as sustained damage / 1s for 9s
    Stage target: 181.2% of final ATK as sustained damage / 1s for 9s
    All allies (except self) if self in Highlight: Noise Pollution
    (Hit Rate -100%) for 1s
    All allies if self in Highlight: Mute -1 stack
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
    character_name="Diesel: Winter Sweets",
    skill1=(
        SkillEffect(
            description="On FB entry (after burst): self Intro — Crit Damage +20.28% perm",
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="self used Burst Skill this rotation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.28,
                    duration_seconds=999.0,
                    notes="Intro state — permanent, undispellable, persists on revive",
                ),
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=60.19,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description="On FB entry (skipped burst): self Highlight — bigger sustained-dmg payload",
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="self did not use Burst Skill this rotation",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.28,
                    duration_seconds=999.0,
                    notes="Highlight state — permanent, undispellable, persists on revive",
                ),
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=235.03,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="Part destroyed: self Sustained Damage +68.04% 15s",
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="ally or self destroys an enemy's part",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=68.04,
                    duration_seconds=15.0,
                ),
            ),
        ),
        SkillEffect(
            description="Full Charge: self Sustained Damage +318.14% 3s (max 2 stacks)",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                notes="full-charge attacks only",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=318.14,
                    duration_seconds=3.0,
                    stacks_max=2,
                ),
            ),
        ),
        SkillEffect(
            description="On FB entry: stage target 63.33% sustained / 1s for 9s",
            trigger=Trigger(kind=TriggerKind.ON_FULL_BURST_START),
            effects=(
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.6333,
                    duration_seconds=9.0,
                    notes="63.33% of final ATK / 1s sustained DOT",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: enemies +25.09% Damage Taken 10s + sustained DOTs",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=25.09,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=0.1843,
                    duration_seconds=9.0,
                ),
                Effect(
                    kind=EffectKind.INFLICT_BURN,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.812,
                    duration_seconds=9.0,
                    notes="stage target — 181.2% / 1s sustained DOT",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire RL B3 sustained-damage attacker. Highlight (skipped burst) "
        "outdamages Intro (used burst) by ~3.9× sustained-dmg buff. "
        "Best as the team's 4th/5th member that lets others burst. "
        "Permanent crit-dmg buff persists across revives — strong vs "
        "wipe-prone defender comps."
    ),
)
register_character(_SKILL)
