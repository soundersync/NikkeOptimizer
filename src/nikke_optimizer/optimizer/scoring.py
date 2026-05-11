"""Heuristic scoring — sum of weighted soft components.

Component summary:

  * ``power_sum``     log-scaled total combat power
  * ``element_div``   bonus for spreading elements across the team
  * ``role_balance``  bonus for an attacker / support / defender / healer mix
  * ``synergy_pairs`` bonus for known meta pairs (Crown+RH, Liter+B3, ...)
  * ``investment``    bonus for high skill levels + arena cubes equipped
                      (under-invested Nikkes are also vetoed by
                      ``has_minimum_investment`` upstream — this scorer
                      fine-tunes the ranking among above-floor Nikkes)
  * ``durability``    bonus for defender / shielder / healer count — heavy on
                      DEFENSE_WEIGHTS, light on ATTACK_WEIGHTS
  * ``burst_gen``     bonus for Burst CD Reduction tags + B1 supports — fast
                      full-burst entries are an attack-favorable trait

Hard burst-chain feasibility is enforced upstream by ``constraints``;
``score_team`` returns ``None`` for invalid teams.

Three weight presets cover the standard PvP roles:

  * :data:`ATTACK_WEIGHTS`   — favors burst-gen and synergy stacking
  * :data:`DEFENSE_WEIGHTS`  — favors durability / sustain
  * :data:`BALANCED_WEIGHTS` — Champions Arena (each team plays both roles
                              via 50/50 coin flip)

The web UI / CLI accept a ``--role`` flag that maps to one of these.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Literal, Optional

from .constraints import is_valid_team
from .models import CharacterView, ScoreBreakdown, TeamCandidate


# Hand-curated synergy pairs: (name_a, name_b) → bonus. Order doesn't matter.
# Sourced from current Prydwen meta archetypes (snapshot 2025-01) — extend
# as new comps emerge. Keys are stored as frozenset(pair) so lookup is
# order-insensitive.
SYNERGY_PAIRS: dict[frozenset[str], float] = {
    # ------------------------------------------------------------------
    # Crown synergies — universal B2 buffer; pairs with every B3 attacker
    # ------------------------------------------------------------------
    frozenset(("Crown", "Red Hood")): 8.0,
    frozenset(("Crown", "Modernia")): 7.0,
    frozenset(("Crown", "Snow White: Heavy Arms")): 7.0,
    frozenset(("Crown", "Scarlet: Black Shadow")): 7.0,
    frozenset(("Crown", "Asuka Shikinami Langley")): 6.0,
    frozenset(("Crown", "Alice")): 6.0,
    frozenset(("Crown", "Rapi: Red Hood")): 6.0,
    frozenset(("Crown", "Ein")): 5.0,
    frozenset(("Crown", "Anis: Sparkling Summer")): 5.0,
    frozenset(("Crown", "Cinderella")): 5.0,
    frozenset(("Crown", "Naga")): 5.0,  # Crown-Naga comp

    # ------------------------------------------------------------------
    # Liter synergies — canonical B1 burst-gen support, near-universal
    # ------------------------------------------------------------------
    frozenset(("Liter", "Red Hood")): 5.0,
    frozenset(("Liter", "Modernia")): 5.0,
    frozenset(("Liter", "Snow White: Heavy Arms")): 5.0,
    frozenset(("Liter", "Scarlet: Black Shadow")): 4.0,
    frozenset(("Liter", "Alice")): 4.0,
    frozenset(("Liter", "Rapi: Red Hood")): 4.0,
    frozenset(("Liter", "Asuka Shikinami Langley")): 4.0,

    # ------------------------------------------------------------------
    # Tia + Naga — the "Tia/Naga burst gen" core (the second-best B1+B2
    # support pair after Liter/Crown)
    # ------------------------------------------------------------------
    frozenset(("Tia", "Naga")): 5.0,
    frozenset(("Naga", "Scarlet: Black Shadow")): 6.0,
    frozenset(("Naga", "Modernia")): 4.0,
    frozenset(("Tia", "Scarlet: Black Shadow")): 5.0,
    frozenset(("Tia", "Modernia")): 4.0,
    frozenset(("Tia", "Red Hood")): 4.0,

    # ------------------------------------------------------------------
    # Dorothy 2-1-2 comps — Dorothy is a B1 buffer that adds a second
    # support slot, freeing the third slot for an extra DPS
    # ------------------------------------------------------------------
    frozenset(("Dorothy", "Crown")): 5.0,
    frozenset(("Dorothy", "Modernia")): 5.0,
    frozenset(("Dorothy", "Red Hood")): 4.0,
    frozenset(("Dorothy", "Snow White: Heavy Arms")): 5.0,
    frozenset(("Dorothy: Serendipity", "Crown")): 4.0,

    # ------------------------------------------------------------------
    # Defense stall comps — Helm/Centi/Blanc/Noah trinity. The bonus is
    # smaller than offensive pairs because defense scoring already rewards
    # durability heavily; we don't want to double-count.
    # ------------------------------------------------------------------
    frozenset(("Helm", "Centi")): 4.0,
    frozenset(("Helm", "Blanc")): 4.0,
    frozenset(("Centi", "Blanc")): 4.0,
    frozenset(("Helm", "Noah")): 4.0,
    frozenset(("Centi", "Noah")): 4.0,
    frozenset(("Blanc", "Noah")): 4.0,
    frozenset(("Bay", "Helm")): 3.0,
    frozenset(("Anchor", "Helm")): 3.0,
    frozenset(("Anchor", "Centi")): 3.0,

    # ------------------------------------------------------------------
    # Helm + carry pairings — Helm shields enable her shielded attacker
    # to stay alive through nukes; she's both a defender AND a setup
    # piece for hyper-DPS attack comps.
    # ------------------------------------------------------------------
    frozenset(("Helm", "Modernia")): 5.0,
    frozenset(("Helm", "Snow White: Heavy Arms")): 4.0,
    frozenset(("Helm", "Red Hood")): 4.0,
    frozenset(("Helm", "Crown")): 4.0,
    frozenset(("Helm", "Liter")): 3.0,
    frozenset(("Helm", "Scarlet: Black Shadow")): 4.0,
    frozenset(("Helm: Aquamarine", "Modernia")): 5.0,
    frozenset(("Helm: Aquamarine", "Crown")): 4.0,

    # ------------------------------------------------------------------
    # Centi/Blanc + carry pairings
    # ------------------------------------------------------------------
    frozenset(("Centi", "Modernia")): 4.0,
    frozenset(("Centi", "Red Hood")): 3.0,
    frozenset(("Centi", "Crown")): 4.0,
    frozenset(("Blanc", "Modernia")): 4.0,
    frozenset(("Blanc", "Red Hood")): 4.0,
    frozenset(("Blanc", "Crown")): 4.0,
    frozenset(("Blanc", "Snow White: Heavy Arms")): 4.0,
    frozenset(("Noah", "Modernia")): 4.0,
    frozenset(("Noah", "Crown")): 4.0,
    frozenset(("Noah", "Red Hood")): 3.0,

    # ------------------------------------------------------------------
    # Anti-defense / anti-shield (counters stall comps)
    # ------------------------------------------------------------------
    frozenset(("D: Killer Wife", "Ade: Agent Bunny")): 4.0,
    frozenset(("D: Killer Wife", "Crown")): 5.0,

    # ------------------------------------------------------------------
    # Anis: Star (B1 burst-gen + buffer + healer) — slots into many
    # carry comps as an alternative to Liter.
    # ------------------------------------------------------------------
    frozenset(("Anis: Star", "Modernia")): 4.0,
    frozenset(("Anis: Star", "Red Hood")): 4.0,
    frozenset(("Anis: Star", "Snow White: Heavy Arms")): 4.0,
    frozenset(("Anis: Star", "Crown")): 4.0,

    # ------------------------------------------------------------------
    # Asuka — flexible B3 attacker with self-buffs that pairs broadly
    # ------------------------------------------------------------------
    frozenset(("Asuka Shikinami Langley", "Liter")): 4.0,
    frozenset(("Asuka Shikinami Langley", "Tia")): 4.0,
    frozenset(("Asuka Shikinami Langley", "Naga")): 4.0,
    frozenset(("Asuka Shikinami Langley", "Modernia")): 4.0,

    # ------------------------------------------------------------------
    # Anti-shield extras (for breaking Helm-led defense walls)
    # ------------------------------------------------------------------
    frozenset(("D: Killer Wife", "Liter")): 4.0,
    frozenset(("D: Killer Wife", "Modernia")): 4.0,
    frozenset(("D: Killer Wife", "Snow White: Heavy Arms")): 4.0,

    # ------------------------------------------------------------------
    # Misc proven pairings
    # ------------------------------------------------------------------
    frozenset(("Volume", "Crown")): 4.0,
    frozenset(("Anis: Sparkling Summer", "Modernia")): 5.0,
    frozenset(("Sakura", "Crown")): 4.0,
    frozenset(("Mast: Romantic Maid", "Modernia")): 4.0,
    frozenset(("Anchor: Innocent Maid", "Crown")): 3.0,
    frozenset(("Anchor: Innocent Maid", "Modernia")): 3.0,
    frozenset(("Rouge", "Crown")): 4.0,
    frozenset(("Rapunzel: Pure Grace", "Modernia")): 4.0,
    frozenset(("Rapunzel: Pure Grace", "Red Hood")): 3.0,
    frozenset(("Mary: Bay Goddess", "Crown")): 3.0,

    # ------------------------------------------------------------------
    # Slice #113 — pairings for newly encoded characters (DSL slices
    # #111+#112). Bonuses are conservative (3-5) since meta validation
    # comes from match-outcome capture, not from this table directly.
    # ------------------------------------------------------------------
    # Vesti: Tactical Upgrade — Fire RL B3 true-damage carry
    frozenset(("Vesti: Tactical Upgrade", "Crown")): 4.0,
    frozenset(("Vesti: Tactical Upgrade", "Liter")): 4.0,
    frozenset(("Vesti: Tactical Upgrade", "Helm")): 3.0,  # anti-shield + true dmg
    frozenset(("Vesti: Tactical Upgrade", "D: Killer Wife")): 4.0,  # DEF-bypass stack

    # Ade: Agent Bunny — Iron SR B2 pierce buffer
    frozenset(("Ade: Agent Bunny", "Maxwell")): 4.0,
    frozenset(("Ade: Agent Bunny", "Alice")): 4.0,
    frozenset(("Ade: Agent Bunny", "Snow White: Heavy Arms")): 4.0,
    frozenset(("Ade: Agent Bunny", "Liberalio")): 4.0,
    frozenset(("Ade: Agent Bunny", "Crown")): 4.0,

    # Liberalio — Wind SR B3 single-target carry
    frozenset(("Liberalio", "Crown")): 4.0,
    frozenset(("Liberalio", "Liter")): 3.0,
    frozenset(("Liberalio", "Tia")): 3.0,

    # Raven — Iron RL B3 sustained-damage carry
    frozenset(("Raven", "Crown")): 4.0,
    frozenset(("Raven", "Tia")): 3.0,
    frozenset(("Raven", "Naga")): 3.0,

    # Ludmilla: Winter Owner — Water MG B3 sustained DPS
    frozenset(("Ludmilla: Winter Owner", "Crown")): 4.0,
    frozenset(("Ludmilla: Winter Owner", "Liter")): 4.0,
    frozenset(("Ludmilla: Winter Owner", "Tia")): 3.0,

    # Noir — Wind SG B3 SG-comp finisher
    frozenset(("Noir", "Tove")): 4.0,
    frozenset(("Noir", "Anis: Sparkling Summer")): 4.0,
    frozenset(("Noir", "Leona")): 3.0,

    # Tove — Water AR B1 SG-comp support
    frozenset(("Tove", "Anis: Sparkling Summer")): 4.0,
    frozenset(("Tove", "Leona")): 4.0,

    # Quency: Escape Queen — Water SMG B3 distributed-damage carry
    frozenset(("Quency: Escape Queen", "Crown")): 4.0,
    frozenset(("Quency: Escape Queen", "Liter")): 3.0,

    # Little Mermaid (Siren) — Wind SMG B1 burst-gen
    frozenset(("Little Mermaid (Siren)", "Modernia")): 4.0,
    frozenset(("Little Mermaid (Siren)", "Crown")): 3.0,

    # Grave — Fire AR B2 pierce-damage support
    frozenset(("Grave", "Maxwell")): 4.0,
    frozenset(("Grave", "Snow White: Heavy Arms")): 3.0,
    frozenset(("Grave", "Liberalio")): 3.0,

    # Moran / Noise — defensive B1 niche
    frozenset(("Moran", "Helm")): 3.0,
    frozenset(("Noise", "Helm")): 3.0,
    frozenset(("Noise", "Centi")): 3.0,

    # ------------------------------------------------------------------
    # Slice #113 — fill gaps for previously encoded but under-represented
    # B3 attackers. Crown is the universal pair; we add Liter / Tia /
    # Naga where the synergy is mechanically sensible.
    # ------------------------------------------------------------------
    frozenset(("Maxwell", "Crown")): 5.0,
    frozenset(("Maxwell", "Liter")): 4.0,
    frozenset(("Maxwell", "Tia")): 4.0,
    frozenset(("Cinderella", "Liter")): 4.0,
    frozenset(("Cinderella", "Tia")): 3.0,
    frozenset(("A2", "Crown")): 4.0,
    frozenset(("A2", "Liter")): 3.0,
    frozenset(("2B", "Crown")): 4.0,
    frozenset(("Phantom", "Crown")): 4.0,
    frozenset(("Phantom", "Liter")): 3.0,
    frozenset(("Trony", "Crown")): 3.0,
    frozenset(("Ein", "Crown")): 4.0,
    frozenset(("Mihara", "Crown")): 4.0,
    frozenset(("Mihara", "Liter")): 3.0,

    # ------------------------------------------------------------------
    # Slice #117 — synergy expansion round 2. More pairings for meta-
    # relevant under-represented chars. Bonuses 3-4 (conservative).
    # ------------------------------------------------------------------
    # Asuka Shikinami Langley: Wille (Iron AR B3) — collab carry.
    frozenset(("Asuka Shikinami Langley: Wille", "Crown")): 4.0,
    frozenset(("Asuka Shikinami Langley: Wille", "Liter")): 3.0,
    # Mihara: Bonding Chain (B3 alt)
    frozenset(("Mihara: Bonding Chain", "Crown")): 4.0,
    frozenset(("Mihara: Bonding Chain", "Liter")): 3.0,
    # Maiden: Ice Rose (Water SMG B3 — MP gauge carry)
    frozenset(("Maiden: Ice Rose", "Crown")): 4.0,
    frozenset(("Maiden: Ice Rose", "Liter")): 3.0,
    # Chisato Nishikigi (Lycoris collab)
    frozenset(("Chisato Nishikigi", "Crown")): 4.0,
    frozenset(("Chisato Nishikigi", "Takina Inoue")): 4.0,
    frozenset(("Chisato Nishikigi", "Liter")): 3.0,
    # Takina Inoue (Lycoris — true damage)
    frozenset(("Takina Inoue", "Crown")): 3.0,
    # Ada Wong / Jill Valentine / Claire Redfield (RE collab)
    frozenset(("Jill Valentine", "Crown")): 4.0,
    frozenset(("Jill Valentine", "Liter")): 3.0,
    frozenset(("Ada Wong", "Crown")): 3.0,
    frozenset(("Ada Wong", "Liter")): 3.0,
    # Soldier OW — more pairings
    frozenset(("Soldier OW", "Modernia")): 3.0,
    frozenset(("Soldier OW", "Snow White: Heavy Arms")): 3.0,
    # Rei Ayanami (Tentative Name) — Eva collab support
    frozenset(("Rei Ayanami (Tentative Name)", "Crown")): 3.0,
    frozenset(("Rei Ayanami (Tentative Name)", "Asuka Shikinami Langley")): 4.0,
    # Sakura: Bloom in Summer (B1 alt support)
    frozenset(("Sakura: Bloom in Summer", "Modernia")): 3.0,
    frozenset(("Sakura: Bloom in Summer", "Crown")): 3.0,
    # Snow White (base, AR B3 carry)
    frozenset(("Snow White", "Crown")): 3.0,
    frozenset(("Snow White", "Liter")): 3.0,
    # Rapi (base) — anti-Pierce / support
    frozenset(("Rapi", "Crown")): 3.0,
    # Rapunzel (base healer)
    frozenset(("Rapunzel", "Modernia")): 3.0,
    # Privaty: Unkind Maid — burst carry
    frozenset(("Privaty: Unkind Maid", "Crown")): 4.0,
    frozenset(("Privaty: Unkind Maid", "Liter")): 3.0,
    # D (Killer Wife alt — base D)
    frozenset(("D", "Crown")): 3.0,
    # Drake (base, Treasure variant separately)
    frozenset(("Drake", "Crown")): 3.0,
    frozenset(("Drake (Treasure)", "Crown")): 3.0,
    # Treasure form pairings
    frozenset(("Bay (Treasure)", "Helm")): 3.0,
    frozenset(("Bay (Treasure)", "Crown")): 3.0,
    frozenset(("Centi (Treasure)", "Helm")): 3.0,
    frozenset(("Helm (Treasure)", "Modernia")): 3.0,
    # Pepper (B1 healer/burst-gen)
    frozenset(("Pepper", "Modernia")): 3.0,
    frozenset(("Pepper", "Crown")): 3.0,
    # Dorothy: Serendipity (B1 alt) — more pairings
    frozenset(("Dorothy: Serendipity", "Modernia")): 4.0,
    frozenset(("Dorothy: Serendipity", "Snow White: Heavy Arms")): 3.0,
    # Folkwang (Iron, B2/Healer)
    frozenset(("Folkwang", "Crown")): 3.0,
    # Marciana / Quency / Ade — support tier
    frozenset(("Marciana", "Crown")): 3.0,
    frozenset(("Quency", "Crown")): 3.0,
    frozenset(("Ade", "Crown")): 3.0,

    # ------------------------------------------------------------------
    # Slice #119 — synergy expansion round 3. Cover the remaining tail
    # of meta-relevant chars + Lycoris / niche supports.
    # ------------------------------------------------------------------
    frozenset(("Anis: Star", "Liter")): 3.0,
    frozenset(("Aria", "Crown")): 3.0,
    frozenset(("Avistar", "Crown")): 3.0,
    frozenset(("Belorta", "Crown")): 3.0,
    frozenset(("Bready", "Crown")): 3.0,
    frozenset(("Brid", "Crown")): 3.0,
    frozenset(("Brid: Silent Track", "Crown")): 3.0,
    frozenset(("Chime", "Crown")): 3.0,
    frozenset(("Crow", "Crown")): 3.0,
    frozenset(("Crust", "Helm")): 3.0,
    frozenset(("Eve", "Crown")): 3.0,
    frozenset(("Exia", "Crown")): 3.0,
    frozenset(("Frima", "Crown")): 3.0,
    frozenset(("Jackal", "Modernia")): 3.0,
    frozenset(("Jackal", "Snow White: Heavy Arms")): 3.0,
    frozenset(("Kilo", "Crown")): 3.0,
    frozenset(("Laplace", "Crown")): 3.0,
    frozenset(("Makima", "Crown")): 3.0,
    frozenset(("Makima", "Liter")): 3.0,
    frozenset(("Misato Katsuragi", "Crown")): 3.0,
    frozenset(("Mast: Romantic Maid", "Crown")): 3.0,
    frozenset(("Nayuta", "Crown")): 3.0,
    frozenset(("Nihilister", "Crown")): 4.0,
    frozenset(("Nihilister", "Liter")): 3.0,
    frozenset(("Pascal", "Crown")): 3.0,
    frozenset(("Power", "Crown")): 3.0,
    frozenset(("Quiry", "Crown")): 3.0,
    frozenset(("Rem", "Crown")): 3.0,
    frozenset(("Sin", "Crown")): 3.0,
    frozenset(("Snow Crane", "Crown")): 3.0,
    frozenset(("Yulha", "Crown")): 3.0,
    frozenset(("Diesel", "Crown")): 3.0,
    frozenset(("Diesel: Winter Sweets", "Crown")): 3.0,
    frozenset(("Cocoa", "Crown")): 3.0,
    frozenset(("Cocoa", "Modernia")): 3.0,
    frozenset(("Anne: Miracle Fairy", "Crown")): 3.0,
    frozenset(("Alice: Wonderland Bunny", "Crown")): 3.0,
    frozenset(("Mari Makinami Illustrious", "Crown")): 3.0,
    frozenset(("Mari Makinami Illustrious", "Asuka Shikinami Langley")): 4.0,
    frozenset(("Soda: Twinkling Bunny", "Crown")): 3.0,
    frozenset(("Rosanna: Chic Ocean", "Crown")): 3.0,
    frozenset(("Elegg: Boom and Shock", "Crown")): 3.0,
    frozenset(("Guillotine: Winter Slayer", "Crown")): 3.0,
    frozenset(("Emilia", "Crown")): 3.0,
    frozenset(("Emma: Tactical Upgrade", "Crown")): 3.0,
    frozenset(("Ade: Agent Bunny", "Liter")): 3.0,
    frozenset(("Volume", "Modernia")): 3.0,
    frozenset(("Mary: Bay Goddess", "Modernia")): 3.0,
    frozenset(("Admi", "Crown")): 3.0,
    frozenset(("Trony", "Liter")): 3.0,
    frozenset(("Anis", "Modernia")): 3.0,
    frozenset(("Soda", "Modernia")): 3.0,
    frozenset(("Privaty", "Modernia")): 3.0,
    frozenset(("Sakura", "Modernia")): 3.0,

    # Slice #120 — add pairings for the round 4 encodings (Trina, Mast,
    # Julia, Elegg, Maiden, Milk: Blooming Bunny) so they're not in the
    # under-represented bucket.
    frozenset(("Trina", "Crown")): 3.0,
    frozenset(("Trina", "Modernia")): 3.0,
    frozenset(("Mast", "Crown")): 3.0,
    frozenset(("Mast", "Modernia")): 3.0,
    frozenset(("Julia", "Crown")): 3.0,
    frozenset(("Julia", "Liter")): 3.0,
    frozenset(("Elegg", "Crown")): 3.0,
    frozenset(("Maiden", "Crown")): 3.0,
    frozenset(("Milk: Blooming Bunny", "Crown")): 4.0,
    frozenset(("Milk: Blooming Bunny", "Liter")): 3.0,

    # Slice #124 — pairings for round-5 encodings (Epinel, Soline:FT,
    # Arcana, Guillotine, Harran, Neon: Blue Ocean) plus more for the
    # remaining under-represented chars.
    frozenset(("Epinel", "Crown")): 3.0,
    frozenset(("Epinel", "Liter")): 3.0,
    frozenset(("Soline: Frost Ticket", "Helm")): 3.0,
    frozenset(("Soline: Frost Ticket", "Centi")): 3.0,
    frozenset(("Arcana", "Modernia")): 4.0,
    frozenset(("Arcana", "Snow White: Heavy Arms")): 3.0,
    frozenset(("Arcana", "Crown")): 3.0,
    frozenset(("Guillotine", "Crown")): 3.0,
    frozenset(("Guillotine", "Liter")): 3.0,
    frozenset(("Harran", "Crown")): 3.0,
    frozenset(("Neon: Blue Ocean", "Crown")): 3.0,
    frozenset(("Neon: Blue Ocean", "Liter")): 3.0,
    # Fill more remaining gaps from the under-represented list.
    frozenset(("Soldier OW", "Crown")): 3.0,
    frozenset(("Mast: Romantic Maid", "Liter")): 3.0,
    frozenset(("Sakura", "Liter")): 3.0,
    frozenset(("Volume", "Liter")): 3.0,
    frozenset(("Marciana", "Modernia")): 3.0,
    frozenset(("Quency", "Modernia")): 3.0,
    frozenset(("Ade", "Modernia")): 3.0,
    frozenset(("Folkwang", "Modernia")): 3.0,
    frozenset(("Pepper", "Liter")): 3.0,
    frozenset(("Bay", "Modernia")): 3.0,
    frozenset(("Anchor", "Modernia")): 3.0,
    frozenset(("Trony", "Modernia")): 3.0,
    frozenset(("Anis: Star", "Modernia")): 3.0,

    # Slice #125 — pairings for round-6 encodings.
    frozenset(("Clay", "Crown")): 4.0,
    frozenset(("Clay", "Modernia")): 3.0,
    frozenset(("Mary", "Crown")): 3.0,
    frozenset(("Yan", "Crown")): 3.0,
    frozenset(("Privaty (Treasure)", "Crown")): 4.0,
    frozenset(("Privaty (Treasure)", "Liter")): 3.0,
    frozenset(("Mica: Snow Buddy", "Modernia")): 4.0,
    frozenset(("Mica: Snow Buddy", "Crown")): 3.0,
    frozenset(("Neon: Vision Eye", "Crown")): 3.0,
    frozenset(("Neon: Blue Ocean", "Modernia")): 3.0,
    # More gap fills from under-represented.
    frozenset(("Trony", "Tia")): 3.0,
    frozenset(("Eve", "Modernia")): 3.0,
    frozenset(("Frima", "Liter")): 3.0,
    frozenset(("Bay (Treasure)", "Modernia")): 3.0,
    frozenset(("Centi (Treasure)", "Modernia")): 3.0,
    frozenset(("Drake", "Modernia")): 3.0,
    frozenset(("Drake (Treasure)", "Modernia")): 3.0,
    frozenset(("Helm (Treasure)", "Crown")): 3.0,
    frozenset(("Helm: Aquamarine", "Snow White: Heavy Arms")): 3.0,
    frozenset(("Anchor: Innocent Maid", "Snow White: Heavy Arms")): 3.0,
    frozenset(("Mast: Romantic Maid", "Snow White: Heavy Arms")): 3.0,
    frozenset(("Quency: Escape Queen", "Modernia")): 3.0,

    # Slice #126 — synergy round 5. Drive under-represented count below 50.
    frozenset(("2B", "Liter")): 3.0,
    frozenset(("Admi", "Liter")): 3.0,
    frozenset(("Alice: Wonderland Bunny", "Liter")): 3.0,
    frozenset(("Anis", "Crown")): 3.0,
    frozenset(("Anne: Miracle Fairy", "Liter")): 3.0,
    frozenset(("Arcana: Fortune Mate", "Crown")): 3.0,
    frozenset(("Arcana: Fortune Mate", "Tove")): 3.0,
    frozenset(("Aria", "Liter")): 3.0,
    frozenset(("Avistar", "Liter")): 3.0,
    frozenset(("Belorta", "Liter")): 3.0,
    frozenset(("Biscuit", "Crown")): 3.0,
    frozenset(("Biscuit", "Helm")): 3.0,
    frozenset(("Bready", "Liter")): 3.0,
    frozenset(("Brid", "Liter")): 3.0,
    frozenset(("Brid: Silent Track", "Liter")): 3.0,
    frozenset(("Chime", "Liter")): 3.0,
    frozenset(("Claire Redfield", "Crown")): 3.0,
    frozenset(("Claire Redfield", "Liter")): 3.0,
    frozenset(("Crow", "Liter")): 3.0,
    frozenset(("Crust", "Centi")): 3.0,
    frozenset(("D", "Liter")): 3.0,
    frozenset(("Diesel", "Liter")): 3.0,
    frozenset(("Diesel: Winter Sweets", "Liter")): 3.0,
    frozenset(("Dolla", "Crown")): 3.0,
    frozenset(("Dolla", "Liter")): 3.0,
    frozenset(("Ein", "Liter")): 3.0,
    frozenset(("Elegg", "Liter")): 3.0,
    frozenset(("Elegg: Boom and Shock", "Liter")): 3.0,
    frozenset(("Emilia", "Liter")): 3.0,
    frozenset(("Emma: Tactical Upgrade", "Liter")): 3.0,
    frozenset(("Exia", "Liter")): 3.0,
    frozenset(("Guillotine: Winter Slayer", "Liter")): 3.0,
    frozenset(("Harran", "Liter")): 3.0,
    frozenset(("Kilo", "Liter")): 3.0,
    frozenset(("Laplace", "Liter")): 3.0,
    frozenset(("Mana", "Crown")): 3.0,
    frozenset(("Mana", "Liter")): 3.0,
    frozenset(("Miranda", "Crown")): 3.0,
    frozenset(("Miranda", "Liter")): 3.0,
    frozenset(("Misato Katsuragi", "Liter")): 3.0,
    frozenset(("Moran", "Crown")): 3.0,
    frozenset(("Nayuta", "Liter")): 3.0,
    frozenset(("Pascal", "Liter")): 3.0,
    frozenset(("Poli", "Crown")): 3.0,
    frozenset(("Poli", "Liter")): 3.0,
    frozenset(("Power", "Liter")): 3.0,
    frozenset(("Privaty", "Liter")): 3.0,
    frozenset(("Quiry", "Liter")): 3.0,
    frozenset(("Rapi", "Liter")): 3.0,
    frozenset(("Rapunzel", "Crown")): 3.0,
    frozenset(("Rem", "Liter")): 3.0,
    frozenset(("Rosanna", "Crown")): 3.0,
    frozenset(("Rosanna: Chic Ocean", "Liter")): 3.0,
    frozenset(("Rouge", "Modernia")): 3.0,
    frozenset(("Scarlet", "Crown")): 3.0,
    frozenset(("Scarlet", "Liter")): 3.0,
    frozenset(("Sin", "Liter")): 3.0,
    frozenset(("Snow Crane", "Liter")): 3.0,
    frozenset(("Soda", "Crown")): 3.0,
    frozenset(("Soda: Twinkling Bunny", "Liter")): 3.0,
    frozenset(("Viper", "Crown")): 3.0,
    frozenset(("Yan", "Liter")): 3.0,
    frozenset(("Yulha", "Liter")): 3.0,
    frozenset(("Eve", "Liter")): 3.0,
    frozenset(("Frima", "Crown")): 3.0,
    frozenset(("Bay (Treasure)", "Liter")): 3.0,
    frozenset(("Centi (Treasure)", "Liter")): 3.0,
    frozenset(("Helm (Treasure)", "Liter")): 3.0,
    frozenset(("Drake (Treasure)", "Liter")): 3.0,
    # Remaining under-represented stragglers.
    frozenset(("Maiden", "Liter")): 3.0,
    frozenset(("Mary", "Modernia")): 3.0,
    frozenset(("Neon: Vision Eye", "Liter")): 3.0,
    frozenset(("Rosanna", "Liter")): 3.0,
    frozenset(("Viper", "Liter")): 3.0,
    # Round 7 encodings — synergy pairs.
    frozenset(("Eunhwa", "Crown")): 3.0,
    frozenset(("Eunhwa", "Liter")): 3.0,
    frozenset(("Mori", "Crown")): 3.0,
    frozenset(("Mori", "Liter")): 3.0,
    frozenset(("Diesel (Treasure)", "Crown")): 3.0,
    frozenset(("Diesel (Treasure)", "Helm")): 3.0,
    frozenset(("Julia (Treasure)", "Crown")): 4.0,
    frozenset(("Julia (Treasure)", "Liter")): 3.0,
    frozenset(("Laplace (Treasure)", "Crown")): 4.0,
    frozenset(("Laplace (Treasure)", "Liter")): 3.0,
    frozenset(("Frima (Treasure)", "Crown")): 3.0,
    frozenset(("Frima (Treasure)", "Modernia")): 3.0,
    # Round 8 encodings (Treasure-form set).
    frozenset(("Miranda (Treasure)", "Crown")): 3.0,
    frozenset(("Miranda (Treasure)", "Modernia")): 3.0,
    frozenset(("Moran (Treasure)", "Crown")): 3.0,
    frozenset(("Moran (Treasure)", "Helm")): 3.0,
    frozenset(("Milk (Treasure)", "Crown")): 3.0,
    frozenset(("Milk (Treasure)", "Modernia")): 3.0,
    frozenset(("Exia (Treasure)", "Crown")): 3.0,
    frozenset(("Exia (Treasure)", "Liter")): 3.0,
    frozenset(("Tove (Treasure)", "Anis: Sparkling Summer")): 4.0,
    frozenset(("Tove (Treasure)", "Noir")): 4.0,
    frozenset(("Poli (Treasure)", "Crown")): 3.0,
    frozenset(("Poli (Treasure)", "Modernia")): 3.0,
    # Round 9 encodings.
    frozenset(("Eunhwa: Tactical Upgrade", "Crown")): 4.0,
    frozenset(("Eunhwa: Tactical Upgrade", "Liter")): 3.0,
    frozenset(("Ludmilla", "Crown")): 3.0,
    frozenset(("Ludmilla", "Liter")): 3.0,
    frozenset(("Milk", "Crown")): 3.0,
    frozenset(("Milk", "Helm")): 3.0,
    frozenset(("Rumani", "Crown")): 3.0,
    frozenset(("Rumani", "Modernia")): 3.0,
    frozenset(("K", "Crown")): 3.0,
    frozenset(("K", "Liter")): 3.0,
    frozenset(("Label", "Helm")): 3.0,
    frozenset(("Label", "Centi")): 3.0,

    # ------------------------------------------------------------------
    # Round 10 encodings (Signal / Snow White: Innocent Days / Soline /
    # Sora / Sugar / Velvet / Vesti / Viper (Treasure) / Yuni / Zwei /
    # Zwei (Treasure)). 2026-05-10.
    # ------------------------------------------------------------------
    frozenset(("Signal", "Crown")): 3.0,
    frozenset(("Signal", "Liter")): 3.0,
    frozenset(("Snow White: Innocent Days", "Crown")): 4.0,
    frozenset(("Snow White: Innocent Days", "Liter")): 4.0,
    frozenset(("Snow White: Innocent Days", "Blanc")): 3.0,
    frozenset(("Soline", "Helm")): 4.0,  # Max-HP-gated crit; shield support
    frozenset(("Soline", "Centi")): 3.0,
    frozenset(("Soline", "Crown")): 3.0,
    frozenset(("Sora", "Crown")): 3.0,
    frozenset(("Sora", "Liter")): 3.0,
    frozenset(("Sugar", "Crown")): 3.0,
    frozenset(("Sugar", "Modernia")): 3.0,  # SG-ally ammo buff
    frozenset(("Velvet", "Crown")): 3.0,
    frozenset(("Velvet", "Liter")): 3.0,
    frozenset(("Vesti", "Crown")): 3.0,
    frozenset(("Vesti", "Liter")): 3.0,
    frozenset(("Viper (Treasure)", "Crown")): 4.0,
    frozenset(("Viper (Treasure)", "Liter")): 3.0,
    frozenset(("Yuni", "Crown")): 3.0,
    frozenset(("Yuni", "Liter")): 3.0,
    frozenset(("Zwei", "Snow White: Heavy Arms")): 3.0,  # Pierce comp
    frozenset(("Zwei", "Liter")): 3.0,
    frozenset(("Zwei (Treasure)", "Snow White: Heavy Arms")): 4.0,
    frozenset(("Zwei (Treasure)", "Crown")): 3.0,
    frozenset(("Zwei (Treasure)", "Modernia")): 3.0,
    # Skin-variant uniqueness placeholders (0 bonus, document constraints):
    frozenset(("Vesti", "Vesti: Tactical Upgrade")): 0.0,
    frozenset(("Viper", "Viper (Treasure)")): 0.0,
    frozenset(("Zwei", "Zwei (Treasure)")): 0.0,
    frozenset(("Snow White", "Snow White: Heavy Arms")): 0.0,
    frozenset(("Snow White", "Snow White: Innocent Days")): 0.0,
    frozenset(("Snow White: Heavy Arms", "Snow White: Innocent Days")): 0.0,
    frozenset(("Soline", "Soline: Frost Ticket")): 0.0,

    # ------------------------------------------------------------------
    # Round 11 encodings (SR / R completion set). 2026-05-10.
    # SR: Delta, Ether, Himeno, Kurumi, Lily, Mica, N102, Neon, Neve,
    # Ram, Sakura Suzuhara. R: Product 08/12/23, Soldier EG/FA,
    # iDoll Flower/Ocean/Sun. Bonuses are minimal (3.0) since these are
    # low-PvP-relevance Recruits / niche SRs encoded mostly for coverage.
    # ------------------------------------------------------------------
    frozenset(("Delta", "Crown")): 3.0,
    frozenset(("Delta", "Helm")): 3.0,
    frozenset(("Ether", "Crown")): 3.0,
    frozenset(("Ether", "Helm")): 3.0,
    frozenset(("Himeno", "Maxwell")): 3.0,  # SR-only buff filter
    frozenset(("Himeno", "Snow White: Heavy Arms")): 3.0,
    frozenset(("Kurumi", "Crown")): 3.0,
    frozenset(("Kurumi", "Liter")): 3.0,
    frozenset(("Lily", "Crown")): 3.0,
    frozenset(("Lily", "Liter")): 3.0,
    frozenset(("Mica", "Crown")): 3.0,
    frozenset(("Mica", "Helm")): 3.0,
    frozenset(("N102", "Crown")): 3.0,
    frozenset(("N102", "Liter")): 3.0,
    frozenset(("Neon", "Crown")): 3.0,
    frozenset(("Neon", "Anis: Sparkling Summer")): 3.0,  # SG synergy
    frozenset(("Neve", "Crown")): 3.0,
    frozenset(("Neve", "Liter")): 3.0,
    frozenset(("Ram", "Crown")): 3.0,
    frozenset(("Ram", "Liter")): 3.0,
    frozenset(("Sakura Suzuhara", "Crown")): 3.0,
    frozenset(("Sakura Suzuhara", "Helm")): 3.0,
    frozenset(("Product 08", "Crown")): 3.0,
    frozenset(("Product 08", "Liter")): 3.0,
    frozenset(("Product 12", "Crown")): 3.0,
    frozenset(("Product 12", "Liter")): 3.0,
    frozenset(("Product 23", "Crown")): 3.0,
    frozenset(("Product 23", "Liter")): 3.0,
    frozenset(("Soldier EG", "Crown")): 3.0,
    frozenset(("Soldier EG", "Liter")): 3.0,
    frozenset(("Soldier FA", "Crown")): 3.0,
    frozenset(("Soldier FA", "Helm")): 3.0,
    frozenset(("iDoll Flower", "Crown")): 3.0,
    frozenset(("iDoll Flower", "Liter")): 3.0,
    frozenset(("iDoll Ocean", "Crown")): 3.0,
    frozenset(("iDoll Ocean", "Helm")): 3.0,
    frozenset(("iDoll Sun", "Crown")): 3.0,
    frozenset(("iDoll Sun", "Liter")): 3.0,

    # ------------------------------------------------------------------
    # Skin variants — same nominal Nikke can't be in the same team in PvP
    # (the game enforces this). Logged at 0 to document the constraint;
    # scoring leaves the pair valued at 0 since hard uniqueness is already
    # enforced upstream.
    # ------------------------------------------------------------------
    frozenset(("Helm", "Helm: Aquamarine")): 0.0,

    # ------------------------------------------------------------------
    # Batch-1 SSR additions — synergy pairings for newly encoded
    # characters so they don't trip the under-represented test.
    # ------------------------------------------------------------------
    # Delta: Ninja Thief — Water MG B2 Defender; pairs with Water-team
    # and DPS-needing-shield carries.
    frozenset(("Delta: Ninja Thief", "Crown")): 2.0,
    frozenset(("Delta: Ninja Thief", "Liter")): 2.0,
    frozenset(("Delta: Ninja Thief", "Mast")): 1.5,
    # E.H. — Wind SMG B3 self-buff carry; pairs with B1 buff supports.
    frozenset(("E.H.", "Crown")): 3.0,
    frozenset(("E.H.", "Liter")): 3.0,
    # Emma — Fire MG B1 budget healer; pairs with Fire allies.
    frozenset(("Emma", "Mast")): 2.0,
    frozenset(("Emma", "Moran")): 1.5,
    # Flora — Electric MG B2 supporter; pairs with Electric allies.
    frozenset(("Flora", "Scarlet: Black Shadow")): 2.5,
    frozenset(("Flora", "Trina")): 1.5,
    # Guilty — Wind SG B2 anti-tank; pairs with high-ATK carries to mirror.
    frozenset(("Guilty", "Liter")): 2.0,
    frozenset(("Guilty", "Crown")): 2.0,
    # Isabel — Electric SG B3 Pilgrim state-machine carry.
    frozenset(("Isabel", "Crown")): 3.0,
    frozenset(("Isabel", "Liter")): 3.0,
    # Nero — Fire SMG B2 defender; pairs with Fire-team and tank synergy.
    frozenset(("Nero", "Mast: Romantic Maid")): 2.0,
    frozenset(("Nero", "Crown")): 2.0,
    # Novel — Iron SMG B2 anti-tank nuker; pairs with B3 carries.
    frozenset(("Novel", "Snow White: Heavy Arms")): 2.5,
    frozenset(("Novel", "Crown")): 2.5,
    # Rei — Water SMG B1 decoy-based tank.
    frozenset(("Rei", "Liter")): 1.5,
    frozenset(("Rei", "Crown")): 1.5,
    # Rei Ayanami — Fire MG B3 Eva-collab shield-shredder.
    frozenset(("Rei Ayanami", "Crown")): 3.0,
    frozenset(("Rei Ayanami", "Liter")): 3.0,
    frozenset(("Rei Ayanami", "Mast")): 2.5,
    # Rupee — Iron AR B2 supporter; pairs with Iron-team carries.
    frozenset(("Rupee", "Scarlet")): 2.5,
    frozenset(("Rupee", "Scarlet: Black Shadow")): 2.5,
    # Rupee: Winter Shopper — Electric AR B1 with re-enter mechanic.
    frozenset(("Rupee: Winter Shopper", "Crown")): 3.0,
    frozenset(("Rupee: Winter Shopper", "Liter")): 2.5,
}


# Real Prydwen role tags (verified by inventorying char.role_tags in the DB).
# An earlier draft used verbose archetype names that don't appear in the
# data — that bug zeroed out role_balance for every Attacker.
_ROLE_BUCKETS: dict[str, tuple[str, ...]] = {
    "dps": ("Attacker",),
    "support": ("Supporter", "Buffer", "Debuffer"),
    "defender": ("Defender", "Shielder", "Taunter"),
    "healer": ("Healer", "Cover Heal"),
}

_DURABILITY_TAGS = {"Defender", "Shielder", "Healer", "Cover Heal", "Taunter"}
_BURST_GEN_TAGS = {"Burst CD Reduction", "Re-Enter Burst Stage"}

# Per-view role-bucket cache. ``CharacterView`` is frozen and hashable
# but the per-call recomputation showed up as 60% of ``score_team``
# time on Champions runs (24M ``_roles_of`` calls × per-tag startswith
# checks). Cache keyed by the immutable ``role_tags`` tuple so two
# different ``CharacterView`` instances of the same character (e.g.,
# from different DB loads) share entries. Slice #101.
_ROLES_CACHE: dict[tuple[str, ...], frozenset[str]] = {}


def _roles_of(view: CharacterView) -> frozenset[str]:
    """Return every role bucket this character maps into.

    A character can fall into multiple buckets — Blanc is Defender +
    Shielder + Healer, for example. The role_balance scorer checks
    presence-by-bucket so multi-role units count for whichever bucket they
    fill in the team, not all of them at once.
    """
    cached = _ROLES_CACHE.get(view.role_tags)
    if cached is not None:
        return cached
    out: set[str] = set()
    for tag in view.role_tags:
        for role, prefixes in _ROLE_BUCKETS.items():
            if any(tag.startswith(p) for p in prefixes):
                out.add(role)
    result = frozenset(out)
    _ROLES_CACHE[view.role_tags] = result
    return result


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------


def _effective_power(view: CharacterView) -> int:
    """Return ``view.power`` if captured (owned + arena-imported),
    otherwise the BlablaLink-predicted power (``predicted_power``).

    Unowned characters used to score 0 power, which made counter-pick
    scoring against opponent compositions blind to stat investment.
    With BlablaLink stat tables mirrored locally, we can predict their
    power at a reasonable assumed investment level (LV600 / MLB / Core 7
    / max skills, set in ``loader.py``).
    """
    if view.power > 0:
        return view.power
    if view.predicted_power is not None:
        return view.predicted_power
    return 0


def _score_power(team: list[CharacterView]) -> float:
    """Log-scale the team's total power so the score doesn't get dominated
    by a single high-CP unit."""
    total = sum(_effective_power(m) for m in team)
    if total <= 0:
        return 0.0
    return math.log10(total)


def _score_element_diversity(team: list[CharacterView]) -> float:
    """Reward element diversity: more distinct elements = more match-up
    flexibility. 5 distinct elements = 5 pts; all-same = 1 pt.
    """
    elements = {m.element for m in team}
    return float(len(elements))


def _score_role_balance(team: list[CharacterView]) -> float:
    """Reward an attacker + support mix.

    Pure-DPS teams without burst generators or buffers tend to under-perform
    in PvP. Multi-role characters count for each of their buckets.
    """
    bucket_present: dict[str, int] = {"dps": 0, "support": 0, "defender": 0, "healer": 0}
    for m in team:
        for r in _roles_of(m):
            bucket_present[r] += 1
    score = 0.0
    if bucket_present["dps"] >= 1:
        score += 1.0
    if bucket_present["support"] >= 2:
        score += 2.0
    elif bucket_present["support"] >= 1:
        score += 1.0
    if bucket_present["defender"] >= 1 or bucket_present["healer"] >= 1:
        score += 0.5
    return score


# Meta-tier multipliers — a hand-curated PvP relevance score per character.
# Multiplied into synergy-pair bonuses so older units (Modernia, Dorothy)
# don't get full credit for being in a "Crown comp" when the meta has moved
# on. Refresh ~quarterly by reading Prydwen's tier list manually; missing
# entries fall through to the heuristic in `_meta_tier_for()`.
#
# Key:   character name (matches Character.name in the DB)
# Value: 0.0–1.2 multiplier
#   1.2  meta-defining new release
#   1.0  current PvP meta
#   0.8  still meta but past peak
#   0.6  past-meta — used to be S/SS, now A/B
#   0.4  fully outclassed — only field if no alternative
#
# Last refresh: 2026-04-28 (snapshot from Prydwen tier list browse).
META_TIER: dict[str, float] = {
    # ---- Current PvP meta (1.0) ----
    "Red Hood": 1.0,
    "Crown": 1.0,
    "Snow White: Heavy Arms": 1.0,
    "Scarlet: Black Shadow": 1.0,
    "Asuka Shikinami Langley": 1.0,
    "Cinderella": 1.0,
    "Maxwell": 1.0,
    "Alice": 1.0,
    "Rapi: Red Hood": 1.0,
    "Naga": 1.0,
    "Tia": 1.0,
    "Liter": 1.0,
    "Helm": 1.0,
    "Centi": 1.0,
    "Blanc": 1.0,
    "Noah": 1.0,
    "Bay": 1.0,
    "Anchor": 1.0,
    "Maiden: Ice Rose": 1.0,
    "Chisato Nishikigi": 1.0,
    "Takina Inoue": 1.0,
    "Jill Valentine": 1.0,
    "Ada Wong": 1.0,
    "Privaty: Unkind Maid": 1.0,
    "Mihara": 1.0,
    "Jackal": 1.0,
    "Ein": 1.0,
    "Mary: Bay Goddess": 1.0,
    "Anchor: Innocent Maid": 1.0,
    "Helm: Aquamarine": 1.0,
    "Phantom": 1.0,
    # ---- Past-meta (0.6) ----
    "Modernia": 0.6,
    "Dorothy": 0.6,
    "Anis: Sparkling Summer": 0.6,
    "Volume": 0.6,
    "Drake": 0.6,
    "Soda": 0.6,
    "Privaty": 0.6,
    "Diesel": 0.6,
    "Sakura": 0.6,
    # ---- Niche (0.7) — situational picks, e.g. anti-element ----
    "D: Killer Wife": 0.7,
    "Anis: Star": 0.7,
    "Mast: Romantic Maid": 0.7,
    "Soldier OW": 0.7,
    "Pepper": 0.7,
    "Quency": 0.7,
    "Marciana": 0.7,
    "Folkwang": 0.7,
    "Trony": 0.7,
}


def _meta_tier_for(name: str, role_tags: tuple[str, ...] = ()) -> float:
    """Return the meta-tier multiplier for ``name``.

    Looks up the manual override first; otherwise falls back to a
    heuristic on character data we have via Prydwen-enriched fields:
    new (specialities)-tagged units get 0.85 default; characters whose
    role_tags include "Healer" or "Defender" get 0.9 (defenders are
    more evergreen than attackers); anything else 0.7.

    Without DB context here we can only use ``role_tags``. Future
    refinement: pass the full CharacterView so we can also see
    ``release_date`` recency and ``is_limited`` / ``high_investment``.
    """
    if name in META_TIER:
        return META_TIER[name]
    # Heuristic fallback. Defenders + Supporters age slower than attackers.
    tags_lower = {t.lower() for t in role_tags}
    if "defender" in tags_lower or "supporter" in tags_lower or "healer" in tags_lower:
        return 0.85
    return 0.7


@lru_cache(maxsize=8192)
def _cached_synergy_score(
    team_key: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[float, tuple[str, ...]]:
    """Cached synergy-pair scoring keyed on (sorted) team identity.

    Slice #115b — like the FB-cache, ``_score_synergy_pairs`` is called
    ~100k times per rookie pass. Each call iterates 10 pair combinations
    and looks them up in SYNERGY_PAIRS. Caching by a sorted tuple of
    (name, role_tags) is a clean win since the result is order-
    independent (we re-sort names internally) and role_tags drive the
    meta-tier multiplier deterministically.
    """
    names = [n for n, _ in team_key]
    role_tags_by_name = {n: t for n, t in team_key}
    tier_by_name = {n: _meta_tier_for(n, role_tags_by_name.get(n, ())) for n in names}
    score = 0.0
    notes: list[str] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            key = frozenset((names[i], names[j]))
            if key in SYNERGY_PAIRS:
                base_bonus = SYNERGY_PAIRS[key]
                if base_bonus > 0:
                    multiplier = min(tier_by_name[names[i]], tier_by_name[names[j]])
                    bonus = base_bonus * multiplier
                    score += bonus
                    notes.append(
                        f"synergy: {names[i]} + {names[j]} (+{bonus:.1f}"
                        + (f", tier ×{multiplier:.1f}" if multiplier < 1.0 else "")
                        + ")"
                    )
    # Return notes as a tuple so callers can't mutate the cached value.
    return score, tuple(notes)


def _score_synergy_pairs(team: list[CharacterView]) -> tuple[float, list[str]]:
    """Sum the bonuses for every pair in the team that appears in
    :data:`SYNERGY_PAIRS`, scaled by the lower meta-tier multiplier of
    the two members. A Crown+Modernia pairing counts at Modernia's 0.6
    rather than Crown's 1.0 — the bonus is only as good as the weakest
    link in current meta."""
    team_key = tuple(sorted(
        (m.name, tuple(m.role_tags)) for m in team
    ))
    score, notes_tuple = _cached_synergy_score(team_key)
    # Convert the cached tuple back to a fresh list for the caller —
    # they may extend it without polluting the cache entry.
    return score, list(notes_tuple)


def _score_investment(team: list[CharacterView]) -> float:
    """Reward high skill levels and arena cubes equipped — the user has put
    real investment into these characters; preferring them over equally
    powerful but less-invested options.
    """
    score = 0.0
    for m in team:
        skills = (m.skill1_level + m.skill2_level + m.burst_skill_level) / 3
        score += skills / 10  # 1.0 for max-skill character
        if m.arena_cube_name:
            score += 0.5
    return score


def _score_durability(team: list[CharacterView]) -> float:
    """Per-character durability contribution (capped) summed across the team.

    Each member's durability tags are counted, then capped at 2 — multi-role
    utility units (Tia has 5 dur tags: Defender/Healer/Shielder/Taunter/
    Cover Heal) shouldn't dominate the score over a team with several
    dedicated defenders.
    """
    score = 0.0
    for m in team:
        member_dur = sum(1 for tag in m.role_tags if tag in _DURABILITY_TAGS)
        score += min(member_dur, 2)
    return score


def _score_burst_gen(team: list[CharacterView]) -> float:
    """Reward burst-gen + B1 supports + fast weapon mix (slice #77).

    Fast full-burst entries are attack-favorable (defense actively wants
    SLOW burst gen so the attacker times out). Counts:
      * +1 per ``Burst CD Reduction`` / ``Re-Enter Burst Stage`` tag
      * +0.5 per B1-position support character (Liter, Tia, etc.)
      * +/- weapon-mix speed bonus from slice #75's gauge dynamics
        (SG/RL-heavy comps faster, MG/SMG-heavy slower).
    """
    score = 0.0
    for m in team:
        for tag in m.role_tags:
            if tag in _BURST_GEN_TAGS:
                score += 1.0
        if m.burst_position == "1" and "support" in _roles_of(m):
            score += 0.5

    score += _weapon_mix_speed_bonus(team)
    return score


@lru_cache(maxsize=4096)
def _cached_fb_start(name_weapon_pairs: tuple[tuple[str, Optional[str]], ...]) -> float:
    """Cached Full-Burst-window start for a (sorted) team key.

    Slice #115 — `_weapon_mix_speed_bonus` is called ~100k times in a
    rookie pass via `_score_burst_gen`. Each call computes the same
    burst offsets for the same member-set (the calculation is order-
    independent — it sums per-weapon and per-skill rates). Caching by
    a sorted tuple of (name, weapon) keeps unique compositions cheap
    after first compute.
    """
    from ..simulator.timeline import compute_burst_chain_offsets

    names = [n for n, _ in name_weapon_pairs]
    weapons = [w for _, w in name_weapon_pairs]
    return compute_burst_chain_offsets(weapons, member_names=names)[2]


def _weapon_mix_speed_bonus(team: list[CharacterView]) -> float:
    """Convert burst-chain offsets into a +/- bonus around the legacy
    Crown comp baseline (10s).

    ``compute_burst_chain_offsets`` returns the Full-Burst-window start
    at index 2. We compare it to the 12.0s legacy default — earlier =
    bonus, later = penalty. Capped at +/- 1.5 so the burst-gauge channel
    can't overwhelm the rest of scoring.
    """
    try:
        from ..simulator.timeline import DEFAULT_FULL_BURST_START_SEC
    except Exception:
        return 0.0

    pairs = tuple(sorted(
        (m.name, m.weapon_class.value if getattr(m, "weapon_class", None) else None)
        for m in team
    ))
    fb_start = _cached_fb_start(pairs)
    delta = DEFAULT_FULL_BURST_START_SEC - fb_start  # positive = faster
    return max(-1.5, min(1.5, delta * 0.5))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class ScoringWeights:
    """Component weights. Adjustable for what-if exploration in the UI."""

    power_sum: float = 1.0
    element_diversity: float = 0.4
    role_balance: float = 1.5
    synergy_pairs: float = 1.0
    investment: float = 0.6
    durability: float = 1.0
    burst_gen: float = 1.0
    # Simulator-derived components, only contribute when ``rescore_with_evaluator``
    # is called. Zero by default so plain ``score_team`` is unchanged.
    team_buff_amp: float = 0.0
    vs_high_def: float = 0.0


# BALANCED is the default — used by Champions where each team plays both
# attack and defense via 50/50 coin flip.
BALANCED_WEIGHTS = ScoringWeights(team_buff_amp=0.6, vs_high_def=0.4)
DEFAULT_WEIGHTS = BALANCED_WEIGHTS

# ATTACK weights: favor fast burst entries, established attack synergies,
# and accept slightly less durability. Power and synergy stay strong because
# the goal is to BURN through the opponent's defense before timeout.
# Damage-conversion bonuses matter most here — true-damage carries shine
# vs durable defenders.
ATTACK_WEIGHTS = ScoringWeights(
    power_sum=1.0,
    element_diversity=0.4,
    role_balance=1.0,
    synergy_pairs=1.5,
    investment=0.6,
    durability=0.5,
    burst_gen=2.0,
    team_buff_amp=1.0,
    vs_high_def=0.8,
)

# DEFENSE weights: favor units that survive 5 minutes of incoming damage.
# Defenders, healers, and shielders dominate; burst-gen is actively bad
# because slow burst gen denies the attacker the kill window. Damage-conversion
# is near-zero here — defenders don't push damage.
DEFENSE_WEIGHTS = ScoringWeights(
    power_sum=1.0,
    element_diversity=0.4,
    role_balance=1.0,
    synergy_pairs=1.0,
    investment=0.6,
    durability=3.0,
    burst_gen=0.0,
    team_buff_amp=0.1,
    vs_high_def=0.0,
)


Role = Literal["attack", "defense", "balanced"]


def weights_for_role(role: Role) -> ScoringWeights:
    if role == "attack":
        return ATTACK_WEIGHTS
    if role == "defense":
        return DEFENSE_WEIGHTS
    return BALANCED_WEIGHTS


def score_team(
    team: list[CharacterView],
    *,
    weights: ScoringWeights = BALANCED_WEIGHTS,
) -> Optional[TeamCandidate]:
    """Score a candidate team. Returns ``None`` if it fails any hard
    constraint (so callers can drop it before sorting)."""
    if not is_valid_team(team):
        return None

    power = _score_power(team)
    diversity = _score_element_diversity(team)
    role = _score_role_balance(team)
    synergy, synergy_notes = _score_synergy_pairs(team)
    investment = _score_investment(team)
    durability = _score_durability(team)
    burst_gen = _score_burst_gen(team)

    weighted_power = weights.power_sum * power
    weighted_diversity = weights.element_diversity * diversity
    weighted_role = weights.role_balance * role
    weighted_synergy = weights.synergy_pairs * synergy
    weighted_investment = weights.investment * investment
    weighted_durability = weights.durability * durability
    weighted_burst_gen = weights.burst_gen * burst_gen

    burst_feasibility = 1.0  # passed the hard check
    total = (
        burst_feasibility
        + weighted_power
        + weighted_diversity
        + weighted_role
        + weighted_synergy
        + weighted_investment
        + weighted_durability
        + weighted_burst_gen
    )

    breakdown = ScoreBreakdown(
        burst_feasibility=burst_feasibility,
        power_sum=weighted_power,
        element_diversity=weighted_diversity,
        role_balance=weighted_role,
        synergy_pairs=weighted_synergy,
        investment=weighted_investment,
        durability=weighted_durability,
        burst_gen=weighted_burst_gen,
        total=total,
    )

    notes: list[str] = []
    elements = {m.element.value for m in team}
    if len(elements) == 5:
        notes.append("rainbow team (5 distinct elements)")
    if len(elements) == 1:
        notes.append("mono-element team")
    notes.extend(synergy_notes)
    return TeamCandidate(members=tuple(team), breakdown=breakdown, notes=notes)


# ---------------------------------------------------------------------------
# Simulator-aware rescoring (Phase-3 wiring)
# ---------------------------------------------------------------------------


# Normalization scales for the simulator-derived components. The raw values
# are large magnitudes (a team with multiple true-damage carries can hit
# 200+ on team_buff_amp, 500+ on vs_high_def_index); these scales bring
# them into the same order of magnitude as the heuristic components (1–10
# range) so the weights are comparable.
_BUFF_AMP_SCALE = 50.0  # per ~50% of stacked damage-type buffs → +1 raw point
_VS_HIGH_DEF_SCALE = 100.0  # per 100 raw vs_high_def units → +1 raw point


def rescore_with_evaluator(
    candidate: TeamCandidate,
    evaluation,  # simulator.evaluator.TeamEvaluation — avoid import cycle
    *,
    weights: ScoringWeights = BALANCED_WEIGHTS,
) -> TeamCandidate:
    """Re-score a candidate using simulator-derived buff dimensions.

    Adds two contributions to the team's total score:

    * ``team_buff_amp`` — average across damage-type buffs (true / attack /
      pierce / shield / core / burst-skill damage). Rewards teams that
      stack multiple damage amplifiers, regardless of which one.
    * ``vs_high_def``   — heuristic for punching through high-DEF defenders.
      Combines true-damage buffs (DEF-bypass) + pierce + shield-damage. Most
      relevant under ATTACK_WEIGHTS, near-zero under DEFENSE_WEIGHTS.

    Returns a new :class:`TeamCandidate` with updated breakdown + total.
    The original heuristic components are preserved unchanged.
    """
    # Average across the 6 damage-type buff dimensions (each is already a
    # team-average percentage, so just average the averages).
    raw_buff_amp = (
        evaluation.team_true_damage_buff_pct
        + evaluation.team_attack_damage_buff_pct
        + evaluation.team_pierce_damage_buff_pct
        + evaluation.team_shield_damage_buff_pct
        + evaluation.team_core_damage_buff_pct
        + evaluation.team_burst_skill_damage_buff_pct
    ) / 6.0

    raw_vs_high_def = evaluation.vs_high_def_damage_index

    weighted_buff_amp = weights.team_buff_amp * (raw_buff_amp / _BUFF_AMP_SCALE)
    weighted_vs_high_def = weights.vs_high_def * (raw_vs_high_def / _VS_HIGH_DEF_SCALE)

    old = candidate.breakdown
    new_total = old.total + weighted_buff_amp + weighted_vs_high_def

    new_breakdown = ScoreBreakdown(
        burst_feasibility=old.burst_feasibility,
        power_sum=old.power_sum,
        element_diversity=old.element_diversity,
        role_balance=old.role_balance,
        synergy_pairs=old.synergy_pairs,
        investment=old.investment,
        durability=old.durability,
        burst_gen=old.burst_gen,
        team_buff_amp=weighted_buff_amp,
        vs_high_def=weighted_vs_high_def,
        total=new_total,
    )

    notes = list(candidate.notes)
    # Add a one-line annotation when the simulator signals are notable
    # so the UI's notes panel reflects what changed.
    if raw_buff_amp >= 50.0:
        notes.append(f"high damage-buff stack ({raw_buff_amp:.0f}% avg)")
    if raw_vs_high_def >= 200.0:
        notes.append(f"strong vs high-DEF defenders ({raw_vs_high_def:.0f})")

    return TeamCandidate(
        members=candidate.members,
        breakdown=new_breakdown,
        notes=notes,
    )
