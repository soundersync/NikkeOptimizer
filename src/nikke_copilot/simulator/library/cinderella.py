"""Cinderella — B3 Electric RL Pilgrim hyper-DPS with decoy + Beautiful stacks.

Encoded from the live ``Character`` skill descriptions in the DB.
Cinderella's signature is the Decoy mechanic + 'Beautiful' stacking
Max-HP buff (12 stacks max) that scales her burst damage. Her burst
fires 10 sequential 1365.92% hits, with a Beautiful-stacks bonus tier.

**Source description (S1)**:

    Activates when entering Burst Skill Stage 3. Affects self.
    ATK ▲ 2.71% of caster's final Max HP for 10 sec.

    Activates when attacking with Full Charge. Affects self.
    Charge Speed ▲ 100%. Removed upon reloading to max ammunition.

    Activates when hitting a target with Full Charge. Affects the target.
    Deals 136.6% of final ATK as additional damage.

**Source description (S2)**:

    Activates at the start of battle. Affects self.
    Decoy: Creates an avatar with 96% of caster's final Max HP continuously.

    Activates when entering Burst Skill Stage 3. Affects self.
    Decoy: Creates an avatar with 96% of caster's final Max HP continuously.

    Activates when decoy exists. Affects self every 3 sec.
    Beautiful: Max HP ▲ 1.6% continuously, stacks up to 12 time(s).

**Source description (Burst)**:

    Affects random enemies. Deals 1365.92% of final ATK as damage.
    Attacks sequentially for 10 time(s).

    Affects the same target(s) when in Beautiful status.
    Deals 28.9% of final ATK as additional damage.
    Mirrors the stack count of Beautiful.

**DSL gaps**:

  * **Decoy** is a state-machine mechanic (an avatar with HP that
    soaks damage); no DSL kind. Encoded as a note on a placeholder.
  * **Beautiful stacks** scale damage on burst — captured as a high
    base burst damage with the stack bonus in notes.
  * "ATK +2.71% of caster's final Max HP" — cross-stat scaling that
    the DSL doesn't model directly. Encoded with a note.
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
    character_name="Cinderella",
    skill1=(
        SkillEffect(
            description=(
                "On Burst Stage 3 cast (self bursts): self ATK +2.71% "
                "of own Max HP for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.71,
                    duration_seconds=10.0,
                    notes=(
                        "actually '2.71% of caster's final Max HP' — "
                        "cross-stat scaling. Captured at face value."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge attack: self Charge Speed +100% (until "
                "reload to max ammunition)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge release; cleared on full reload",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.0,
                    duration_seconds=86400.0,
                    notes="cleared on reload to max ammo",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Charge hit: target takes additional 136.6% "
                "of ATK as damage."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="full charge hit lands",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=1.366,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On battle start: self spawns a Decoy with 96% of "
                "Cinderella's max HP. (And again on B3 cast — re-spawns "
                "the avatar.)"
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=96.0,
                    duration_seconds=86400.0,
                    notes=(
                        "actually 'Decoy avatar' (state-machine entity, "
                        "not a shield). DSL gap (DECOY). Effective HP "
                        "boost is similar to a shield in coarse model."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "While decoy exists: every 3 sec, self gains Beautiful "
                "stack — Max HP +1.6%, stacks up to 12 (max +19.2%)."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_TIMER,
                cooldown_seconds=3.0,
                condition="Decoy avatar is active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_HP,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.6,
                    duration_seconds=86400.0,
                    stacks_max=12,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: 10 sequential hits at 1365.92% of ATK to random "
                "enemies. With Beautiful stacks, +28.9% per stack on "
                "the same targets (mirrors stack count, max 12 = "
                "+346.8% total)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=10),
                    magnitude=13.6592,
                    notes="10 sequential hits at 1365.92% each",
                ),
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMIES_RANDOM_K, count=10),
                    magnitude=3.468,  # 28.9% × 12 stacks max
                    notes=(
                        "Beautiful bonus: +28.9% per stack on the same "
                        "10 targets, capped at 12 stacks (+346.8%). "
                        "Realistic at full stacks; less at lower."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Cinderella is a high-ceiling burst-payload carry — her 10 × "
        "1365% sequential hits + Beautiful stacking can hit 5x the "
        "burst payload of a typical B3. The Decoy mechanic also "
        "soaks an avatar's-worth of damage before she takes any."
    ),
)
register_character(_SKILL)
