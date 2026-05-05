"""Skill DSL — structured representation of NIKKE character abilities.

Each character has 3 skills: ``skill1``, ``skill2``, ``burst_skill``. Each
skill is a list of ``SkillEffect`` records, where each record bundles:

  * a ``Trigger``   — when does the effect fire? (on burst, every N hits,
                     full burst window, etc.)
  * a tuple of ``Effect``s — what happens? (buff a stat, deal damage, gain
                            burst gauge, heal, etc.)

This is **declarative**: each record describes the rule, not how to
evaluate it. The simulator consumes these to play out matches; the
optimizer uses them to detect synergies the hand-curated SYNERGY_PAIRS
table doesn't cover.

Coverage goal: encode the top ~50 PvP-relevant Nikkes by hand, then expand
outward by tier. The ``library/`` directory holds one file per encoded
character. Five are encoded today as a proof-of-concept; the
:func:`assert_well_formed` helper ensures every encoded Nikke conforms to
the DSL invariants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Element / WeaponClass / Role / ScalingSource — used by Target filters
# and Effect cross-stat scaling
# ---------------------------------------------------------------------------


class Element(str, Enum):
    """The 5-element rock-paper-scissors cycle. Mirrors `Character.element`."""

    FIRE = "fire"
    WATER = "water"
    ELECTRIC = "electric"
    IRON = "iron"
    WIND = "wind"


class WeaponClass(str, Enum):
    """Weapon type. Mirrors `Character.weapon_class`."""

    SMG = "smg"
    AR = "ar"
    SR = "sr"
    RL = "rl"
    SG = "sg"
    MG = "mg"


class Role(str, Enum):
    """Role tag. Mirrors `Character.role_tags` for the primary role."""

    ATTACKER = "attacker"
    DEFENDER = "defender"
    SUPPORTER = "supporter"


class ScalingSource(str, Enum):
    """How an Effect's magnitude scales.

    NONE (default) — the magnitude is the literal % buff on the recipient
    (e.g. ``BUFF_ATK 50`` means recipient ATK +50%).

    CASTER_ATK / CASTER_MAX_HP / CASTER_DEF — the magnitude is a flat
    bonus computed as ``caster.<stat> * magnitude / 100`` and added to
    the recipient. Used for in-game wording like
    "ATK +30.78% of caster's ATK".
    """

    NONE = "none"
    CASTER_ATK = "caster_atk"
    CASTER_MAX_HP = "caster_max_hp"
    CASTER_DEF = "caster_def"


# ---------------------------------------------------------------------------
# Triggers — when does a skill fire?
# ---------------------------------------------------------------------------


class TriggerKind(str, Enum):
    """When the associated effect activates.

    These mirror the in-game wording on Prydwen / community wikis.
    """

    ALWAYS = "always"  # passive while alive
    ON_BURST_USE = "on_burst_use"  # this Nikke's burst skill activates
    ON_ALLY_BURST_USE = "on_ally_burst_use"  # any ally uses burst skill
    ON_FULL_BURST_START = "on_full_burst_start"  # team enters Full Burst window
    ON_FULL_BURST_END = "on_full_burst_end"
    ON_HIT = "on_hit"  # every N normal attacks (use ``every_n_hits``)
    ON_KILL = "on_kill"  # this Nikke kills an enemy
    ON_BURST_GAUGE_FULL = "on_burst_gauge_full"
    ON_SHIELD_BREAK = "on_shield_break"
    ON_RELOAD = "on_reload"
    ON_LAST_AMMO = "on_last_ammo"  # firing the final round of magazine
    ON_DAMAGE_TAKEN = "on_damage_taken"
    ON_TIMER = "on_timer"  # every N seconds (use ``cooldown_seconds``)
    ON_BATTLE_START = "on_battle_start"
    CONDITIONAL = "conditional"  # use ``condition`` for a free-form predicate


@dataclass(frozen=True)
class Trigger:
    kind: TriggerKind
    every_n_hits: int = 0  # for ON_HIT — how many hits between activations
    cooldown_seconds: float = 0.0  # for ON_TIMER and rate-limited triggers
    condition: str = ""  # free-form predicate ("when target HP < 50%")
    notes: str = ""


# ---------------------------------------------------------------------------
# Targets — who is affected?
# ---------------------------------------------------------------------------


class TargetKind(str, Enum):
    SELF = "self"
    ALL_ALLIES = "all_allies"
    NEAREST_ALLIES = "nearest_allies"  # ``count`` adjacent allies (e.g. Liter)
    ALLY_HIGHEST_ATK = "ally_highest_atk"
    ALLY_LOWEST_HP = "ally_lowest_hp"
    BURST_USER = "burst_user"  # the ally currently bursting
    ALL_ENEMIES = "all_enemies"
    ENEMY_HIGHEST_HP = "enemy_highest_hp"
    ENEMY_LOWEST_HP = "enemy_lowest_hp"
    ENEMY_FRONT = "enemy_front"  # taunters / nearest
    ENEMIES_RANDOM_K = "enemies_random_k"  # K random enemies (use ``count``)
    PRIMARY_TARGET = "primary_target"  # the Nikke's current shooting target


@dataclass(frozen=True)
class Target:
    kind: TargetKind
    count: int = 1  # for NEAREST_ALLIES, ENEMIES_RANDOM_K, etc.
    # Filter dimensions — restrict the resolved target set further.
    # Stored on the DSL so encoded effects can express "Water-code allies",
    # "RL allies", "Defender allies", etc. The static evaluator currently
    # records but doesn't enforce these (Character-data threading TBD); the
    # eventual simulator will use them for accurate target resolution.
    filter_element: Optional[Element] = None
    filter_weapon: Optional[WeaponClass] = None
    filter_role: Optional[Role] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Effects — what actually happens?
# ---------------------------------------------------------------------------


class EffectKind(str, Enum):
    BUFF_ATK = "buff_atk"
    BUFF_HP = "buff_hp"
    BUFF_DEFENSE = "buff_defense"
    BUFF_CRIT_RATE = "buff_crit_rate"
    BUFF_CRIT_DAMAGE = "buff_crit_damage"
    BUFF_CHARGE_DAMAGE = "buff_charge_damage"
    BUFF_CHARGE_SPEED = "buff_charge_speed"
    BUFF_HIT_RATE = "buff_hit_rate"
    BUFF_ELEMENT_DAMAGE = "buff_element_damage"
    BUFF_AMMO_CAPACITY = "buff_ammo_capacity"
    BUFF_RELOAD_SPEED = "buff_reload_speed"
    BUFF_PIERCE = "buff_pierce"
    # Damage-type-specific buffs — distinct from BUFF_ATK. In-game these
    # multiply only their named damage type, not raw ATK.
    BUFF_ATTACK_DAMAGE = "buff_attack_damage"  # generic "Attack Damage +X%"
    BUFF_TRUE_DAMAGE = "buff_true_damage"  # multiplies true-damage instances
    BUFF_PIERCE_DAMAGE = "buff_pierce_damage"  # multiplies Pierce damage
    BUFF_SHIELD_DAMAGE = "buff_shield_damage"  # damage-to-shield amplifier
    BUFF_CORE_DAMAGE = "buff_core_damage"  # core-hit damage amplifier
    BUFF_DAMAGE_TO_PARTS = "buff_damage_to_parts"  # part-destruction amp
    BUFF_SUSTAINED_DAMAGE = "buff_sustained_damage"  # DOT amplifier
    BUFF_BURST_SKILL_DAMAGE = "buff_burst_skill_damage"  # burst-skill amp
    DEAL_DAMAGE = "deal_damage"  # ``magnitude`` × ATK as damage
    DEAL_TRUE_DAMAGE = "deal_true_damage"  # bypasses defense
    HEAL_HP_FLAT = "heal_hp_flat"  # magnitude as % of caster max HP
    HEAL_PER_SECOND = "heal_per_second"
    GRANT_SHIELD = "grant_shield"  # magnitude as % of caster max HP
    TAUNT = "taunt"
    GAIN_BURST_GAUGE = "gain_burst_gauge"  # magnitude as % of full gauge
    REDUCE_BURST_COOLDOWN = "reduce_burst_cooldown"
    CLEANSE = "cleanse"
    DEBUFF_DEFENSE = "debuff_defense"  # magnitude as % reduction
    DEBUFF_ATK = "debuff_atk"
    INFLICT_BURN = "inflict_burn"


@dataclass(frozen=True)
class Effect:
    kind: EffectKind
    target: Target
    magnitude: float = 0.0
    duration_seconds: float = 0.0  # 0 = instant / permanent
    stacks_max: int = 1
    # Cross-stat scaling — when set, ``magnitude`` is interpreted as
    # ``caster.<stat> * magnitude / 100`` and added as a flat bonus to
    # the recipient (rather than a % buff). See ``ScalingSource``.
    scaling_source: ScalingSource = ScalingSource.NONE
    notes: str = ""


@dataclass(frozen=True)
class SkillEffect:
    """One trigger paired with one or more effects.

    A single skill (e.g. Crown's burst) can fire multiple effects from one
    trigger — the tuple groups them.
    """

    trigger: Trigger
    effects: tuple[Effect, ...]
    description: str = ""  # human-readable summary, optional


# ---------------------------------------------------------------------------
# Character-level container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharacterSkillSet:
    """Encoded skill set for a single Nikke at max level."""

    character_name: str
    skill1: tuple[SkillEffect, ...]
    skill2: tuple[SkillEffect, ...]
    burst_skill: tuple[SkillEffect, ...]
    burst_duration_seconds: float = 10.0  # Full Burst window length
    skill_levels_assumed: int = 10
    notes: str = ""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class DSLValidationError(ValueError):
    """A hand-encoded character violates DSL invariants."""


def assert_well_formed(skills: CharacterSkillSet) -> None:
    """Raise :class:`DSLValidationError` if any rule is malformed.

    Run on every entry registered with :func:`register_character` so a
    typo (e.g. magnitude on a HEAL effect that lacks ``duration_seconds``)
    is caught at import time, not at simulator runtime.
    """
    if not skills.character_name.strip():
        raise DSLValidationError("character_name must be non-empty")
    if skills.burst_duration_seconds <= 0:
        raise DSLValidationError("burst_duration_seconds must be > 0")
    for slot_name in ("skill1", "skill2", "burst_skill"):
        slot: tuple[SkillEffect, ...] = getattr(skills, slot_name)
        if not isinstance(slot, tuple):
            raise DSLValidationError(f"{slot_name} must be a tuple of SkillEffects")
        for i, se in enumerate(slot):
            if not isinstance(se, SkillEffect):
                raise DSLValidationError(
                    f"{slot_name}[{i}] is not a SkillEffect"
                )
            if not se.effects:
                raise DSLValidationError(
                    f"{slot_name}[{i}] has no effects"
                )
            for j, eff in enumerate(se.effects):
                if not isinstance(eff, Effect):
                    raise DSLValidationError(
                        f"{slot_name}[{i}].effects[{j}] is not an Effect"
                    )
                if eff.kind in {
                    EffectKind.BUFF_ATK,
                    EffectKind.BUFF_DEFENSE,
                    EffectKind.BUFF_CRIT_RATE,
                    EffectKind.BUFF_CRIT_DAMAGE,
                    EffectKind.BUFF_CHARGE_DAMAGE,
                    EffectKind.BUFF_CHARGE_SPEED,
                    EffectKind.BUFF_ELEMENT_DAMAGE,
                    EffectKind.BUFF_AMMO_CAPACITY,
                    EffectKind.BUFF_HIT_RATE,
                    EffectKind.BUFF_PIERCE,
                    EffectKind.BUFF_ATTACK_DAMAGE,
                    EffectKind.BUFF_TRUE_DAMAGE,
                    EffectKind.BUFF_PIERCE_DAMAGE,
                    EffectKind.BUFF_SHIELD_DAMAGE,
                    EffectKind.BUFF_CORE_DAMAGE,
                    EffectKind.BUFF_DAMAGE_TO_PARTS,
                    EffectKind.BUFF_SUSTAINED_DAMAGE,
                    EffectKind.BUFF_BURST_SKILL_DAMAGE,
                    EffectKind.GRANT_SHIELD,
                    EffectKind.DEBUFF_ATK,
                    EffectKind.DEBUFF_DEFENSE,
                } and eff.duration_seconds <= 0:
                    raise DSLValidationError(
                        f"{slot_name}[{i}].effects[{j}] {eff.kind.value} "
                        "needs a positive duration_seconds"
                    )
                if eff.magnitude < 0 and eff.kind not in {
                    EffectKind.DEBUFF_ATK,
                    EffectKind.DEBUFF_DEFENSE,
                }:
                    raise DSLValidationError(
                        f"{slot_name}[{i}].effects[{j}] has negative "
                        "magnitude — debuffs should use the dedicated "
                        "DEBUFF_* effect kinds"
                    )
