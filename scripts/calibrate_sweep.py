"""Grid search calibration: sweep multipliers and find best fit
against beta-29 actuals across all 5 rounds.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nikke_optimizer.simulator import registry, damage as damage_mod
from nikke_optimizer.simulator import match_sim as ms
from nikke_optimizer.simulator.evaluator import evaluate_by_names
from nikke_optimizer.simulator.match_sim import simulate_per_character


# Real outcomes — per-team total dealt by winner / loser as numerator-target.
MATCHES = [
    {"r": 1, "winner": "nika",
     "n": ["Jackal", "Vesti: Tactical Upgrade", "Blanc", "Ada Wong", "Laplace"],
     "k": ["Noise", "Noah", "Cinderella", "Helm", "Anis"],
     "actual_to_kyu": 57_000_000,
     "actual_to_nika": 75_700_000},
    {"r": 2, "winner": "kyushen",
     "n": ["Nayuta", "Helm", "Red Hood", "Emilia", "Rumani"],
     "k": ["Soda: Twinkling Bunny", "Poli", "Rosanna", "Noir", "Drake"],
     "actual_to_kyu": 10_300_000,   # NIKA dealt to KYU; NIKA lost (mostly partial dmg)
     "actual_to_nika": 24_900_000},
    {"r": 3, "winner": "kyushen",
     "n": ["Scarlet", "Trina", "Soda", "Anis", "Centi"],
     "k": ["Scarlet: Black Shadow", "Blanc", "Emilia", "Rapunzel", "Laplace"],
     "actual_to_kyu": 31_700_000,
     "actual_to_nika": 20_000_000},
    {"r": 4, "winner": "kyushen",
     "n": ["Rapunzel", "Little Mermaid (Siren)", "Liberalio", "Noah", "Anis: Star"],
     "k": ["Scarlet", "Soda", "Trina", "Centi", "Jackal"],
     "actual_to_kyu": 3_300_000,
     "actual_to_nika": 26_200_000},
    {"r": 5, "winner": "nika",
     "n": ["Moran", "Bay", "Biscuit", "Snow White: Heavy Arms", "Label"],
     "k": ["Moran", "Biscuit", "Anis: Sparkling Summer", "Maiden: Ice Rose", "Rumani"],
     "actual_to_kyu": 47_600_000,
     "actual_to_nika": 17_900_000},   # winner Nika; her own team damage taken
]


def run_one_config():
    out = []
    for m in MATCHES:
        ne = evaluate_by_names(m["n"])
        ke = evaluate_by_names(m["k"])
        nika_atk = simulate_per_character(ne, ke)
        kyu_atk = simulate_per_character(ke, ne)
        n_wins = (1 if nika_atk.attacker_wins else 0) + (0 if kyu_atk.attacker_wins else 1)
        if n_wins == 2:
            pred = "nika"
        elif n_wins == 0:
            pred = "kyushen"
        else:
            pred = "split"
        # Use winner-perspective for damage
        chosen = nika_atk if m["winner"] == "nika" else kyu_atk
        sim_to_def = chosen.attacker_total_damage
        sim_to_atk = chosen.defender_total_damage
        if m["winner"] == "nika":
            sim_to_kyu = sim_to_def; sim_to_nika = sim_to_atk
        else:
            sim_to_kyu = sim_to_atk; sim_to_nika = sim_to_def
        # Log-error
        import math
        err_kyu = math.log(max(sim_to_kyu, 1) / max(m["actual_to_kyu"], 1))
        err_nika = math.log(max(sim_to_nika, 1) / max(m["actual_to_nika"], 1))
        out.append({
            "r": m["r"], "pred": pred, "winner": m["winner"],
            "end": chosen.match_ended_at_sec,
            "sim_to_kyu": sim_to_kyu, "sim_to_nika": sim_to_nika,
            "act_to_kyu": m["actual_to_kyu"], "act_to_nika": m["actual_to_nika"],
            "log_err_kyu": err_kyu, "log_err_nika": err_nika,
        })
    correct = sum(1 for r in out if r["pred"] == r["winner"])
    abs_log = sum(abs(r["log_err_kyu"]) + abs(r["log_err_nika"]) for r in out)
    avg_end = sum(r["end"] for r in out) / len(out)
    return out, correct, abs_log, avg_end


def main():
    registry._autoload_library()
    base_charge = damage_mod.CHARGE_DAMAGE_AVG_MULT
    base_range = damage_mod.EFFECTIVE_RANGE_BONUS
    base_roles = dict(ms._ROLE_DPS_SCALE)

    best = None
    print(f"{'charge':<7} {'range':<6} {'atk':<5} {'def':<5} {'sup':<5}  {'win':<3} {'logE':<6} {'avg_end':<7}")
    for charge in [1.2, 1.5, 1.8, 2.1, 2.5]:
        for atk_s in [0.5, 0.7, 0.9, 1.0]:
            for def_s in [0.25, 0.4, 0.6]:
                for sup_s in [0.15, 0.3, 0.5]:
                    damage_mod.CHARGE_DAMAGE_AVG_MULT = charge
                    ms._ROLE_DPS_SCALE = {
                        "attacker": atk_s, "defender": def_s, "supporter": sup_s
                    }
                    _, correct, log_err, avg_end = run_one_config()
                    score = (-correct, log_err)  # max correct, min log_err
                    if best is None or score < best[0]:
                        best = (score, (charge, atk_s, def_s, sup_s, correct, log_err, avg_end))
                        print(f"{charge:<7} {1.30:<6} {atk_s:<5} {def_s:<5} {sup_s:<5}  "
                              f"{correct}/5 {log_err:5.2f} {avg_end:>5.1f}s  *NEW BEST*")
    print()
    print(f"BEST: charge={best[1][0]} atk={best[1][1]} def={best[1][2]} sup={best[1][3]} "
          f"correct={best[1][4]}/5 logE={best[1][5]:.2f} avg_end={best[1][6]:.1f}s")


if __name__ == "__main__":
    main()
