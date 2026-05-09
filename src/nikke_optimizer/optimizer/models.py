"""Value objects shared by the optimizer pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..data.enums import BurstType, Element, Manufacturer, Rarity, WeaponClass


@dataclass(frozen=True)
class CharacterView:
    """A flattened, immutable read-model of a single Nikke.

    Combines static data from ``Character`` (element, weapon, burst type,
    role tags, ...) with the user's investment state from ``OwnedCharacter``
    (power, sync level, skill levels, equipped cubes). The optimizer only
    reads from this view — never from the SQLModel rows directly — so we can
    swap data sources later (e.g. a hypothetical "what-if" investment plan)
    without touching the search.
    """

    name: str
    rarity: Rarity
    element: Element
    weapon_class: WeaponClass
    burst_type: BurstType
    manufacturer: Optional[Manufacturer] = None
    role_tags: tuple[str, ...] = ()

    # Investment state (None when the user doesn't own this character)
    owned: bool = False
    power: int = 0
    sync_level: Optional[int] = None
    skill1_level: int = 1
    skill2_level: int = 1
    burst_skill_level: int = 1
    arena_cube_name: Optional[str] = None
    battle_cube_name: Optional[str] = None

    # Slice #134 — Treasure (Favorite Item) unlock flag from the
    # 2026-04-29+ CSV. True when the user has the SSR Treasure equipped
    # at phase ≥ 1 (so the simulator should route to the
    # ``<name> (Treasure)`` library entry when one exists).
    is_treasure_unlocked: bool = False

    # Predicted base stats from BlablaLink stat tables (pre-equipment).
    # Populated by the loader when a roledata cache hit is available.
    # Used by counter-pick scoring for unowned characters, and as a
    # consistency check against captured ``power`` for owned ones.
    predicted_base_atk: Optional[int] = None
    predicted_base_hp: Optional[int] = None
    predicted_base_def: Optional[int] = None
    predicted_power: Optional[int] = None

    @property
    def burst_position(self) -> str:
        """One of '1', '2', '3', or 'flex'.

        Treated as a string because ``BurstType`` is an enum but search code
        only cares about position bucket — the position-1/2/3 chain rule.
        ``BurstType.FLEX`` characters can fill any of the three slots.
        """
        if self.burst_type is BurstType.I:
            return "1"
        if self.burst_type is BurstType.II:
            return "2"
        if self.burst_type is BurstType.III:
            return "3"
        return "flex"


@dataclass(frozen=True)
class ScoreBreakdown:
    """Per-component contributions to a team's total score.

    Stored alongside the team so the UI can show ``Why this team?`` —
    components map to specific scoring rules and accumulate to ``total``.
    """

    burst_feasibility: float = 0.0
    power_sum: float = 0.0
    element_diversity: float = 0.0
    role_balance: float = 0.0
    synergy_pairs: float = 0.0
    investment: float = 0.0
    # Defensive components — heavily weighted in DEFENSE_WEIGHTS, lightly in
    # ATTACK_WEIGHTS. ``durability`` rewards defenders/healers/shielders;
    # ``burst_gen`` rewards burst-gen supports + B1 units that enable fast
    # full-burst entries (an attack-favorable trait).
    durability: float = 0.0
    burst_gen: float = 0.0
    # Simulator-derived components (added by ``rescore_with_evaluator``).
    # Zero when the team isn't fully encoded or rescoring wasn't applied.
    # ``team_buff_amp``    — average across the new damage-type buff fields
    #                        (TRUE_DAMAGE / ATTACK_DAMAGE / PIERCE_DAMAGE /
    #                        SHIELD_DAMAGE / CORE_DAMAGE / BURST_SKILL_DAMAGE)
    # ``vs_high_def``      — heuristic for punching through high-DEF defenders
    #                        (true-damage / pierce / shield-damage carries)
    team_buff_amp: float = 0.0
    vs_high_def: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "burst_feasibility": self.burst_feasibility,
            "power_sum": self.power_sum,
            "element_diversity": self.element_diversity,
            "role_balance": self.role_balance,
            "synergy_pairs": self.synergy_pairs,
            "investment": self.investment,
            "durability": self.durability,
            "burst_gen": self.burst_gen,
            "team_buff_amp": self.team_buff_amp,
            "vs_high_def": self.vs_high_def,
            "total": self.total,
        }


@dataclass
class TeamCandidate:
    """A scored 5-Nikke team produced by the search."""

    members: tuple[CharacterView, ...]
    breakdown: ScoreBreakdown
    notes: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.breakdown.total

    @property
    def names(self) -> list[str]:
        return [m.name for m in self.members]

    @property
    def power(self) -> int:
        return sum(m.power for m in self.members)
