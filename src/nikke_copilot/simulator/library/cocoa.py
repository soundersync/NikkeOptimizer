"""Cocoa — B1 Fire SR. Cover-heal supporter with cleanse + Sustained
Damage debuff stacking.

Encoded from the live ``Character`` skill descriptions in the DB.
Cocoa's role is anti-DOT support: she stacks a Sustained-Damage debuff
on enemies (Tomato Sauce, max 15) via her Full Charge attacks, heals
covers across the team, and her burst dispels and pops a team-wide
ATK debuff once Tomato Sauce maxes out.

**Source description (S1)**:

    All allies: recover 17.76% of cover's HP
    2 random debuffed allies: dispel 1 debuff each

**Source description (S2)**:

    On Full Charge attack: self Professional Tomato Sauce —
    Sustained Damage -4.37% per stack (max 15, 5 sec)

**Source description (Burst)**:

    All allies: dispel 1 debuff
    On Tomato Sauce fully stacked: all enemies — ATK -13.59% for 10s
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
    character_name="Cocoa",
    skill1=(
        SkillEffect(
            description="All allies: recover 17.76% of cover's HP (S1 ticker)",
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes="S1 ticks on its own cooldown",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=17.76,
                    notes="cover-HP heal (not max-HP based)",
                ),
                Effect(
                    kind=EffectKind.CLEANSE,
                    target=Target(kind=TargetKind.NEAREST_ALLIES, count=2),
                    notes="2 random debuffed allies — dispel 1 debuff each",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description="On Full Charge: self Tomato Sauce -4.37% Sustained Dmg (max 15)",
            trigger=Trigger(
                kind=TriggerKind.ON_HIT,
                every_n_hits=1,
                notes="full-charge attack only (SR mechanic)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_SUSTAINED_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=5.0,
                    stacks_max=15,
                    notes=(
                        "Tomato Sauce: -4.37% Sustained Damage per stack "
                        "(self-DEBUFF, captured as 0-mag BUFF for stack "
                        "tracking; magnitude flips meaning at simulation "
                        "time)."
                    ),
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description="Burst: all allies cleanse + (if Sauce maxed) enemies ATK -13.59%",
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.CLEANSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    notes="dispel 1 debuff per ally",
                ),
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=13.59,
                    duration_seconds=10.0,
                    notes="conditional: only when Tomato Sauce at 15 stacks",
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Fire SR B1 supporter. Cleanse + cover-heal + conditional ATK "
        "debuff. Niche pick for DOT-heavy PvE; PvP value is the cleanse "
        "+ cover heal vs status-spamming defenders."
    ),
)
register_character(_SKILL)
