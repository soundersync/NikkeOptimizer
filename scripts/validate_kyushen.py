"""Focused validation against KYUSHEN's two captured matches.

Pulls all rounds where KYUSHEN played and runs both simulators
(simulate_event_loop with DSL effect scheduling, simulate_per_character)
in both attack/defense directions. Reports outcome prediction + the
simulated damage and heal numbers so we can see whether the new
DSL-driven scheduling improved outcome accuracy AND whether the
absolute damage/heal values changed.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import text  # noqa: E402

from nikke_optimizer.data.db import get_session, make_engine  # noqa: E402
from nikke_optimizer.simulator import registry  # noqa: E402
from nikke_optimizer.simulator.evaluator import evaluate_by_names  # noqa: E402
from nikke_optimizer.simulator.event_loop import simulate_event_loop  # noqa: E402
from nikke_optimizer.simulator.match_sim import simulate_per_character  # noqa: E402


def parse_strip(strip: str) -> str | None:
    if not strip:
        return None
    s = strip.upper()
    win_m = re.search(r"\bWIN\b", s)
    lose_m = re.search(r"\bLOSE\b", s)
    if not win_m or not lose_m:
        return None
    return "left" if win_m.start() < lose_m.start() else "right"


def collect_kyushen_rounds():
    """Find every round where KYUSHEN played, return (match, round, left, right, winner)."""
    eng = make_engine()
    with get_session(eng) as s:
        # Find matches with KYUSHEN
        rows = s.exec(text("""
            SELECT DISTINCT pms.match_id
            FROM promo_extracted_field pef
            JOIN promo_match_screenshot pms ON pms.id = pef.screenshot_id
            WHERE pef.text = 'KYUSHEN' AND pef.region_slug IN ('left_name', 'right_name')
        """)).all()
        match_ids = [r[0] for r in rows]
        # Find KYUSHEN's side per match
        side_per_match = {}
        for mid in match_ids:
            row = s.exec(text(f"""
                SELECT pef.region_slug
                FROM promo_extracted_field pef
                JOIN promo_match_screenshot pms ON pms.id = pef.screenshot_id
                WHERE pms.match_id = {mid} AND pef.text = 'KYUSHEN'
                  AND pef.region_slug IN ('left_name', 'right_name') LIMIT 1
            """)).first()
            if row:
                side_per_match[mid] = row[0].split("_")[0]  # left/right
        # Get round outcomes (overview screenshots)
        outcomes: dict[tuple[int, int], str] = {}
        rows = s.exec(text("""
            SELECT pms.match_id, pef.region_slug, pef.text
            FROM promo_extracted_field pef
            JOIN promo_match_screenshot pms ON pms.id = pef.screenshot_id
            WHERE pms.kind = 'results_overview' AND pef.region_slug LIKE 'round%_strip'
        """)).all()
        for mid, slug, txt in rows:
            if mid not in match_ids:
                continue
            m = re.match(r"round(\d+)_strip", slug)
            if not m:
                continue
            rno = int(m.group(1))
            w = parse_strip(txt or "")
            if w:
                outcomes[(mid, rno)] = w
        # Get teams per round
        teams: dict[tuple[int, int], dict] = defaultdict(
            lambda: {"left": [None] * 5, "right": [None] * 5}
        )
        rows = s.exec(text("""
            SELECT pms.match_id, pms.round_no, pef.region_slug, c.name
            FROM promo_extracted_field pef
            JOIN promo_match_screenshot pms ON pms.id = pef.screenshot_id
            JOIN character c ON c.id = pef.character_id
            WHERE pms.kind = 'results_duel' AND pef.region_slug LIKE '%char%name'
        """)).all()
        for mid, rno, slug, cname in rows:
            if mid not in match_ids:
                continue
            m = re.match(r"^(left|right)\.char([1-5])\.name$", slug)
            if not m:
                continue
            side = m.group(1)
            idx = int(m.group(2)) - 1
            teams[(mid, rno)][side][idx] = cname

    out = []
    for (mid, rno), t in sorted(teams.items()):
        left = [c for c in t["left"] if c]
        right = [c for c in t["right"] if c]
        winner = outcomes.get((mid, rno))
        if not winner or len(left) != 5 or len(right) != 5:
            continue
        kyushen_side = side_per_match.get(mid, "?")
        kyushen_won = (winner == kyushen_side)
        out.append({
            "match_id": mid,
            "round": rno,
            "kyushen_side": kyushen_side,
            "left": left,
            "right": right,
            "winner": winner,
            "kyushen_won": kyushen_won,
        })
    return out


def fmt_M(n: float) -> str:
    return f"{n/1e6:.1f}M"


def main():
    rounds = collect_kyushen_rounds()
    print(f"Pulled {len(rounds)} KYUSHEN rounds.\n")

    el_correct = 0
    pc_correct = 0
    skipped = 0

    print(f"{'Match':<6} {'Side':<5} {'Actual':<8} "
          f"{'event_loop':<22} {'per_char':<22}")
    print("-" * 90)

    for r in rounds:
        all_names = r["left"] + r["right"]
        unencoded = [n for n in all_names if registry.get(n) is None]
        if unencoded:
            print(f"M{r['match_id']:<3}R{r['round']}  "
                  f"{r['kyushen_side']:<5} {r['winner']:<8} "
                  f"SKIP (unencoded: {','.join(unencoded[:3])})")
            skipped += 1
            continue
        try:
            le = evaluate_by_names(r["left"])
            re_ = evaluate_by_names(r["right"])
        except Exception as e:
            print(f"  evaluate fail: {e}")
            skipped += 1
            continue

        # Run both directions for each sim
        el_l = simulate_event_loop(le, re_)
        el_r = simulate_event_loop(re_, le)
        pc_l = simulate_per_character(le, re_)
        pc_r = simulate_per_character(re_, le)

        # Predicted winner: agreement → use that, else net damage tiebreak
        def pick(left_atk, right_atk):
            if left_atk.attacker_wins == (not right_atk.attacker_wins):
                return "left" if left_atk.attacker_wins else "right"
            net_l = left_atk.attacker_total_damage - left_atk.defender_total_damage
            net_r = right_atk.defender_total_damage - right_atk.attacker_total_damage
            return "left" if (net_l + net_r) > 0 else "right"

        el_pred = pick(el_l, el_r)
        pc_pred = pick(pc_l, pc_r)

        actual_label = (
            f"{r['winner']:<5} ({'KY✓' if r['kyushen_won'] else 'KY✗'})"
        )
        el_ok = "✓" if el_pred == r["winner"] else "✗"
        pc_ok = "✓" if pc_pred == r["winner"] else "✗"
        if el_pred == r["winner"]:
            el_correct += 1
        if pc_pred == r["winner"]:
            pc_correct += 1
        print(f"M{r['match_id']:<3}R{r['round']}  "
              f"{r['kyushen_side']:<5} {actual_label:<10} "
              f"{el_pred:<5} {el_ok}  ({fmt_M(el_l.attacker_total_damage)}/"
              f"{fmt_M(el_l.defender_total_damage)} {el_l.match_ended_at_sec:.0f}s)  "
              f"{pc_pred:<5} {pc_ok}  ({fmt_M(pc_l.attacker_total_damage)}/"
              f"{fmt_M(pc_l.defender_total_damage)} {pc_l.match_ended_at_sec:.0f}s)")

    n = len(rounds) - skipped
    print(f"\nKYUSHEN-rounds summary ({n} valid, {skipped} skipped):")
    print(f"  event_loop    : {el_correct}/{n} = "
          f"{100*el_correct/max(n,1):.0f}%")
    print(f"  per_character : {pc_correct}/{n} = "
          f"{100*pc_correct/max(n,1):.0f}%")

    # Detailed view of one round — show all sim numbers
    if n > 0:
        sample = next(r for r in rounds
                      if not [c for c in r["left"]+r["right"]
                              if registry.get(c) is None])
        print(f"\n=== Detail: M{sample['match_id']}R{sample['round']} ===")
        print(f"Left ({sample['kyushen_side']}=KYUSHEN if matches): "
              f"{sample['left']}")
        print(f"Right: {sample['right']}")
        print(f"Actual winner: {sample['winner']}")
        le = evaluate_by_names(sample["left"])
        re_ = evaluate_by_names(sample["right"])
        print(f"\nLeft  team:  DPS={fmt_M(le.dps_estimate)}  EHP="
              f"{fmt_M(le.ehp_estimate)}  burst={fmt_M(le.burst_payload)}  "
              f"shield={fmt_M(le.total_shield)}")
        print(f"Right team:  DPS={fmt_M(re_.dps_estimate)}  EHP="
              f"{fmt_M(re_.ehp_estimate)}  burst={fmt_M(re_.burst_payload)}  "
              f"shield={fmt_M(re_.total_shield)}")
        for label, fn in [("event_loop", simulate_event_loop),
                          ("per_char  ", simulate_per_character)]:
            res = fn(le, re_)
            print(f"\n{label} (left attacks):")
            print(f"  attacker_wins={res.attacker_wins} ended={res.match_ended_at_sec:.1f}s")
            print(f"  damage:  attacker={fmt_M(res.attacker_total_damage)}  "
                  f"defender={fmt_M(res.defender_total_damage)}")
            living_a = getattr(res, "attacker_living_at_end", None)
            living_d = getattr(res, "defender_living_at_end", None)
            if living_a is not None:
                print(f"  living:  attacker={living_a}  defender={living_d}")
            first_a = getattr(res, "a_first_burst_at", None)
            first_d = getattr(res, "d_first_burst_at", None)
            if first_a is not None:
                print(f"  first burst:  attacker={first_a:.1f}s  defender={first_d:.1f}s")


if __name__ == "__main__":
    main()
