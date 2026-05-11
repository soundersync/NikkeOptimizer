"""V2 sweep: finer-grained search around interesting region.

Key insight from v1: outcome maxes at 2/5 because no global tuning
moves the per-char attribution enough. Try to find the config that
produces (a) realistic match lengths and (b) closest per-team damage
totals.
"""
from __future__ import annotations
import sys
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nikke_optimizer.simulator import registry, damage as damage_mod
from nikke_optimizer.simulator import match_sim as ms
from nikke_optimizer.simulator.evaluator import evaluate_by_names
from nikke_optimizer.simulator.match_sim import simulate_per_character

MATCHES = [
    {"r": 1, "winner": "nika", "target_end": 30,
     "n": ["Jackal", "Vesti: Tactical Upgrade", "Blanc", "Ada Wong", "Laplace"],
     "k": ["Noise", "Noah", "Cinderella", "Helm", "Anis"],
     "actual_to_kyu": 57_000_000, "actual_to_nika": 75_700_000},
    {"r": 2, "winner": "kyushen", "target_end": 8,
     "n": ["Nayuta", "Helm", "Red Hood", "Emilia", "Rumani"],
     "k": ["Soda: Twinkling Bunny", "Poli", "Rosanna", "Noir", "Drake"],
     "actual_to_kyu": 10_300_000, "actual_to_nika": 24_900_000},
    {"r": 3, "winner": "kyushen", "target_end": 20,
     "n": ["Scarlet", "Trina", "Soda", "Anis", "Centi"],
     "k": ["Scarlet: Black Shadow", "Blanc", "Emilia", "Rapunzel", "Laplace"],
     "actual_to_kyu": 31_700_000, "actual_to_nika": 20_000_000},
    {"r": 4, "winner": "kyushen", "target_end": 10,
     "n": ["Rapunzel", "Little Mermaid (Siren)", "Liberalio", "Noah", "Anis: Star"],
     "k": ["Scarlet", "Soda", "Trina", "Centi", "Jackal"],
     "actual_to_kyu": 3_300_000, "actual_to_nika": 26_200_000},
    {"r": 5, "winner": "nika", "target_end": 20,
     "n": ["Moran", "Bay", "Biscuit", "Snow White: Heavy Arms", "Label"],
     "k": ["Moran", "Biscuit", "Anis: Sparkling Summer", "Maiden: Ice Rose", "Rumani"],
     "actual_to_kyu": 47_600_000, "actual_to_nika": 17_900_000},
]


def evaluate():
    correct = 0
    log_err = 0.0
    end_err = 0.0
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
        if pred == m["winner"]:
            correct += 1
        chosen = nika_atk if m["winner"] == "nika" else kyu_atk
        sim_to_def = chosen.attacker_total_damage
        sim_to_atk = chosen.defender_total_damage
        if m["winner"] == "nika":
            stk = sim_to_def; stn = sim_to_atk
        else:
            stk = sim_to_atk; stn = sim_to_def
        log_err += abs(math.log(max(stk, 1) / max(m["actual_to_kyu"], 1)))
        log_err += abs(math.log(max(stn, 1) / max(m["actual_to_nika"], 1)))
        end_err += abs(chosen.match_ended_at_sec - m["target_end"]) / m["target_end"]
    return correct, log_err, end_err


def main():
    registry._autoload_library()
    base_charge = damage_mod.CHARGE_DAMAGE_AVG_MULT
    base_roles = dict(ms._ROLE_DPS_SCALE)

    print(f"{'chg':<4} {'atk':<5} {'def':<5} {'sup':<5} {'pre':<5}  win logE  endE")
    best_score = None
    best_cfg = None
    for charge in [1.5, 1.8, 2.1, 2.4, 2.7]:
        for atk_s in [0.20, 0.25, 0.32, 0.40]:
            for def_s in [0.08, 0.12, 0.18, 0.25]:
                for sup_s in [0.04, 0.08, 0.12, 0.18]:
                    damage_mod.CHARGE_DAMAGE_AVG_MULT = charge
                    ms._ROLE_DPS_SCALE = {
                        "attacker": atk_s, "defender": def_s, "supporter": sup_s
                    }
                    correct, log_err, end_err = evaluate()
                    score = (-correct, log_err + end_err * 2)
                    if best_score is None or score < best_score:
                        best_score = score
                        best_cfg = (charge, atk_s, def_s, sup_s)
                        print(f"{charge:<4} {atk_s:<5} {def_s:<5} {sup_s:<5} ----  "
                              f"{correct}/5 {log_err:5.2f} {end_err:5.2f}  *BEST*")
    print(f"\nBest: charge={best_cfg[0]} atk={best_cfg[1]} def={best_cfg[2]} sup={best_cfg[3]}")
    # Print final detailed run with best config
    damage_mod.CHARGE_DAMAGE_AVG_MULT = best_cfg[0]
    ms._ROLE_DPS_SCALE = {
        "attacker": best_cfg[1], "defender": best_cfg[2], "supporter": best_cfg[3]
    }
    print("\nDetail with best:")
    for m in MATCHES:
        ne = evaluate_by_names(m["n"])
        ke = evaluate_by_names(m["k"])
        nika_atk = simulate_per_character(ne, ke)
        kyu_atk = simulate_per_character(ke, ne)
        n_wins = (1 if nika_atk.attacker_wins else 0) + (0 if kyu_atk.attacker_wins else 1)
        pred = "nika" if n_wins == 2 else ("kyushen" if n_wins == 0 else "split")
        chosen = nika_atk if m["winner"] == "nika" else kyu_atk
        sim_def = chosen.attacker_total_damage
        sim_atk = chosen.defender_total_damage
        if m["winner"] == "nika":
            stk, stn = sim_def, sim_atk
        else:
            stk, stn = sim_atk, sim_def
        ok = "✓" if pred == m["winner"] else "✗"
        print(f"  R{m['r']} {ok} pred={pred:<7} end={chosen.match_ended_at_sec:>5.1f}s "
              f"toKYU {stk/1e6:>5.1f}M (act {m['actual_to_kyu']/1e6:.1f}M)  "
              f"toNIKA {stn/1e6:>5.1f}M (act {m['actual_to_nika']/1e6:.1f}M)")


if __name__ == "__main__":
    main()
