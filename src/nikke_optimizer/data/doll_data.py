"""Doll (Collection Item) checkpoint data, ready for the seeder.

The doll catalog is small and fixed: 6 weapon classes × {R, SR} = 12 dolls.
Each doll has 1 (R) or 2 (SR) skills; each skill upgrades over 5 (R) or
15 (SR) phases. The user's ``OwnedCharacter.treasure_*`` rows reference
these by ``name``.

This module exposes ``DOLL_CHECKPOINTS``: a per-doll list of skills, each
with a ``checkpoints`` dict mapping ``phase → effects``. The seeder
linearly interpolates intermediate phases between adjacent checkpoints.

Skill names + trigger text + effect labels match the in-game text exactly
("Activates at the start of the battle. Damage dealt when attacking core
▲ 17.04% / DEF ▲ 37%").

Sourcing notes
--------------
- **AR Phase 15 / RL Phase 1 / RL Phase 15 / Grounding Pillar Phase 15**:
  verified from in-game capture by user + cross-checked against nikke.gg
  / Prydwen guides (May 2026).
- **All other Phase 15 magnitudes**: published in nikke.gg's Collection
  Item guide as the universal SR-cap value per weapon class.
- **Phase 1 magnitudes (non-RL)**: derived from RL's Phase 1 → Phase 15
  ratio (≈ 6×, consistent with skill level 1 → 10 scaling). Mark these
  as needing in-game verification when the user has time.
- **Phase 2-14**: linearly interpolated by ``doll_seed.interpolate``.
- **R doll Phase 5**: published as the R-cap value (≈ Phase 5 of SR
  scaled to R's lower max).
"""

from __future__ import annotations

from typing import TypedDict


class DollEffect(TypedDict, total=False):
    stat: str  # required
    magnitude: float  # required, always positive
    direction: str  # optional: "up" (default) or "down" (e.g. Damage Taken ▼)


class DollSkillSpec(TypedDict):
    skill_index: int
    name: str
    trigger: str
    checkpoints: dict[int, list[DollEffect]]


class DollSpec(TypedDict):
    weapon_class: str  # WeaponClass enum value
    rarity: str  # Rarity enum value
    name: str
    skills: list[DollSkillSpec]


# Phase-15 universal: DEF ▲ 37% (skill 1, all SR dolls)
# Phase-1 universal: DEF ▲ 25% (skill 1, all SR dolls)  -- inferred from RL example
_DEF_PHASE1 = 25.0
_DEF_PHASE15 = 37.0

# Phase-15 universal: Damage Taken ▼ 17%, Cover Max HP ▲ 30% ("Grounding Pillar")
_GROUNDING_PILLAR = {
    "name": "Grounding Pillar",
    "trigger": "Activates at the start of the battle.",
    "checkpoints": {
        # Phase 6 = SR Skill 2 unlocks (level 1)
        6: [
            {"stat": "Damage Taken", "magnitude": 6.0, "direction": "down"},
            {"stat": "Max HP of Cover", "magnitude": 12.0},
        ],
        15: [
            {"stat": "Damage Taken", "magnitude": 17.0, "direction": "down"},
            {"stat": "Max HP of Cover", "magnitude": 30.0},
        ],
    },
}


def _sr_skill1(stat_label: str, ph1_mag: float, ph15_mag: float, skill_name: str) -> DollSkillSpec:
    """Build the SR doll skill 1 spec: one weapon-class buff + universal DEF."""
    return {
        "skill_index": 1,
        "name": skill_name,
        "trigger": "Activates at the start of the battle.",
        "checkpoints": {
            1: [
                {"stat": stat_label, "magnitude": ph1_mag},
                {"stat": "DEF", "magnitude": _DEF_PHASE1},
            ],
            15: [
                {"stat": stat_label, "magnitude": ph15_mag},
                {"stat": "DEF", "magnitude": _DEF_PHASE15},
            ],
        },
    }


def _r_skill1(stat_label: str, ph1_mag: float, ph5_mag: float, skill_name: str) -> DollSkillSpec:
    """Build the R doll skill 1 spec: weapon-class buff only, caps at Phase 5."""
    return {
        "skill_index": 1,
        "name": skill_name,
        "trigger": "Activates at the start of the battle.",
        "checkpoints": {
            1: [{"stat": stat_label, "magnitude": ph1_mag}],
            5: [{"stat": stat_label, "magnitude": ph5_mag}],
        },
    }


