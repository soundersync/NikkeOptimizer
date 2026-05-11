"""Calibration sweep: vary global damage formula constants and report
sim outcome accuracy + match-length distribution against beta-29 actuals.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nikke_optimizer.simulator import registry, damage as damage_mod
from nikke_optimizer.simulator.evaluator import evaluate_by_names
from nikke_optimizer.simulator.match_sim import simulate_per_character


# Real outcomes
MATCHES = [
    {"r": 1, "winner": "nika",
     "n": ["Jackal", "Vesti: Tactical Upgrade", "Blanc", "Ada Wong", "Laplace"],
     "k": ["Noise", "Noah", "Cinderella", "Helm", "Anis"],
     "actual_total_to_kyu": 57_000_000,    # NIKA dealt to KYU
     "actual_total_to_nika": 75_700_000,   # KYU dealt to NIKA (Vesti tanked)
     "winner_alive_count": 4},  # 4/5 NIKA alive at end (Jackal died)
    {"r": 2, "winner": "kyushen",
     "n": ["Nayuta", "Helm", "Red Hood", "Emilia", "Rumani"],
     "k": ["Soda: Twinkling Bunny", "Poli", "Rosanna", "Noir", "Drake"],
     "actual_total_to_kyu": 24_900_000,
     "actual_total_to_nika": 33_400_000,
     "winner_alive_count": 5},
    {"r": 3, "winner": "kyushen",
     "n": ["Scarlet", "Trina", "Soda", "Anis", "Centi"],
     "k": ["Scarlet: Black Shadow", "Blanc", "Emilia", "Rapunzel", "Laplace"],
     "actual_total_to_kyu": 31_700_000,
     "actual_total_to_nika": 27_400_000,
     "winner_alive_count": 2},
    {"r": 4, "winner": "kyushen",
     "n": ["Rapunzel", "Little Mermaid (Siren)", "Liberalio", "Noah", "Anis: Star"],
     "k": ["Scarlet", "Soda", "Trina", "Centi", "Jackal"],
     "actual_total_to_kyu": 8_100_000,
     "actual_total_to_nika": 26_200_000,
     "winner_alive_count": 5},
    {"r": 5, "winner": "nika",
     "n": ["Moran", "Bay", "Biscuit", "Snow White: Heavy Arms", "Label"],
     "k": ["Moran", "Biscuit", "Anis: Sparkling Summer", "Maiden: Ice Rose", "Rumani"],
     "actual_total_to_kyu": 47_600_000,
     "actual_total_to_nika": 29_300_000,
     "winner_alive_count": 5},
]


def run_validation():
    registry._autoload_library()

    correct = 0
    diffs_to_kyu = []
    diffs_to_nika = []
    end_times = []
    for m in MATCHES:
        ne = evaluate_by_names(m["n"])
        ke = evaluate_by_names(m["k"])
        # Two coin flips
        nika_atk = simulate_per_character(ne, ke)
        kyu_atk = simulate_per_character(ke, ne)
        # Pred
        n_wins = (1 if nika_atk.attacker_wins else 0) + (0 if kyu_atk.attacker_wins else 1)
        if n_wins == 2:
            pred = "nika"
        elif n_wins == 0:
            pred = "kyushen"
        else:
            pred = "split"
        if pred == m["winner"]:
            correct += 1

        # Pick the winner perspective for damage totals
        chosen = nika_atk if m["winner"] == "nika" else kyu_atk
        sim_to_def = chosen.attacker_total_damage  # winner dealt to loser
        sim_to_atk = chosen.defender_total_damage
        end_times.append(chosen.match_ended_at_sec)

        if m["winner"] == "nika":
            sim_to_kyu = sim_to_def; sim_to_nika = sim_to_atk
        else:
            sim_to_kyu = sim_to_atk; sim_to_nika = sim_to_def

        d_kyu_pct = (sim_to_kyu - m["actual_total_to_kyu"]) / m["actual_total_to_kyu"] * 100
        d_nika_pct = (sim_to_nika - m["actual_total_to_nika"]) / m["actual_total_to_nika"] * 100
        diffs_to_kyu.append(d_kyu_pct)
        diffs_to_nika.append(d_nika_pct)

        print(f"  R{m['r']} actual={m['winner']:<7} pred={pred:<7} "
              f"end={chosen.match_ended_at_sec:>5.1f}s  "
              f"toKYU sim={sim_to_kyu/1e6:>5.1f}M act={m['actual_total_to_kyu']/1e6:>5.1f}M ({d_kyu_pct:+5.0f}%)  "
              f"toNIKA sim={sim_to_nika/1e6:>5.1f}M act={m['actual_total_to_nika']/1e6:>5.1f}M ({d_nika_pct:+5.0f}%)")
    avg_kyu = sum(diffs_to_kyu) / len(diffs_to_kyu)
    avg_nika = sum(diffs_to_nika) / len(diffs_to_nika)
    avg_end = sum(end_times) / len(end_times)
    abs_kyu = sum(abs(d) for d in diffs_to_kyu) / len(diffs_to_kyu)
    abs_nika = sum(abs(d) for d in diffs_to_nika) / len(diffs_to_nika)
    print(f"\n  outcome={correct}/5  avg end={avg_end:.1f}s  "
          f"avg_err toKYU={avg_kyu:+5.0f}% / toNIKA={avg_nika:+5.0f}%  "
          f"abs_err toKYU={abs_kyu:5.0f}% / toNIKA={abs_nika:5.0f}%")
    return correct, abs_kyu + abs_nika


def sweep():
    """Sweep weapon factors / charge / range and find best fit."""
    base_weapons = dict(damage_mod.WEAPON_DAMAGE_PER_SECOND_FRACTION)
    base_charge = damage_mod.CHARGE_DAMAGE_DEFAULT_MULTIPLIER
    base_range = damage_mod.EFFECTIVE_RANGE_BONUS

    print("=== BASELINE ===")
    run_validation()

    # Step 1: try halving weapon factors
    for scale in [0.5, 0.4, 0.3, 0.25, 0.2]:
        damage_mod.WEAPON_DAMAGE_PER_SECOND_FRACTION = {
            k: v * scale for k, v in base_weapons.items()
        }
        print(f"\n=== WEAPON SCALE × {scale} ===")
        run_validation()
    # restore
    damage_mod.WEAPON_DAMAGE_PER_SECOND_FRACTION = base_weapons

    # Step 2: charge variation
    for chg in [2.0, 1.7, 1.5, 1.3, 1.0]:
        damage_mod.CHARGE_DAMAGE_DEFAULT_MULTIPLIER = chg
        print(f"\n=== CHARGE = {chg} ===")
        run_validation()
    damage_mod.CHARGE_DAMAGE_DEFAULT_MULTIPLIER = base_charge

    # Step 3: range variation
    for rng in [1.30, 1.20, 1.15, 1.10, 1.0]:
        damage_mod.EFFECTIVE_RANGE_BONUS = rng
        print(f"\n=== RANGE = {rng} ===")
        run_validation()
    damage_mod.EFFECTIVE_RANGE_BONUS = base_range


if __name__ == "__main__":
    sweep()
