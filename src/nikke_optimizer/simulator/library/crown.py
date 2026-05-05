"""Crown — B2 Iron MG buffer/defender, Pilgrim. Universal carry amplifier.

Encoded from the live ``Character`` skill descriptions in the DB
(scraped from Prydwen).

**Source description (S1)** — split into two branches based on whether
the ally bursted previously:

    Activates at the start of Full Burst.
    Affects all allies who previously cast their Burst Skills.
        ATK ▲ 64.51% of caster's ATK for 15 sec.
        Reloading Speed ▲ 44.35% for 15 sec.
    Affects all allies who did not previously cast their Burst Skills.
        DEF ▲ 37.44% of caster's DEF for 15 sec.
        Reloading Speed ▲ 44.35% for 15 sec.

**Source description (S2)** — multi-stage Relax → Attract → recovery loop:

    Activates after 43 normal attack(s). Affects self.
        Relax: HP Potency ▲ 4.06% continuously, stacks up to 20 times.
    Activates when Relax is fully stacked, affects self after the stacks
    are removed.
        Invulnerable for 5 sec.
        Attract: Taunt all enemies for 5 sec.
        Recovers 5.23% of caster's final Max HP as HP.
    Activates when recovery takes effect. Affects all allies.
        Attack Damage ▲ 20.99% for 7 sec.

**Source description (Burst)**:

    Affects all allies.
        Attack Damage ▲ 36.24% for 15 sec.
        Creates a Shield equal to 10.45% of caster's final Max HP for 15 sec.

The Relax-stack loop in S2 is multi-step state — encoded as a single
SkillEffect with a CONDITIONAL trigger because the DSL doesn't yet
model intermediate states. The simulator will need a richer state
machine; for now the encoded effect captures the team-ATK boost that
fires once the loop completes.
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
    character_name="Crown",
    skill1=(
        SkillEffect(
            description=(
                "On Full Burst start, ATK +64.51% to allies who already "
                "bursted, plus reload speed."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="targeted ally has already used their burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=64.51,
                    duration_seconds=15.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                    notes="conditional: only allies who already bursted",
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=44.35,
                    duration_seconds=15.0,
                    notes="conditional: only allies who already bursted",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Full Burst start, DEF +37.44% to allies who haven't "
                "bursted yet, plus reload speed."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_FULL_BURST_START,
                condition="targeted ally has NOT yet used their burst",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=37.44,
                    duration_seconds=15.0,
                    scaling_source=ScalingSource.CASTER_DEF,
                    notes="conditional: only allies who haven't bursted",
                ),
                Effect(
                    kind=EffectKind.BUFF_RELOAD_SPEED,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=44.35,
                    duration_seconds=15.0,
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "Stack 'Relax' on self every 43 normal attacks (max 20). "
                "When fully stacked, become invulnerable, taunt enemies, "
                "and grant the team an attack-damage buff."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=43),
            effects=(
                # The simulator will need a state machine to model the
                # 20-stack threshold + invulnerability window. For now we
                # encode the headline outcomes:
                Effect(
                    kind=EffectKind.HEAL_HP_FLAT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=5.23,
                    notes="fires when Relax fully stacks",
                ),
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,  # boolean-ish flag
                    duration_seconds=5.0,
                    notes="taunts all enemies; fires when Relax fully stacks",
                ),
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=20.99,
                    duration_seconds=7.0,
                    notes="fires after Crown's invulnerability + heal cycle",
                ),
            ),
        ),
    ),
    burst_skill=(
        SkillEffect(
            description=(
                "All allies: attack damage +36.24% for 15 sec, plus a "
                "shield equal to 10.45% of Crown's max HP for 15 sec."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BURST_USE),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATTACK_DAMAGE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=36.24,
                    duration_seconds=15.0,
                ),
                Effect(
                    kind=EffectKind.GRANT_SHIELD,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=10.45,
                    duration_seconds=15.0,
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Crown's burst grants both an attack buff AND a shield to the "
        "whole team — this is why she's mandatory in nearly every meta "
        "carry comp. Her S1 makes her conditional on burst order: allies "
        "who burst before Crown get the ATK; allies who burst after get "
        "DEF. The simulator must model burst order to score her correctly."
    ),
)
register_character(_SKILL)
