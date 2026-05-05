"""Synergy table coverage audit.

The hand-curated SYNERGY_PAIRS table in ``scoring.py`` covers the
established meta cores (Crown comp, defense trinity, Tia/Naga, etc.).
As new characters get encoded, the synergy table can lag behind — a
character may have a real PvP-relevant pairing that isn't represented
in the table, so the optimizer doesn't credit teams that include her.

This module surfaces the gap by counting how many synergy entries
each encoded character appears in, and lists the under-represented
ones so the maintainer can decide what to add.

Usage:

    from nikke_copilot.optimizer.synergy_audit import audit_synergy_coverage
    from nikke_copilot.optimizer.scoring import SYNERGY_PAIRS
    from nikke_copilot.simulator.registry import all_encoded_names

    report = audit_synergy_coverage(all_encoded_names(), SYNERGY_PAIRS)
    for tier, names in report.tiers_by_coverage.items():
        ...
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class SynergyCoverageReport:
    """Per-character synergy-pair count, grouped by tier."""

    counts: dict[str, int] = field(default_factory=dict)
    # 0 = no synergy pair entries; 1 = a single pair; 2 = two pairs; ...
    # Common partners (Crown, Liter, Modernia) tend to top this list.
    tiers_by_coverage: dict[int, list[str]] = field(default_factory=dict)

    @property
    def under_represented(self) -> list[str]:
        """Encoded characters appearing in 0 or 1 synergy pair."""
        return sorted(
            name for name, n in self.counts.items() if n <= 1
        )


def audit_synergy_coverage(
    encoded_names: Iterable[str],
    synergy_pairs: dict[frozenset[str], float],
) -> SynergyCoverageReport:
    """Count how many synergy entries each encoded character appears in.

    Pairs with bonus value of 0 (e.g., the skin-variant uniqueness
    placeholder) are excluded — they document constraints rather than
    actual synergies.
    """
    encoded = set(encoded_names)
    counts: dict[str, int] = {n: 0 for n in encoded}
    for pair, bonus in synergy_pairs.items():
        if bonus <= 0:
            continue
        for name in pair:
            if name in counts:
                counts[name] += 1
    tiers: dict[int, list[str]] = defaultdict(list)
    for name, n in counts.items():
        tiers[n].append(name)
    for n in tiers:
        tiers[n].sort()
    return SynergyCoverageReport(
        counts=counts,
        tiers_by_coverage=dict(sorted(tiers.items())),
    )
