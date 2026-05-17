-- 0001 — ArenaMatch ⇄ RosterSnapshot linkage
--
-- Adds two nullable FK columns to ``arena_match`` so each captured
-- arena match can record which player snapshots its stats should be
-- resolved against. Required for Champions Arena season-locked
-- simulations: each match in a season references the snapshot of
-- the user and the opponent that was captured at season start.
--
-- For Champions v1 the existing ``RosterSnapshot`` schema
-- (``(season_number, player_username)`` unique key) is reused
-- unchanged — snapshots can be sparse (only the chars that played
-- in any of the 5 teams) or complete. No schema changes there.
--
-- See BACKLOG.md "Snapshot architecture — future extensions" for the
-- Rookie-Arena extension (snapshot_kind + snapshot_date columns).
--
-- Idempotent: skip whichever pieces already exist. Run via the
-- companion Python script (``apply_migrations.py``) which detects
-- existing columns + indexes and only applies missing pieces.

ALTER TABLE arena_match
    ADD COLUMN user_snapshot_id INTEGER
    REFERENCES roster_snapshot(id);

ALTER TABLE arena_match
    ADD COLUMN opponent_snapshot_id INTEGER
    REFERENCES roster_snapshot(id);

CREATE INDEX IF NOT EXISTS ix_arena_match_user_snapshot
    ON arena_match (user_snapshot_id);

CREATE INDEX IF NOT EXISTS ix_arena_match_opponent_snapshot
    ON arena_match (opponent_snapshot_id);
