"""Centi — B2 Iron RL defender, Missilis. Shield support + AOE nuke.

Encoded from the live ``Character`` skill descriptions in the DB.

Centi is the canonical "cheap shield" support — her S2 grants a
team-wide shield on cooldown and her burst clears low-HP enemies + DEF
debuffs them. Her S1's ability to reduce her own S2 cooldown is what
makes her uptime so high in PvP defense.

**Source description (S1)**:

    Activates when hitting a target with Full Charge. Affects self.
    Cooldown of Skill 2 ▼ 9.16%.

**Source description (S2)**:

    Affects all allies.
    Creates a shield, equivalent to 6.38% of the caster's final Max HP,
    which protects all allies from damage. Lasts for 5 sec.

**Source description (Burst)**:

    Affects 5 enemy unit(s) with the lowest remaining HP.
    Deals 145.46% of final ATK as damage.
    DEF ▼ 14.54% for 10 sec.

**DSL gaps**:

  * "Cooldown of Skill 2 ▼ 9.16%" reduces a non-burst skill cooldown.
    The DSL has ``REDUCE_BURST_COOLDOWN`` but no general
    ``REDUCE_SKILL_COOLDOWN`` — encoded as a note. Critical for the
    simulator since this is what makes Centi's shield uptime so high.
  * S2 itself is on its own cooldown (not Burst), but the DSL's
    triggers don't yet model named skill timers — encoded with
    ``ALWAYS`` + a note describing the cooldown loop.
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
    character_name="Centi",
    skill1=(
        SkillEffect(
            description=(
                "On Full Charge hit: reduces Centi's own Skill 2 cooldown "
                "by 9.16% (compounds the shield uptime)."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Full Charge hit lands",
            ),
            effects=(
                # The DSL has REDUCE_BURST_COOLDOWN, not a generic
                # REDUCE_SKILL_COOLDOWN. Encoded with magnitude 0 + a note
                # so the simulator sees the link without misapplying it.
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    notes=(
                        "actually 'Cooldown of Skill 2 -9.16%' — DSL has "
                        "no REDUCE_SKILL_COOLDOWN kind. Critical for "
                        "Centi's shield uptime."
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Periodically: grants all allies a shield equal to 6.38% "
                "of Centi's max HP, lasting 5 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ALWAYS,
                notes=(
                    "S2 fires on its own cooldown, accelerated by S1. "
                    "DSL doesn't have ON_SKILL_2_COOLDOWN; ALWAYS is a "
                    "placeholder for the simulator to gate."
                ),
            ),
            effects=(
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=6.38,
                    duration_seconds=5.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "Burst: deals 145.46% of final ATK to the 5 lowest-HP "
                "enemies, then debuffs their DEF by 14.54% for 10 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP, count=5),
                    magnitude=1.4546,
                    notes=(
                        "5 lowest-HP enemies; DSL's ENEMY_LOWEST_HP single "
                        "target is being abused with count=5 — the count "
                        "field's semantics aren't defined for this kind"
                    ),
                ),
                Effect(
                    kind=EffectKind.DEBUFF_DEFENSE,
                    target=Target(kind=TargetKind.ENEMY_LOWEST_HP, count=5),
                    magnitude=14.54,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Centi's value in PvP defense is the periodic team shield + "
        "the AOE DEF debuff on burst. Her S1 → S2 cooldown loop means "
        "shields can come up several times per match if she gets enough "
        "Full Charge hits. The simulator must model her S2 timer to "
        "score her correctly."
    ),
)
register_character(_SKILL)
