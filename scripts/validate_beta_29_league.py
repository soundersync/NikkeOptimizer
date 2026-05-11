"""Validate simulator against Beta Season 29 League — Nika vs Kyushen.

Compares simulator predictions to actual match outcomes (5 rounds).
Per-character damage / heal / HP-remaining are extracted from the
in-game Battle Records screens via OCR (already done; values inlined
below).

Usage:
    PYTHONPATH=src python scripts/validate_beta_29_league.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nikke_optimizer.simulator import registry  # noqa: E402
from nikke_optimizer.simulator.evaluator import evaluate_by_names  # noqa: E402
from nikke_optimizer.simulator.match_sim import simulate_per_character  # noqa: E402


# ---------------------------------------------------------------------
# Match definitions: NIKA's 5 teams + KYUSHEN's 5 teams + actual outcome
# (winner, plus per-character DMG / DMG-taken / HEAL / HP-remaining for
# the side whose data was synced in the replay capture).
#
# Names below are the canonical registry names. OCR'd numbers come from
# captures/beta_season_29/league/player_1/results/duel_*.png.
# ---------------------------------------------------------------------

MATCHES = [
    {
        "round": 1,
        "winner": "nika",  # Nika WIN, Kyushen LOSE
        "nika": [
            "Jackal", "Vesti: Tactical Upgrade", "Blanc",
            "Ada Wong", "Laplace",
        ],
        "kyushen": [
            "Noise", "Noah", "Cinderella", "Helm", "Anis",
        ],
        # Synced side: BOTH (Kyushen all 0% disconnected; Nika has 4 alive).
        # Numbers (DMG / TAKEN / HEAL) are best-guess from OCR ordering.
        "actual": {
            "nika": {  # winner — survived
                "Jackal": {"dmg": 1_663_913, "taken": 11_059_658, "heal": 0, "hp_pct": 0.0},
                "Vesti: Tactical Upgrade": {"dmg": 48_272_380, "taken": 39_200_924, "heal": 2_601_524, "hp_pct": 7.92},
                "Blanc": {"dmg": 379_479, "taken": 7_290_087, "heal": 1_563_206, "hp_pct": 100.0},
                "Ada Wong": {"dmg": 1_557_179, "taken": 7_898_978, "heal": 0, "hp_pct": 100.0},
                "Laplace": {"dmg": 5_086_470, "taken": 10_216_507, "heal": 0, "hp_pct": 100.0},
            },
            "kyushen": {  # loser — fully cleared
                "Noise": {"dmg": 3_956_784, "taken": 8_943_034, "heal": 3_963_762, "hp_pct": 0.0},
                "Noah": {"dmg": 3_082_839, "taken": 9_588_624, "heal": 0, "hp_pct": 0.0},
                "Cinderella": {"dmg": 6_991_012, "taken": 6_553_400, "heal": 0, "hp_pct": 0.0},
                "Helm": {"dmg": 8_266_849, "taken": 7_327_228, "heal": 662_888, "hp_pct": 0.0},
                "Anis": {"dmg": 2_639_477, "taken": 6_337_766, "heal": 0, "hp_pct": 0.0},
            },
        },
    },
    {
        "round": 2,
        "winner": "kyushen",  # Kyushen WIN
        "nika": [
            "Nayuta", "Helm", "Red Hood", "Emilia", "Rumani",
        ],
        "kyushen": [
            "Soda: Twinkling Bunny", "Poli", "Rosanna", "Noir", "Drake",
        ],
        "actual": {
            "kyushen": {
                "Soda: Twinkling Bunny": {"dmg": 6_514_938, "taken": 3_217_571, "heal": 0, "hp_pct": 6.93},
                "Poli": {"dmg": 2_167_731, "taken": 1_135_059, "heal": 133_242, "hp_pct": 72.63},
                "Rosanna": {"dmg": 12_396_132, "taken": 941_971, "heal": 0, "hp_pct": 72.90},
                "Noir": {"dmg": 1_821_134, "taken": 0, "heal": 0, "hp_pct": 100.0},
                "Drake": {"dmg": 2_422_013, "taken": 0, "heal": 0, "hp_pct": 100.0},
            },
            "nika": {
                "Nayuta": {"dmg": 578_740, "taken": 4_383_485, "heal": 0, "hp_pct": 0.0},
                "Helm": {"dmg": 743_890, "taken": 9_870_667, "heal": 45_794, "hp_pct": 0.0},
                "Red Hood": {"dmg": 838_589, "taken": 3_412_541, "heal": 0, "hp_pct": 0.0},
                "Emilia": {"dmg": 6_786_465, "taken": 2_971_773, "heal": 0, "hp_pct": 0.0},
                "Rumani": {"dmg": 1_397_520, "taken": 4_683_482, "heal": 0, "hp_pct": 0.0},
            },
        },
    },
    {
        "round": 3,
        "winner": "kyushen",
        "nika": [
            "Scarlet", "Trina", "Soda", "Anis", "Centi",
        ],
        "kyushen": [
            "Scarlet: Black Shadow", "Blanc", "Emilia", "Rapunzel", "Laplace",
        ],
        "actual": {
            "kyushen": {
                "Scarlet: Black Shadow": {"dmg": 2_755_233, "taken": 6_171_452, "heal": 0, "hp_pct": 0.0},
                "Blanc": {"dmg": 282_478, "taken": 5_777_532, "heal": 2_050_828, "hp_pct": 0.0},
                "Emilia": {"dmg": 6_356_568, "taken": 7_447_673, "heal": 0, "hp_pct": 0.0},
                "Rapunzel": {"dmg": 6_709_078, "taken": 4_746_580, "heal": 765_456, "hp_pct": 49.16},
                "Laplace": {"dmg": 15_586_782, "taken": 3_099_067, "heal": 0, "hp_pct": 81.69},
            },
            "nika": {
                "Scarlet": {"dmg": 23_898_738, "taken": 5_924_311, "heal": 0, "hp_pct": 0.0},
                "Trina": {"dmg": 1_026_350, "taken": 3_564_507, "heal": 123_985, "hp_pct": 0.0},
                "Soda": {"dmg": 507_335, "taken": 3_168_486, "heal": 0, "hp_pct": 0.0},
                "Anis": {"dmg": 1_617_667, "taken": 3_162_650, "heal": 0, "hp_pct": 0.0},
                "Centi": {"dmg": 3_915_331, "taken": 4_229_888, "heal": 837_945, "hp_pct": 0.0},
            },
        },
    },
    {
        "round": 4,
        "winner": "kyushen",
        "nika": [
            "Rapunzel", "Little Mermaid (Siren)", "Liberalio",
            "Noah", "Anis: Star",
        ],
        "kyushen": [
            "Scarlet", "Soda", "Trina", "Centi", "Jackal",
        ],
        "actual": {
            "kyushen": {
                "Scarlet": {"dmg": 26_368_925, "taken": 510_945, "heal": 0, "hp_pct": 47.95},
                "Soda": {"dmg": 843_354, "taken": 1_592_509, "heal": 0, "hp_pct": 49.52},
                "Trina": {"dmg": 2_700_853, "taken": 599_023, "heal": 95_748, "hp_pct": 68.09},
                "Centi": {"dmg": 2_010_169, "taken": 0, "heal": 0, "hp_pct": 86.19},
                "Jackal": {"dmg": 2_310_588, "taken": 599_023, "heal": 0, "hp_pct": 73.16},
            },
            "nika": {
                "Rapunzel": {"dmg": 1_874_625, "taken": 6_873_456, "heal": 5_568_592, "hp_pct": 0.0},
                "Little Mermaid (Siren)": {"dmg": 130_990, "taken": 6_696_651, "heal": 0, "hp_pct": 0.0},
                "Liberalio": {"dmg": 4_049_903, "taken": 0, "heal": 0, "hp_pct": 0.0},
                "Noah": {"dmg": 589_626, "taken": 7_678_616, "heal": 0, "hp_pct": 0.0},
                "Anis: Star": {"dmg": 5_670_704, "taken": 4_483_620, "heal": 495_530, "hp_pct": 0.0},
            },
        },
    },
    {
        "round": 5,
        "winner": "nika",
        "nika": [
            "Moran", "Bay", "Biscuit", "Snow White: Heavy Arms", "Label",
        ],
        "kyushen": [
            "Moran", "Biscuit", "Anis: Sparkling Summer",
            "Maiden: Ice Rose", "Rumani",
        ],
        "actual": {
            "kyushen": {
                "Moran": {"dmg": 859_159, "taken": 13_194_274, "heal": 281_255, "hp_pct": 0.0},
                "Biscuit": {"dmg": 4_512_553, "taken": 5_995_799, "heal": 1_634_444, "hp_pct": 0.0},
                "Anis: Sparkling Summer": {"dmg": 18_263_965, "taken": 9_072_307, "heal": 5_779_239, "hp_pct": 0.0},
                "Maiden: Ice Rose": {"dmg": 3_654_722, "taken": 5_261_790, "heal": 0, "hp_pct": 0.0},
                "Rumani": {"dmg": 1_981_961, "taken": 5_301_686, "heal": 0, "hp_pct": 0.0},
            },
            "nika": {
                "Moran": {"dmg": 1_123_670, "taken": 2_853_499, "heal": 93_229, "hp_pct": 76.54},
                "Bay": {"dmg": 4_958_311, "taken": 3_160_048, "heal": 3_712_672, "hp_pct": 36.53},
                "Biscuit": {"dmg": 4_244_668, "taken": 3_177_227, "heal": 1_259_354, "hp_pct": 40.08},
                "Snow White: Heavy Arms": {"dmg": 36_720_999, "taken": 3_349_598, "heal": 0, "hp_pct": 32.32},
                "Label": {"dmg": 552_330, "taken": 3_045_429, "heal": 0, "hp_pct": 21.96},
            },
        },
    },
]


def fmt_num(n):
    return f"{int(n):>11,}"


def pct_err(predicted, actual):
    if actual == 0:
        return "  n/a" if predicted == 0 else " >999%"
    return f"{(predicted - actual) / actual * 100:+6.0f}%"


def main():
    registry._autoload_library()

    # Verify all names resolve before running.
    for m in MATCHES:
        for side in ("nika", "kyushen"):
            for n in m[side]:
                if registry.get(n) is None:
                    print(f"ERROR: unknown name {n!r}")
                    return

    print("=" * 96)
    print("  BETA SEASON 29 LEAGUE — Nika vs Kyushen   (actual: Kyushen 3-2 Nika)")
    print("=" * 96)

    outcome_correct = 0

    for match in MATCHES:
        rno = match["round"]
        nika_team = match["nika"]
        kyu_team = match["kyushen"]
        winner = match["winner"]

        nika_eval = evaluate_by_names(nika_team)
        kyu_eval = evaluate_by_names(kyu_team)

        # Champions Arena coin flip: simulate both directions.
        nika_atk = simulate_per_character(nika_eval, kyu_eval)
        kyu_atk = simulate_per_character(kyu_eval, nika_eval)

        nika_wins_count = (1 if nika_atk.attacker_wins else 0) + \
                          (0 if kyu_atk.attacker_wins else 1)
        if nika_wins_count == 2:
            pred = "nika"
        elif nika_wins_count == 0:
            pred = "kyushen"
        else:
            pred = "split"

        if pred == winner and pred != "split":
            outcome_correct += 1

        # Choose the perspective that matches actual outcome so per-char
        # numbers are meaningful (we don't know who actually attacked).
        if winner == "nika":
            chosen = nika_atk
            n_per = chosen.attacker_per_char
            k_per = chosen.defender_per_char
        else:
            chosen = kyu_atk
            k_per = chosen.attacker_per_char
            n_per = chosen.defender_per_char

        print()
        print(f"--- ROUND {rno}  ACTUAL: {winner.upper():<8}  "
              f"SIM (both flips): nika_atk={'W' if nika_atk.attacker_wins else 'L'} "
              f"kyu_atk={'W' if kyu_atk.attacker_wins else 'L'}  "
              f"→ predicted={pred.upper()}  "
              f"{'✓' if pred == winner else '✗' if pred != 'split' else '?'}")
        print(f"    end_reason: nika_atk={nika_atk.end_reason:<18} "
              f"kyu_atk={kyu_atk.end_reason:<18}")
        for n in nika_atk.notes:
            if "first_burst" in n:
                print(f"    {n}")
                break

        for label, team_list, per in [
            ("NIKA", nika_team, n_per),
            ("KYUSHEN", kyu_team, k_per),
        ]:
            actual_side = match["actual"][label.lower()]
            print(f"\n    {label}:")
            print(f"    {'Character':<32}  {'DMG dealt':>11}  {'DMG taken':>11}  {'HEAL':>11}   HP%")
            for char_name in team_list:
                stats = per.get(char_name, {})
                actual = actual_side.get(char_name, {})
                sim_dmg = stats.get("damage_dealt", 0)
                sim_tk = stats.get("damage_taken", 0)
                sim_hl = stats.get("healing_dealt", 0)
                hp_pct_sim = stats.get("hp_pct", 0)
                a_dmg = actual.get('dmg', 0)
                a_tk = actual.get('taken', 0)
                a_hl = actual.get('heal', 0)
                a_hp = actual.get('hp_pct', 0)
                print(f"    {char_name:<32}  "
                      f"{fmt_num(sim_dmg)}  "
                      f"{fmt_num(sim_tk)}  "
                      f"{fmt_num(sim_hl)}  "
                      f"{hp_pct_sim:5.1f}%")
                print(f"    {'    actual:':<32}  "
                      f"{fmt_num(a_dmg)}  "
                      f"{fmt_num(a_tk)}  "
                      f"{fmt_num(a_hl)}  "
                      f"{a_hp:5.1f}%")
                print(f"    {'    err:':<32}  "
                      f"{pct_err(sim_dmg, a_dmg):>11}  "
                      f"{pct_err(sim_tk, a_tk):>11}  "
                      f"{pct_err(sim_hl, a_hl):>11}")

    print("\n" + "=" * 96)
    print(f"OUTCOME: simulator predicted {outcome_correct}/5 rounds correctly "
          f"(actual: Kyushen 3-2 Nika)")
    print("=" * 96)


if __name__ == "__main__":
    main()
