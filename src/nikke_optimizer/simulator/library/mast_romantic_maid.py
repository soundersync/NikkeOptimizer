"""Mast: Romantic Maid — B2 Water MG Elysion. Drunken-stacks team buffer.

Encoded from the live ``Character`` skill descriptions in the DB.
Mast: RM accumulates Drunken stacks via burst rotations and converts
them into team-wide Crit Rate + ATK + Distributed Damage uplifts.
The Hangover penalty (stun on max-stack expiry) is the cost.

**Source description (S1)**:

    Activates when entering Burst stage 1. Affects self.
    Drunken: Hit Rate ▼ 20%, stacks up to 3 times continuously.

    Activates only when in Drunken status. Affects all allies.
    Critical Rate ▲ 20.05% continuously. ATK ▲ 35.02% of caster's ATK continuously.

**Source description (S2)**:

    Activates when entering Burst stage 3 in Drunken status. Affects all allies.
    Distributed Damage ▲ 15.03% * Number of Drunken stacks for 10 sec.
    Reloading Speed ▲ 15.04% * Number of Drunken stacks for 10 sec.

    Activates when the caster reaches max stacks of Drunken at the end
    of Full Burst. Affects self after the stacks are removed.
    Hangover: Stun for 10 sec.

**Source description (Burst)**:

    Affects all allies. Critical Damage ▲ 40.04% for 10 sec.
    Attack Damage ▲ 15.04% for 10 sec.

    Affects all allies if in Drunken status.
    ATK ▲ (20.06% * Number of Drunken stacks) of caster's ATK for 10 sec.

**DSL gaps**:

  * **Drunken stacks** drive multiple effects scaling — encoded as
    headline magnitudes assuming 3 stacks (max). Simulator must track
    the stack counter.
  * **Hangover stun** — self-stun debuff on stack expiry; DSL has no
    SELF_STUN kind. Captured as a note.
  * "Distributed Damage" is a stat distinct from raw ATK.
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
    character_name="Mast: Romantic Maid",
    skill1=(
        SkillEffect(
            description=(
                "On B1 cast (any ally bursts at slot 1): self gains "
                "Drunken stack (×3 max). Stacks cause Hit Rate -20% but "
                "enable team buffs."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_ALLY_BURST_USE,
                condition="ally is using a Burst Stage 1 skill",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEBUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.0,
                    duration_seconds=86400.0,
                    notes=(
                        "actually 'Hit Rate -20%' per stack; encoded as "
                        "DEBUFF_ATK proxy. Track up to 3 stacks."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While Drunken: all allies Crit Rate +20.05% + ATK "
                "+35.02% of caster's ATK continuously."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Drunken stack count >= 1",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_RATE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.05,
                    duration_seconds=86400.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=35.02,
                    duration_seconds=86400.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On B3 cast in Drunken: all allies get scaling buffs "
                "(15.03% × stacks Distributed Damage, 15.04% × stacks "
                "Reload Speed) for 10 sec. Encoded at 3-stack max."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_ALLY_BURST_USE,
                condition="ally bursting at Stage 3 + Drunken active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=45.09,  # 15.03 × 3 stacks
                    duration_seconds=10.0,
                    notes="actually 'Distributed Damage'; ATK proxy. Max stacks.",
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=45.12,  # 15.04 × 3 stacks
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: all allies Crit Damage +40.04%, Attack Damage "
                "+15.04% (10s). Plus Drunken-conditional team ATK "
                "+(20.06% × stacks)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CRIT_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=40.04,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=15.04,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=60.18,  # 20.06 × 3 max stacks
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes=(
                        "Drunken-conditional: 20.06% × stacks of caster's "
                        "ATK. Max stacks (3) gives 60.18%."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Mast: Romantic Maid is the alt B2 buffer for Crit comps — at "
        "max Drunken stacks she stacks +60.18% ATK + 40% Crit Damage "
        "on top of her base +35% from S1, hitting near-Crown-tier "
        "buff totals at the cost of self Hit Rate."
    ),
)
register_character(_SKILL)
