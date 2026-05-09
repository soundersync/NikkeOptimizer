"""Validate event-loop simulator against captured tournament outcomes.

Pulls promo_match data from the DB, runs simulate_event_loop against each
round's left/right teams, and compares predictions to actual outcomes
parsed from the round-strip OCR (e.g. "ROUND 01 LOSE WIN").

Compares against simulate_per_character (the prior best simulator) so
we can see whether DSL effect scheduling actually moves the needle.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

# Make src/ importable when invoked from project root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import text  # noqa: E402

from nikke_optimizer.data.db import get_session, make_engine  # noqa: E402
from nikke_optimizer.simulator import registry  # noqa: E402
from nikke_optimizer.simulator.evaluator import evaluate_by_names  # noqa: E402
from nikke_optimizer.simulator.event_loop import simulate_event_loop  # noqa: E402
from nikke_optimizer.simulator.match_sim import simulate_per_character  # noqa: E402


def parse_round_strip(strip: str) -> str | None:
    """Return 'left', 'right', or None given a round-strip text.

    Round strips read 'ROUND 01 LOSE WIN' (left LOSE, right WIN) or
    'ROUND 03 WIN V5 LOSE' (with V5 noise). We just look for which side
    is WIN.
    """
    if not strip:
        return None
    s = strip.upper()
    # find positions of WIN and LOSE
    win_match = re.search(r"\bWIN\b", s)
    lose_match = re.search(r"\bLOSE\b", s)
    if not win_match or not lose_match:
        return None
    return "left" if win_match.start() < lose_match.start() else "right"


def collect_rounds():
    """Pull (match_id, round_no, left_team, right_team, winner) tuples."""
    rounds: list[dict] = []
    eng = make_engine()
    with get_session(eng) as s:
        rows = s.exec(text("""
            SELECT pms.id, pms.match_id, pms.round_no, pms.kind,
                   pef.region_slug, pef.text, c.name
            FROM promo_match_screenshot pms
            JOIN promo_extracted_field pef ON pef.screenshot_id = pms.id
            LEFT JOIN character c ON c.id = pef.character_id
            WHERE pms.kind = 'results_duel'
            ORDER BY pms.match_id, pms.round_no, pms.id
        """)).all()
        # group rows by (match_id, round_no, screenshot_id)
        by_ss: dict[int, dict] = defaultdict(lambda: {
            "match_id": None,
            "round_no": None,
            "left": [None] * 5,
            "right": [None] * 5,
            "winner": None,
        })
        for ss_id, mid, rno, kind, slug, txt, char_name in rows:
            entry = by_ss[ss_id]
            entry["match_id"] = mid
            entry["round_no"] = rno
            m = re.match(r"^(left|right)\.char([1-5])\.name$", slug or "")
            if m and char_name:
                side = m.group(1)
                idx = int(m.group(2)) - 1
                entry[side][idx] = char_name
                continue
            # winner from round_strip on the same screenshot
            if slug and slug.endswith("_strip") and txt:
                w = parse_round_strip(txt)
                if w:
                    entry["winner"] = w
        # Also collect overview-level round strips (some screenshots are
        # results_overview which holds per-round result strips).
        ov_rows = s.exec(text("""
            SELECT pms.match_id, pef.region_slug, pef.text
            FROM promo_match_screenshot pms
            JOIN promo_extracted_field pef ON pef.screenshot_id = pms.id
            WHERE pms.kind = 'results_overview'
              AND pef.region_slug LIKE 'round%_strip'
        """)).all()
        overview_winners: dict[tuple[int, int], str] = {}
        for mid, slug, txt in ov_rows:
            m = re.match(r"^round(\d+)_strip$", slug or "")
            if not m:
                continue
            rno = int(m.group(1))
            w = parse_round_strip(txt or "")
            if w:
                overview_winners[(mid, rno)] = w
    # Compose final list. Skip rounds where both teams aren't fully
    # extracted or the winner is unknown.
    for entry in by_ss.values():
        winner = entry["winner"] or overview_winners.get(
            (entry["match_id"], entry["round_no"])
        )
        left = [c for c in entry["left"] if c]
        right = [c for c in entry["right"] if c]
        if winner and len(left) == 5 and len(right) == 5:
            rounds.append({
                "match_id": entry["match_id"],
                "round_no": entry["round_no"],
                "left": left,
                "right": right,
                "winner": winner,
            })
    return rounds


def run_validation():
    rounds = collect_rounds()
    print(f"Collected {len(rounds)} rounds with teams + winner.\n")

    skipped = 0
    el_correct = 0
    el_total = 0
    pc_correct = 0
    pc_total = 0
    detail: list[tuple] = []

    for r in rounds:
        # Skip rounds with unencoded characters (we can't simulate them)
        all_names = r["left"] + r["right"]
        unencoded = [n for n in all_names if registry.get(n) is None]
        if unencoded:
            skipped += 1
            continue
        try:
            left_eval = evaluate_by_names(r["left"])
            right_eval = evaluate_by_names(r["right"])
        except Exception as e:
            skipped += 1
            print(f"  evaluate fail M{r['match_id']}R{r['round_no']}: {e}")
            continue

        # NOTE: Champions Arena coin-flip — we don't know who attacked.
        # Run BOTH directions and call the prediction "correct" if EITHER
        # direction matches the actual winner. (Coarse — better would be
        # to use match-level attack/defense info, but for our coverage
        # this is consistent with how predict-mode works.)
        el_left_atk = simulate_event_loop(left_eval, right_eval)
        el_right_atk = simulate_event_loop(right_eval, left_eval)
        # Predicted winner: whoever wins more often across coin flips.
        # If both directions show the same winner, that's high confidence.
        left_wins_count = (1 if el_left_atk.attacker_wins else 0) + \
                          (0 if el_right_atk.attacker_wins else 1)
        el_pred = "left" if left_wins_count >= 1 else "right"
        # More precise: if both directions agree, use that. Otherwise lean
        # on net damage.
        if el_left_atk.attacker_wins == (not el_right_atk.attacker_wins):
            # Both directions show same winner.
            el_pred = "left" if el_left_atk.attacker_wins else "right"
        else:
            # Disagreement — go by net damage swing.
            net_left = (el_left_atk.attacker_total_damage
                        - el_left_atk.defender_total_damage)
            net_right = (el_right_atk.defender_total_damage
                         - el_right_atk.attacker_total_damage)
            el_pred = "left" if (net_left + net_right) > 0 else "right"

        pc_left_atk = simulate_per_character(left_eval, right_eval)
        pc_right_atk = simulate_per_character(right_eval, left_eval)
        if pc_left_atk.attacker_wins == (not pc_right_atk.attacker_wins):
            pc_pred = "left" if pc_left_atk.attacker_wins else "right"
        else:
            net_left = (pc_left_atk.attacker_total_damage
                        - pc_left_atk.defender_total_damage)
            net_right = (pc_right_atk.defender_total_damage
                         - pc_right_atk.attacker_total_damage)
            pc_pred = "left" if (net_left + net_right) > 0 else "right"

        el_total += 1
        pc_total += 1
        if el_pred == r["winner"]:
            el_correct += 1
        if pc_pred == r["winner"]:
            pc_correct += 1
        detail.append((r["match_id"], r["round_no"], r["winner"],
                       el_pred, pc_pred))

    print(f"Skipped {skipped} rounds (unencoded characters / eval errors)")
    print(f"Validated {el_total} rounds\n")
    print(f"{'event_loop':<14}: {el_correct}/{el_total} = "
          f"{100*el_correct/max(el_total,1):.1f}%")
    print(f"{'per_character':<14}: {pc_correct}/{pc_total} = "
          f"{100*pc_correct/max(pc_total,1):.1f}%")
    print()
    print("Detail (M=match, R=round, actual / event_loop / per_character):")
    for mid, rno, actual, el, pc in detail:
        el_mark = "✓" if el == actual else "✗"
        pc_mark = "✓" if pc == actual else "✗"
        print(f"  M{mid:<3} R{rno}  actual={actual:<5}  "
              f"event_loop={el:<5} {el_mark}  per_char={pc:<5} {pc_mark}")


if __name__ == "__main__":
    run_validation()
