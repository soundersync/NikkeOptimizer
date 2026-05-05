"""2B — B3 Fire AR Abnormal NieR collab carry.

Encoded from the live ``Character`` skill descriptions in the DB.
2B (NieR: Automata) has a cumulative-activation Max-HP self-buff (1st:
+10%, 2nd: +20%, 3rd: +57.76%) plus an ATK-from-Max-HP scaling that
turns her into a self-buffing tank-DPS. Her burst is a massive AOE
distributed-damage payload + single-target follow-up.

**Source description (S1)**:

    Activates when using Burst Skill. Affects self.
    Effect changes according to the number of activation time(s).
    Previous effects trigger repeatedly:
        Once:        Max HP ▲ 10.03% continuously.
        Twice:       Max HP ▲ 20.06% continuously.
        Three times: Max HP ▲ 57.76% continuously.

**Source description (S2)**:

    Activates after firing 300 time(s). Affects all enemies.
    Deals 167.45% of final ATK as damage.

    Activates when entering battle. Affects self.
    ATK ▲ 6.16% of caster's final Max HP continuously.

**Source description (Burst)**:

    Affects all enemies. Deals 2439.36% of final ATK as Distributed Damage.

    Affects 1 enemy unit(s) with the highest Max HP.
    Deals 792% of final ATK as additional damage.
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
    character_name="2B",
    skill1=(
        SkillEffect(
            description=(
                "On burst use: self Max HP buff stacks cumulatively. "
                "Encoded at 3rd-tier (57.76%); 1st/2nd are 10.03/20.06."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                notes="effect scales with cumulative activation count",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=57.76,
                    duration_seconds=86400.0,
                    notes="continuous until 4th burst removes; cumulative",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Every 300 normal attacks: deals 167.45% of ATK to all enemies."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=300),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=1.6745,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On battle start: self ATK +6.16% of own Max HP "
                "continuously (HP-to-ATK scaling)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=6.16,
                    duration_seconds=86400.0,
                    notes="actually 6.16% of Max HP added to ATK; cross-stat scaling",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 2439.36% Distributed Damage to all enemies + "
                "792% additional damage to highest-HP enemy."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=24.3936,
                    notes="distributed across all enemies",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_HIGHEST_HP),
                    magnitude=7.92,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "2B's S1 cumulative HP scaling (peaking at +57.76% Max HP after "
        "3 bursts) + S2's HP-to-ATK conversion makes her significantly "
        "stronger after a few burst cycles. Solid PvE pick; in PvP her "
        "burst payload (2439% AOE + 792% on tank) is potent."
    ),
)
register_character(_SKILL)