# Per-weapon-class Phase-15 SR magnitudes from nikke.gg guide (May 2026).
# Phase 1 derived from the RL anchor (1.58% → 9.47% = 5.99×).
# AR is the user-verified anchor: Phase 15 = 17.04%, Phase 1 derived ≈ 2.84%.
DOLL_CHECKPOINTS: list[DollSpec] = [
    # ---- AR (Cooking Commander Doll Ltd.) ------------------------------
    {
        "weapon_class": "AR",
        "rarity": "SR",
        "name": "Cooking Commander Doll Ltd.",
        "skills": [
            _sr_skill1(
                "Damage dealt when attacking core",
                ph1_mag=2.84,  # derived (17.04 / 6.0)
                ph15_mag=17.04,  # user-verified
                skill_name="Gaze of Courage",
            ),
            _GROUNDING_PILLAR | {"skill_index": 2},  # type: ignore[operator]
        ],
    },
    {
        "weapon_class": "AR",
        "rarity": "R",
        "name": "Cooking Commander Doll",
        "skills": [
            _r_skill1(
                "Damage dealt when attacking core",
                ph1_mag=2.84,
                ph5_mag=6.82,  # ≈ AR-SR Phase 5 (linear lvl 1→4 of 17.04@lvl10 scale)
                skill_name="Gaze of Courage",
            ),
        ],
    },
    # ---- RL (Exercising Commander Doll Ltd.) ---------------------------
    {
        "weapon_class": "RL",
        "rarity": "SR",
        "name": "Exercising Commander Doll Ltd.",
        "skills": [
            _sr_skill1(
                "Charge Damage Multiplier",
                ph1_mag=1.58,  # user-verified
                ph15_mag=9.47,
                skill_name="Energy of Tomorrow",
            ),
            _GROUNDING_PILLAR | {"skill_index": 2},  # type: ignore[operator]
        ],
    },
    {
        "weapon_class": "RL",
        "rarity": "R",
        "name": "Exercising Commander Doll",
        "skills": [
            _r_skill1(
                "Charge Damage Multiplier",
                ph1_mag=1.58,
                ph5_mag=3.79,
                skill_name="Energy of Tomorrow",
            ),
        ],
    },
    # ---- SR / Sniper (Napping Commander Doll Ltd.) ---------------------
    # Sniper-weapon dolls share the Charge Damage buff with RL per nikke.gg.
    {
        "weapon_class": "SR",
        "rarity": "SR",
        "name": "Napping Commander Doll Ltd.",
        "skills": [
            _sr_skill1(
                "Charge Damage Multiplier",
                ph1_mag=1.58,
                ph15_mag=9.47,
                skill_name="Sweet Dreams",
            ),
            _GROUNDING_PILLAR | {"skill_index": 2},  # type: ignore[operator]
        ],
    },
    {
        "weapon_class": "SR",
        "rarity": "R",
        "name": "Napping Commander Doll",
        "skills": [
            _r_skill1(
                "Charge Damage Multiplier",
                ph1_mag=1.58,
                ph5_mag=3.79,
                skill_name="Sweet Dreams",
            ),
        ],
    },
    # ---- SG (Strolling Commander Doll Ltd.) ----------------------------
    {
        "weapon_class": "SG",
        "rarity": "SR",
        "name": "Strolling Commander Doll Ltd.",
        "skills": [
            _sr_skill1(
                "Normal Attack Damage Multiplier",
                ph1_mag=1.58,
                ph15_mag=9.46,
                skill_name="Steady Stride",
            ),
            _GROUNDING_PILLAR | {"skill_index": 2},  # type: ignore[operator]
        ],
    },
    {
        "weapon_class": "SG",
        "rarity": "R",
        "name": "Strolling Commander Doll",
        "skills": [
            _r_skill1(
                "Normal Attack Damage Multiplier",
                ph1_mag=1.58,
                ph5_mag=3.78,
                skill_name="Steady Stride",
            ),
        ],
    },
    # ---- SMG (Shopping Commander Doll Ltd.) ----------------------------
    {
        "weapon_class": "SMG",
        "rarity": "SR",
        "name": "Shopping Commander Doll Ltd.",
        "skills": [
            _sr_skill1(
                "Normal Attack Damage Multiplier",
                ph1_mag=1.58,
                ph15_mag=9.46,
                skill_name="Bargain Hunter",
            ),
            _GROUNDING_PILLAR | {"skill_index": 2},  # type: ignore[operator]
        ],
    },
    {
        "weapon_class": "SMG",
        "rarity": "R",
        "name": "Shopping Commander Doll",
        "skills": [
            _r_skill1(
                "Normal Attack Damage Multiplier",
                ph1_mag=1.58,
                ph5_mag=3.78,
                skill_name="Bargain Hunter",
            ),
        ],
    },
    # ---- MG (Studying Commander Doll Ltd.) -----------------------------
    # MG SR cap = +9.5% Max Ammo Capacity per nikke.gg.
    {
        "weapon_class": "MG",
        "rarity": "SR",
        "name": "Studying Commander Doll Ltd.",
        "skills": [
            _sr_skill1(
                "Max Ammunition Capacity",
                ph1_mag=1.58,
                ph15_mag=9.5,
                skill_name="Bookish Resolve",
            ),
            _GROUNDING_PILLAR | {"skill_index": 2},  # type: ignore[operator]
        ],
    },
    {
        "weapon_class": "MG",
        "rarity": "R",
        "name": "Studying Commander Doll",
        "skills": [
            _r_skill1(
                "Max Ammunition Capacity",
                ph1_mag=1.58,
                ph5_mag=3.80,
                skill_name="Bookish Resolve",
            ),
        ],
    },
]


def find_doll(weapon_class: str, rarity: str) -> DollSpec | None:
    """Look up the doll spec for a (weapon_class, rarity) pair.

    Returns ``None`` if the pair isn't in the catalog (e.g. SSR — that's
    the Treasure tier, not a Doll).
    """
    for doll in DOLL_CHECKPOINTS:
        if doll["weapon_class"] == weapon_class and doll["rarity"] == rarity:
            return doll
    return None
