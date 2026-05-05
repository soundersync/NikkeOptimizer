"""Phase-2 heuristic team optimizer.

Top-level architecture:

  * ``models``      — value objects shared across the pipeline
                      (CharacterView, TeamCandidate, ScoreBreakdown)
  * ``loader``      — pulls Character + OwnedCharacter from the DB into
                      CharacterView records
  * ``constraints`` — hard constraints (burst chain, team size). A team that
                      fails a hard constraint is unrankable.
  * ``scoring``     — soft scoring components (power, element, role mix,
                      synergy). Each returns a number; ``score_team`` sums
                      them with configurable weights.
  * ``search``      — beam search + greedy/local-search solvers that produce
                      the top-K teams under a scorer.

The Rookie Arena solver in ``rookie`` is the first concrete consumer. SP
Arena and Champions Arena will land in their own modules later — they reuse
the scorer but bring their own constraint topology.
"""
