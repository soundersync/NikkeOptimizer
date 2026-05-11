"""Diagnostic: print per-member sustained_dps + burst_payload + death tick
for each round of beta-29 to see why some characters end with 0 damage.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nikke_optimizer.simulator import registry
from nikke_optimizer.simulator.evaluator import evaluate_by_names
from nikke_optimizer.simulator.match_sim import simulate_per_character


TEAMS = [
    ("R1 NIKA", ["Jackal", "Vesti: Tactical Upgrade", "Blanc", "Ada Wong", "Laplace"], "winner"),
    ("R1 KYU",  ["Noise", "Noah", "Cinderella", "Helm", "Anis"], "loser"),
    ("R2 NIKA", ["Nayuta", "Helm", "Red Hood", "Emilia", "Rumani"], "loser"),
    ("R2 KYU",  ["Soda: Twinkling Bunny", "Poli", "Rosanna", "Noir", "Drake"], "winner"),
    ("R3 NIKA", ["Scarlet", "Trina", "Soda", "Anis", "Centi"], "loser"),
    ("R3 KYU",  ["Scarlet: Black Shadow", "Blanc", "Emilia", "Rapunzel", "Laplace"], "winner"),
    ("R4 NIKA", ["Rapunzel", "Little Mermaid (Siren)", "Liberalio", "Noah", "Anis: Star"], "loser"),
    ("R4 KYU",  ["Scarlet", "Soda", "Trina", "Centi", "Jackal"], "winner"),
    ("R5 NIKA", ["Moran", "Bay", "Biscuit", "Snow White: Heavy Arms", "Label"], "winner"),
    ("R5 KYU",  ["Moran", "Biscuit", "Anis: Sparkling Summer", "Maiden: Ice Rose", "Rumani"], "loser"),
]


def main():
    registry._autoload_library()
    # Pair up rounds — 0&1, 2&3, etc.
    for i in range(0, len(TEAMS), 2):
        nika_label, nika, _ = TEAMS[i]
        kyu_label, kyu, _ = TEAMS[i+1]
        print(f"\n========== ROUND {1 + i // 2} ==========")
        ne = evaluate_by_names(nika)
        ke = evaluate_by_names(kyu)
        for label, ev, opp_ev in [(nika_label, ne, ke), (kyu_label, ke, ne)]:
            opp_avg_def = sum(m.effective_def for m in opp_ev.members) / len(opp_ev.members)
            print(f"\n  {label}  (vs avg DEF {opp_avg_def:,.0f})")
            print(f"  {'name':30}  {'ATK':>10}  {'sus_dps':>11}  {'burst_pay':>12}  bp wpn")
            from nikke_optimizer.simulator.match_sim import _per_char_states
            ms = _per_char_states(
                ev, opponent_avg_def=opp_avg_def,
                opponent_elements=[m.element for m in opp_ev.members],
            )
            for m, s in zip(ev.members, ms):
                print(f"  {m.name:30}  {m.effective_atk:>10,.0f}  {s.sustained_dps:>11,.0f}  {s.burst_payload:>12,.0f}  {m.burst_position} {m.weapon_class}")
        # Run sim with both atk directions to see who dies when
        for atk_label, atk_ev, def_ev in [(f"{nika_label}-atk", ne, ke), (f"{kyu_label}-atk", ke, ne)]:
            res = simulate_per_character(atk_ev, def_ev)
            print(f"\n  -> {atk_label} → {'WIN' if res.attacker_wins else 'LOSS'} at t={res.match_ended_at_sec:.0f}s ({res.end_reason})")
            print(f"     attacker per-char: ", end="")
            for m_name, stats in res.attacker_per_char.items():
                print(f"{m_name.split(':')[0][:8]}={int(stats['damage_dealt']):,} ", end="")
            print()
            print(f"     defender per-char: ", end="")
            for m_name, stats in res.defender_per_char.items():
                print(f"{m_name.split(':')[0][:8]}={int(stats['damage_dealt']):,} ", end="")
            print()


if __name__ == "__main__":
    main()
