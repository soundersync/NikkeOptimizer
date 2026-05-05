"""Rapi: Red Hood — B3 Fire MG Elysion hyper-DPS / Combat-Assist toggler.

Encoded from the live ``Character`` skill descriptions in the DB.
Rapi: Red Hood (the Treasure-style limited release) has the same
squad-conditional state-flip pattern as Anis: Star: 'Combat Assist'
mode when no other B1 ally is present, with different effects
depending on which mode + which burst-stage was used.

**Source description (S1)**:

    Activates at the start of battle and at the end of Full Burst.
    Effects differ according to squad formation. Activates only the
    corresponding effect.

      Affects self if there are no Burst Stage 1 allies.
        Combat Assist: Changes to Burst phase 1 continuously.
      Affects self if there are Burst Stage 1 allies.
        Removes Combat Assist.

      Affects all allies if in Combat Assist status when entering Full Burst.
        Cooldown of Burst Skill ▼ 7.48 sec.
        Attack Damage ▲ 8.02% for 10 sec.

      Affects self if NOT in Combat Assist status when entering Full Burst.
        ATK ▲ 95.04% for 10 sec.
        Damage to interruption Parts ▲ 48% for 10 sec.

**Source description (S2)**:

    Activates at the start of battle. Affects self.
    Applies damage as strong element to Electric Code enemies continuously.
    Projectile attachment damage ▲ 150.72% continuously.
    Projectile explosion damage ▲ 100.6% continuously.

    Activates after 120 normal attack(s). Affects self.
    Attachable Projectiles Effect: Launches attachable projectiles that
    attach to hit locations. When entering Full Burst, the projectiles
    explode.
    Projectile attachment damage: Deals 88.11% of final ATK as damage.
    Projectile explosion damage: Deals 88.11% of final ATK as damage.
    Max Ammunition Capacity: 1 round(s).

**Source description (Burst)** — two-stage:

    When used in Stage I: Squad Support Action Style
        Self: Cooldown of Burst Skill ▼ 20 sec. Explosion Radius ▲ 100.62% for 10 sec.
        All allies: ATK ▲ 18.01% of caster's ATK for 10 sec.

    When used in Stage 3: High-Mobility Close-Range Combat Weapon
        Crosshair-nearest enemy: deals 2808% of final ATK as additional damage.
        Self: Explosion Radius ▲ 100.62% for 10 sec.
              Projectile attachment damage ▲ 421.2% for 10 sec.
              Skill 2 attachable projectiles trigger count condition ▼ 60 times for 10 sec.

**DSL gaps**:

  * "Combat Assist" mode flip — same gap as Anis: Star.
  * "Damage as strong element" vs Electric — element-conditional damage.
  * "Projectile attachment / explosion damage" — RL-only damage stats
    distinct from BUFF_CHARGE_DAMAGE; encoded as note.
  * "Skill 2 attachable projectiles trigger count condition ▼ 60 times" —
    mutates the S2 trigger threshold (similar to SBS burst's threshold
    mutation).
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
    character_name="Rapi: Red Hood",
    skill1=(
        SkillEffect(
            description=(
                "On battle start / FB end with no other B1 ally: enter "
                "Combat Assist mode (acts as Burst phase 1 continuously)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="solo B1 (Combat Assist mode)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.GAIN_BURST_GAUGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    notes=(
                        "Combat Assist state — Rapi: RH fills the B1 slot "
                        "for the team. DSL gap (NAMED_STATE_FLIP)."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry while in Combat Assist: all allies "
                "burst CD -7.48s, Attack Damage +8.02% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="Combat Assist mode active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=7.48,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=8.02,
                    duration_seconds=10.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst entry while NOT in Combat Assist: self "
                "ATK +95.04% and 'Damage to interruption Parts' +48% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="Combat Assist mode NOT active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=95.04,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_DAMAGE_TO_PARTS,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=48.0,
                    duration_seconds=10.0,
                    notes="'Damage to interruption Parts' — PvE-only",
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On battle start: anti-Electric strong-element damage "
                "+ projectile damage stacks (RL specific)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ELEMENT_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=86400.0,
                    notes=(
                        "anti-Electric strong-element damage; "
                        "+150.72% projectile-attach damage and "
                        "+100.6% projectile-explosion damage. RL-only "
                        "stats — DSL has no PROJECTILE_DAMAGE kind."
                    ),
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Every 120 normal attacks: launches Attachable "
                "Projectiles that explode on Full Burst entry. Each "
                "deals 88.11% of ATK on attach + 88.11% on explosion."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=120),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.8811,
                    notes="attach phase; explosion phase fires on FB entry",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Stage 1 (Squad Support Action Style): self burst CD -20s "
                "+ explosion radius +100.62%; all allies ATK +18.01% for 10s."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="burst used in Stage 1 (Combat Assist mode)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=20.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=18.01,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "Stage 3 (High-Mobility Close-Range): crosshair enemy "
                "takes 2808% of ATK; self gets explosion radius +100.62% + "
                "projectile-attach damage +421.2% + S2 trigger threshold "
                "lowered by 60 hits for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="burst used in Stage 3 (non-Combat Assist mode)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_FRONT),
                    magnitude=28.08,
                    notes="2808% — single-target nuke",
                ),
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=421.2,
                    duration_seconds=10.0,
                    notes=(
                        "projectile-attach damage +421.2%; encoded as "
                        "BUFF_CHARGE_DAMAGE proxy. ALSO S2 threshold "
                        "drops by 60 hits — DSL gap (TRIGGER_COUNTER_MUTATE)."
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Rapi: Red Hood is the dual-mode B1/B3 — solo-B1 teams get "
        "Combat Assist (effective B1 with team CD reduction); double-B1 "
        "teams have her in B3 with massive single-target nuke + projectile "
        "stacking. Same complexity tier as Anis: Star."
    ),
)
register_character(_SKILL)
