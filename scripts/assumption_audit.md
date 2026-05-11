# Simulator constants — assumption audit

For each constant: current value, origin (where in code, why), level of evidence.
Filled in by research agent results.

## Burst chain & timing

| Constant | Current | Origin | Evidence | Verified value |
|---|---|---|---|---|
| `_BURST_CHAIN_STEP_SEC` | 1.0 s | timeline.py L79, initial commit | **PLACEHOLDER** (never grounded) | TBD |
| `DEFAULT_BURST_CHAIN_OFFSETS_SEC` | (10,11,12,13,14) | timeline.py L61 | Legacy fixed schedule | TBD |
| `DEFAULT_FULL_BURST_DURATION_SEC` | 10.0 s | timeline.py L199 | Anecdotal "10s window" | TBD |
| `DEFAULT_CYCLE_PERIOD_SEC` | 40.0 s | damage.py L161 | "~40s/cycle" anecdotal | TBD |
| `DEFAULT_FIRST_BURST_SEC` | 10.0 s | damage.py L166 | "Crown comp lands here" | Crown comp does ~6.5–8s per published data |

## Damage formula layers

| Constant | Current | Origin | Evidence | Verified value |
|---|---|---|---|---|
| `FULL_BURST_AVERAGE_MULTIPLIER` | 1.125 | damage.py L68 | `1 + 0.5 × 0.25 (25% uptime)` derivation | Real FB is +50% during 10s window; uptime depends on cycle |
| `ELEMENT_ADVANTAGE_AVERAGE` | 1.05 (fallback) | damage.py L78 | Steady-state proxy | +10% on weakness — per-pair calc now |
| `DEFAULT_CRIT_RATE_PCT` | 25.0 | damage.py L115 | Anecdotal "PvP avg" | Base PvP crit ≈ 15%; varies with buffs |
| `DEFAULT_CRIT_DAMAGE_PCT` | 50.0 | damage.py L117 | Anecdotal | NIKKE base crit dmg = +50% |
| `MIN_DAMAGE_FRACTION_THROUGH_DEF` | 0.05 | damage.py L121 | Published formula floor | Confirmed by nikke.gg |
| `MATCH_LENGTH_SEC` | 300.0 | damage.py L124 | In-game timeout | Confirmed (defender wins on timeout) |

## Weapon factors

`WEAPON_DAMAGE_PER_SECOND_FRACTION` (damage.py L140-158):
- AR 1.62, SMG 1.95, MG 1.40, SG 1.50, SR 1.28, RL 0.64
- Claimed "calibrated against nikke.gg/published damage formula" but I haven't been able to find published per-weapon DPS fractions on nikke.gg with these exact magnitudes
- These produce very high per-second damage when stacked with crit×FB×elem×range×charge multipliers

## Charge / range

| Constant | Current | Origin | Evidence | Verified value |
|---|---|---|---|---|
| `CHARGE_DAMAGE_DEFAULT_MULTIPLIER` | 2.5 (full-charge) | damage.py L138 | "+150% charge dmg" | SR=2.5× (+150%), RL=3.5× (+250%) per research |
| `CHARGE_DAMAGE_AVG_MULT` | 2.1 | damage.py L139 | Tuned for beta-29 fit | Should be derivable from charge time / shot rate |
| `EFFECTIVE_RANGE_BONUS` | 1.30 (SR only) | damage.py L152 | nikke.gg +30%, research said SR-only | Confirmed SR-only mid-range arena |

## DPS decay

| Constant | Current | Origin | Evidence | Verified value |
|---|---|---|---|---|
| `BURST_WINDOW_DURATION_SEC` | 10.0 s | match_sim.py L60 | Standard FB window | Likely correct |
| `POST_BURST_DPS_RETENTION` | 0.55 | match_sim.py L61 | "55% retention for Crown comps" | Anecdotal — needs verification |
| Pre-burst DPS factor | 1.0 (peak) | _dps_decay_factor | Doesn't penalize pre-chain | But snapshot has all team buffs baked in — this is wrong: pre-burst team has no team buffs yet |

## Burst gauge

`BURST_GEN_RATE_BY_WEAPON_PCT_PER_SEC` (timeline.py L70):
- SMG 1.6, AR 1.7, SR 2.0, MG 2.2, RL 2.8, SG 3.3
- Claimed calibrated so Crown comp (SMG/MG/MG/SR/SR) sums to 10/s
- Per nikke.gg published rates: SMG ~0.95, AR ~1.05, MG ~1.15, SR ~1.25, RL ~1.85, SG ~2.05 (rough — needs verification)

`BURST_GAUGE_SKILL_BONUS_PCT_PER_SEC` (timeline.py L87):
- Liter 2.0, Tia 1.5, Dorothy 1.6, Crown 1.0 (?), etc.
- Most values are "calibrated from community burst-gen breakdowns" but no specific source cited

## Role scaling

`_ROLE_DPS_SCALE` (match_sim.py):
- attacker 0.20, defender 0.08, supporter 0.04
- **Empirical fit** to beta-29 outcomes, no game-mechanics basis
- This is the BIGGEST hack — exists because simulator's peak-DPS × match-length overshoots reality

`_NAME_DPS_SCALE` (30+ chars):
- Per-character overrides, all empirical
- Mostly tuned to match beta-29 specific match outputs

## State machine factors (match_sim.py)

- SW:HA: 0.7 → 1.0 ramp over 5s, 1.10 in window, 0.95 outside — based on "Lock-On stacks" but specific values guessed
- Crown: 0.4 outside / 1.1 in-window — "Relax stack" model but uncalibrated
- Modernia: 0.5/1.0/0.8 — guesses
- Liberalio: 0.15/0.20/0.10 — heavily gated to make R4 work; not from game data
- Moran: 0.70 const — pose toggle approximation
- Cinderella: 0.65 const — hit-counter gate
- Drake: same as SW:HA — assumed similar Lock-On family

## Burst payload caps (`_BURST_MAG_OVERRIDE`)

25+ entries capping encoded burst magnitudes to "realistic averages". Each based on the observation that encoded magnitudes are the conditional MAX in-game values. Specific cap values are all empirical guesses tuned to beta-29.

## Identified gaps

1. **Burst sequencing** is fake (1s per slot, placeholder)
2. **Pre-burst DPS** treated same as in-burst (snapshot baked all buffs in)
3. **State machines** are constant-factor approximations, not actual stack tracking
4. **AOE bursts** treated as one-shot to one target then cascaded (focus-fire); real AOE is simultaneous per-enemy
5. **Charge mechanic** simplified — no shot-rate gating based on charge time
6. **Team buffs** that are burst-window-only (e.g. Liberalio S1 +160% ATK 3s) are baked into snapshot as steady-state — over-counts
7. **Match length** in sim often 60-90s; real often <10s for fast comps. Either DPS too low or HP/heal too high
