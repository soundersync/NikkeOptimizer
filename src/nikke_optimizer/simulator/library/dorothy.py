"""Dorothy — B1 Water AR DPS-buffer, Pilgrim. The 2-1-2 comp enabler.

Encoded from the live ``Character`` skill descriptions in the DB.
Dorothy is unusual: a B1 slot that doubles as a damage dealer + team
debuffer-via-Brand. Her S2 is a permanent passive that Manifestation
mode (her burst) accelerates.

**Source description (S1)**:

    Activates when firing the last bullet. Affects all allies.
    Cooldown of Burst Skill ▼ 1.56 sec.

    Activates when firing the last bullet during Manifestation. Affects
    all allies. Damage to Parts ▲ 50.68%, lasts for 5 seconds.

**Source description (S2)**:

    Affects all enemies. Scorch to Dust: Deals 216% of final ATK as
    distributed damage.

**Source description (Burst)**:

    Affects self. Manifestation: Changes the cooldown of Skill 2 to 2 sec.
    Lasts for 10 sec. Gain Pierce for 10 sec.

    Affects a designated enemy. Brand: Accumulates total damage dealt
    to enemies during the duration, and then deals that accumulated
    damage to all enemies as distributed damage once the duration ends.
    The maximum accumulated damage is 8900.83% of the caster's final
    ATK. Lasts for 10 sec.

**DSL gaps**:

  * "Cooldown of Skill 2 → 2 sec" overrides a non-burst skill cooldown
    — encoded as a note (DSL has no SET_SKILL_COOLDOWN).
  * "Brand" is a damage-accumulator mechanic with a delayed-payload
    cap of 8900% — captured as a single DEAL_DAMAGE with the cap value.
    The actual damage is dynamic; simulator must track Brand state.
  * "Damage to Parts" is a PvE boss-only stat — note included.
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
    character_name="Dorothy",
    skill1=(
        SkillEffect(
            description=(
                "On firing the magazine's last bullet: all allies burst "
                "CD -1.56 sec. (Stacks across reload cycles for steady "
                "burst rotation acceleration.)"
            ),
            trigger=Trigger(kind=TriggerKind.ON_LAST_AMMO),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=1.56,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On last-bullet during Manifestation: all allies "
                "'Damage to Parts' +50.68% for 5 sec (PvE-leaning stat)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_LAST_AMMO,
                condition="Dorothy is in Manifestation mode (post-burst)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=50.68,
                    duration_seconds=5.0,
                    notes="PvE boss-only stat",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodic 'Scorch to Dust': deals 216% of ATK as "
                "distributed damage to all enemies. Cooldown is "
                "non-burst (own timer); Manifestation reduces it to 2 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes=(
                    "fires on Skill 2's own cooldown timer; Manifestation "
                    "(burst) sets the cooldown to 2 sec for 10 sec. The "
                    "DSL has no SET_SKILL_COOLDOWN so this dynamic is "
                    "captured in the burst notes."
                ),
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=2.16,
                    notes="distributed damage to all enemies",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: Manifestation (S2 cd → 2 sec, self gains Pierce) "
                "for 10 sec. Designated enemy gets 'Brand': accumulates "
                "team damage and deals it back to all enemies after 10 "
                "sec, capped at 8900.83% of Dorothy's final ATK."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=10.0,
                ),
                # Brand payload — encoded as a delayed DEAL_DAMAGE at the
                # cap value. The simulator must accumulate damage during
                # the 10s window and apply at cap or at expiry.
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ENEMIES),
                    magnitude=89.0083,
                    notes=(
                        "Brand: caps at 8900.83% of caster ATK after 10s "
                        "of accumulating team damage. Delayed payload — "
                        "the simulator must track the Brand timer."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Dorothy's value comes from Manifestation: while active, her S2 "
        "fires every 2 seconds for 10 seconds (5 ticks of 216% damage), "
        "and her Brand redirects accumulated team damage as a delayed "
        "AOE nuke. Pairs especially well with Modernia (high sustained "
        "damage to feed Brand)."
    ),
)
register_character(_SKILL)
