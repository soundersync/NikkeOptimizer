"""Phase 3 — battle simulator.

Currently scaffolding only:

  * ``dsl``     — structured representation of Nikke skills (Triggers,
                  Targets, Effects). The simulator will eventually consume
                  this; the optimizer can also use it for synergy detection.
  * ``library`` — hand-encoded skills for top-tier PvP Nikkes. Five are
                  encoded as proof of concept; the goal is ~50 to cover
                  ~95% of meta teams before running simulations.
  * ``registry``— central registry that loads every encoded character.

The simulator core (event queue, full-burst window, target selection,
buff stacking, RNG model, deterministic outcomes) is the next slice.
"""
