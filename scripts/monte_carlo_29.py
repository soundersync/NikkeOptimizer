"""Monte Carlo simulation over beta-29 league matches.

Runs each round N times with different seeds, reports P(NIKA wins) and
damage variance per team.
"""
from __future__ import annotations
import statistics
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nikke_optimizer.simulator import registry
from nikke_optimizer.simulator.evaluator import evaluate_by_names
from nikke_optimizer.simulator.match_sim import simulate_per_character


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


def main(n_runs: int = 100):
    registry._autoload_library()
    print(f"Monte Carlo: {n_runs} runs per round\n")
    print(f"{'Round':<6} {'Actual':<10} {'P(nika)':<8} {'P(kyu)':<7} {'avg end':<10} {'mean toKYU':<12} {'mean toNIKA':<12}")

    for label, actual_winner, n, k in MATCHES:
        ne = evaluate_by_names(n)
        ke = evaluate_by_names(k)
        nika_wins = 0
        kyu_wins = 0
        end_times = []
        to_kyus = []
        to_nikas = []
        for seed in range(n_runs):
            # Champions Arena coin flip: try both directions.
            nika_atk = simulate_per_character(ne, ke, seed=seed)
            kyu_atk = simulate_per_character(ke, ne, seed=seed + 1000)
            n_wins = (1 if nika_atk.attacker_wins else 0) + \
                     (0 if kyu_atk.attacker_wins else 1)
            if n_wins == 2:
                nika_wins += 1
            elif n_wins == 0:
                kyu_wins += 1
            # else split
            chosen = nika_atk if actual_winner == "nika" else kyu_atk
            if actual_winner == "nika":
                to_kyus.append(chosen.attacker_total_damage)
                to_nikas.append(chosen.defender_total_damage)
            else:
                to_kyus.append(chosen.defender_total_damage)
                to_nikas.append(chosen.attacker_total_damage)
            end_times.append(chosen.match_ended_at_sec)
        p_nika = nika_wins / n_runs
        p_kyu = kyu_wins / n_runs
        mean_end = statistics.mean(end_times)
        mean_kyu = statistics.mean(to_kyus)
        mean_nika = statistics.mean(to_nikas)
        std_kyu = statistics.stdev(to_kyus) if n_runs > 1 else 0
        std_nika = statistics.stdev(to_nikas) if n_runs > 1 else 0
        print(f"{label:<6} {actual_winner:<10} {p_nika:.2f}     {p_kyu:.2f}    "
              f"{mean_end:.1f}s      {mean_kyu/1e6:.1f}M ±{std_kyu/1e6:.1f}    "
              f"{mean_nika/1e6:.1f}M ±{std_nika/1e6:.1f}")


if __name__ == "__main__":
    main(n_runs=100)
