"""Red Hood — Flex (B1/B2/B3) Iron SR carry, Pilgrim.

Encoded from the live ``Character`` skill descriptions in the DB. Red
Hood is the most mechanically complex of our verified entries — her
burst has three sequential stages, and several effects involve
non-standard stats (Charge Speed → Charge Damage conversion, Pierce
range, weapon-change). The DSL captures the headline mechanics; lossy
parts are listed in the notes.

**Source description (S1)**:

    Activates when casting a normal attack. Affects self.
    Charge Speed ▲ 3.81%, stacks up to 10 time(s) and lasts for 5 sec.

    Activates when entering battle. Affects self. Convert excess value
    over 100% of Charge Speed to Charge Damage.
    Charge Damage ▲ 240% of the excess value continuously.

**Source description (S2)** — four conditional sub-effects gated on
which burst stage is active:

    Activates when entering battle. Affects self. Gain Pierce continuously.
    Activates during Beast Cage. Affects all allies.
        DEF ▲ 50.68% of caster's DEF for 10 sec.
    Activates during The Last Howl. Affects self.
        Recovers 23.04% of attack damage as HP over 10 sec.
    Activates when casting Red Wolf. Affects self.
        ATK ▲ 71.42% for 10 sec.

**Source description (Burst)** — three-stage progression. Each cast
advances to the next stage; stages 1 and 2 are once-per-battle:

    Step 1: Beast Cage
        All allies: ATK ▲ 77.55% of caster's ATK for 10 sec.
        Self: Cooldown of Burst Skill ▼ 40 sec. Activates once per battle.
    Step 2: The Last Howl
        Self: Attract: Taunt all enemies for 10 sec.
        HP Potency ▲ 74.88% for 10 sec.
        Cooldown of Burst Skill ▼ 40 sec. Activates once per battle.
    Step 3: Red Wolf
        Self: Change weapon — damage 51.46% of final ATK,
        full charge damage 250% of damage, lasts 10 sec.
        Pierce range ▲ 100% for 10 sec.
        Charge Speed ▲ 100.8% for 10 sec.

**DSL gaps**:

  * **Charge Speed → Charge Damage conversion** (S1): non-trivial
    cross-stat conversion. Encoded as a single note on a placeholder
    BUFF_CHARGE_DAMAGE so the simulator sees it; real value depends on
    runtime Charge Speed value.
  * **Pierce range +100%** (Burst Step 3): the DSL has BUFF_PIERCE
    but no concept of pierce *range* as a separate dimension.
  * **"Activates during X" conditional triggers**: encoded as
    ``CONDITIONAL`` triggers with the burst-stage name in ``condition``
    so the simulator can gate them on the right sub-step.
  * **Once-per-battle CD reduction** in burst Steps 1 + 2 — captured as
    a REDUCE_BURST_COOLDOWN with a per-battle-cap note. The DSL
    doesn't yet have a one-shot trigger flag.
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
    character_name="Red Hood",
    skill1=(
        SkillEffect(
            description=(
                "Each normal attack stacks Charge Speed +3.81% (max ×10, "
                "5 sec)."
            ),
            trigger=Trigger(kind=TriggerKind.ON_HIT, every_n_hits=1),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=3.81,
                    duration_seconds=5.0,
                    stacks_max=10,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On battle start: Charge Speed above 100% converts to "
                "Charge Damage at 240%. (Continuous; magnitude depends on "
                "runtime Charge Speed and so is encoded as a placeholder.)"
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_DAMAGE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=86400.0,  # effectively battle-long
                    notes=(
                        "240% of (Charge Speed - 100%); simulator must "
                        "recompute each tick"
                    ),
                ),
            ),
        ),
    ),
    skill2=(
        SkillEffect(
            description=(
                "On battle start: self gains Pierce continuously."
            ),
            trigger=Trigger(kind=TriggerKind.ON_BATTLE_START),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=86400.0,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "During Beast Cage (Burst Step 1): all allies gain DEF "
                "+50.68% (of caster's DEF) for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Burst Step 1 'Beast Cage' is active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_DEFENSE,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=50.68,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_DEF,
                ),
            ),
        ),
        SkillEffect(
            description=(
                "During The Last Howl (Burst Step 2): self recovers "
                "23.04% of attack damage as HP over 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Burst Step 2 'The Last Howl' is active",
            ),
            effects=(
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=2.304,  # 23.04% / 10s
                    duration_seconds=10.0,
                    notes="recovers 23.04% of attack damage; per-second proxy",
                ),
            ),
        ),
        SkillEffect(
            description=(
                "On Red Wolf cast (Burst Step 3): self ATK +71.42% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.CONDITIONAL,
                condition="Burst Step 3 'Red Wolf' is being cast",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=71.42,
                    duration_seconds=10.0,
                ),
            ),
        ),
    ),
    burst_skill=(
        # Step 1 — Beast Cage
        SkillEffect(
            description=(
                "Step 1 (Beast Cage): all allies ATK +77.55% (of caster's "
                "ATK) for 10 sec; self burst CD -40 sec, once per battle."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="first burst use of battle (Beast Cage stage)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_ATK,
                    target=Target(kind=TargetKind.ALL_ALLIES),
                    magnitude=77.55,
                    duration_seconds=10.0,
                    scaling_source=ScalingSource.CASTER_ATK,
                ),
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.0,  # seconds
                    notes="once per battle",
                ),
            ),
        ),
        # Step 2 — The Last Howl
        SkillEffect(
            description=(
                "Step 2 (The Last Howl): self taunts all enemies for 10 sec; "
                "HP Potency +74.88% for 10 sec; burst CD -40 sec, once per "
                "battle."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="second burst use of battle (The Last Howl stage)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.TAUNT,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=10.0,
                ),
                # HP Potency boost — encoded as a heal-per-second placeholder
                # since the DSL doesn't have a HEAL_POTENCY effect kind.
                Effect(
                    kind=EffectKind.HEAL_PER_SECOND,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=0.0,
                    duration_seconds=10.0,
                    notes="HP Potency +74.88%; DSL needs BUFF_HEAL_POTENCY",
                ),
                Effect(
                    kind=EffectKind.REDUCE_BURST_COOLDOWN,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=40.0,
                    notes="once per battle",
                ),
            ),
        ),
        # Step 3 — Red Wolf
        SkillEffect(
            description=(
                "Step 3 (Red Wolf): self changes weapon — damage 51.46% of "
                "final ATK, full charge damage 250% of damage, for 10 sec. "
                "Pierce range +100% and Charge Speed +100.8% for 10 sec."
            ),
            trigger=Trigger(
                kind=TriggerKind.ON_BURST_USE,
                condition="third+ burst use of battle (Red Wolf stage)",
            ),
            effects=(
                Effect(
                    kind=EffectKind.BUFF_CHARGE_SPEED,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=100.8,
                    duration_seconds=10.0,
                ),
                Effect(
                    kind=EffectKind.BUFF_PIERCE,
                    target=Target(kind=TargetKind.SELF),
                    magnitude=1.0,
                    duration_seconds=10.0,
                    notes=(
                        "actually 'Pierce range +100%'; DSL has only "
                        "boolean Pierce — range isn't modeled"
                    ),
                ),
                # Weapon-change damage profile — encoded as a continuous
                # DEAL_DAMAGE that the simulator can apply per shot during
                # Red Wolf. Charge damage 250% multiplier isn't expressible
                # in a single Effect; lives in the notes.
                Effect(
                    kind=EffectKind.DEAL_DAMAGE,
                    target=Target(kind=TargetKind.PRIMARY_TARGET),
                    magnitude=0.5146,
                    notes=(
                        "weapon change for 10s; per-shot 51.46% of final "
                        "ATK, full charge applies 250% multiplier"
                    ),
                ),
            ),
        ),
    ),
    burst_duration_seconds=10.0,
    notes=(
        "Red Hood's three-stage burst is the heart of her kit — the "
        "encoded SkillEffects use ``ON_BURST_USE`` + a stage-specific "
        "``condition`` so the simulator can pick the right step. Several "
        "effects (Charge Speed → Charge Damage conversion, Pierce range, "
        "weapon-change profile) don't fit the current DSL cleanly; their "
        "headline magnitudes are encoded with detailed notes for the "
        "simulator to interpret."
    ),
)
register_character(_SKILL)
