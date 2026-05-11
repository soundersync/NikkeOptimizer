"""Test event_loop simulator against beta-29 captures."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nikke_optimizer.simulator import registry
from nikke_optimizer.simulator.evaluator import evaluate_by_names
from nikke_optimizer.simulator.event_loop import simulate_event_loop

MATCHES = [
    ("R1", "nika",
     ["Jackal", "Vesti: Tactical Upgrade", "Blanc", "Ada Wong", "Laplace"],
     ["Noise", "Noah", "Cinderella", "Helm", "Anis"]),
    ("R2", "kyushen",
     ["Nayuta", "Helm", "Red Hood", "Emilia", "Rumani"],
     ["Soda: Twinkling Bunny", "Poli", "Rosanna", "Noir", "Drake"]),
    ("R3", "kyushen",
     ["Scarlet", "Trina", "Soda", "Anis", "Centi"],
     ["Scarlet: Black Shadow", "Blanc", "Emilia", "Rapunzel", "Laplace"]),
    ("R4", "kyushen",
     ["Rapunzel", "Little Mermaid (Siren)", "Liberalio", "Noah", "Anis: Star"],
     ["Scarlet", "Soda", "Trina", "Centi", "Jackal"]),
    ("R5", "nika",
     ["Moran", "Bay", "Biscuit", "Snow White: Heavy Arms", "Label"],
     ["Moran", "Biscuit", "Anis: Sparkling Summer", "Maiden: Ice Rose", "Rumani"]),
]


def main():
    registry._autoload_library()
    correct = 0
    print(f"{'R':<4} {'actual':<10} {'pred':<10} {'end':<8} a_first  d_first  toKYU/toNIKA")
    for label, winner, n, k in MATCHES:
        ne = evaluate_by_names(n)
        ke = evaluate_by_names(k)
        n_atk = simulate_event_loop(ne, ke)
        k_atk = simulate_event_loop(ke, ne)
        n_wins = (1 if n_atk.attacker_wins else 0) + (0 if k_atk.attacker_wins else 1)
        pred = "nika" if n_wins == 2 else ("kyushen" if n_wins == 0 else "split")
        mark = "✓" if pred == winner else "✗"
        if pred == winner:
            correct += 1
        chosen = n_atk if winner == "nika" else k_atk
        if winner == "nika":
            stk = chosen.attacker_total_damage
            stn = chosen.defender_total_damage
        else:
            stk = chosen.defender_total_damage
            stn = chosen.attacker_total_damage
        print(f"{label} {mark} {winner:<10} {pred:<10} {chosen.match_ended_at_sec:>5.1f}s  "
              f"{chosen.a_first_burst_at:>5.1f}s   {chosen.d_first_burst_at:>5.1f}s   "
              f"{stk/1e6:>5.1f}M / {stn/1e6:>5.1f}M")
    print(f"\noutcome event_loop: {correct}/5")


if __name__ == "__main__":
    main()
