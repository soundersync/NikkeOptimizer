"""Seed the Doll / DollSkill / DollSkillPhase tables from ``doll_data.DOLL_CHECKPOINTS``.

Linearly interpolates intermediate phases between adjacent checkpoints
on a per-stat basis. Idempotent: re-running ``seed_dolls(session)``
re-populates from scratch (existing rows are cleared first so manually-
edited rows would be overwritten — change checkpoints in ``doll_data.py``
to make a permanent override).
"""

from __future__ import annotations

from typing import Iterable

from sqlmodel import Session, delete, select

from .doll_data import DOLL_CHECKPOINTS, DollEffect, DollSkillSpec, DollSpec
from .enums import Rarity, WeaponClass
from .models import Doll, DollSkill, DollSkillPhase


def interpolate_phase(
    phase: int, checkpoints: dict[int, list[DollEffect]]
) -> tuple[list[DollEffect], bool]:
    """Return ``(effects, interpolated)`` for a single phase.

    ``effects`` is the union of all stats appearing in any checkpoint, with
    magnitudes either copied verbatim (when ``phase`` is itself a
    checkpoint) or linearly interpolated between the two surrounding
    checkpoints. ``interpolated`` is False only when ``phase`` is exactly
    a checkpoint.

    Raises ``ValueError`` if ``phase`` falls outside the checkpoint range
    — the caller should skip such phases (e.g. SR skill 2 has no data
    for phases 1-5).
    """
    if phase in checkpoints:
        # Verbatim copy; no interpolation.
        return [dict(e) for e in checkpoints[phase]], False

    sorted_phases = sorted(checkpoints.keys())
    lo = max((p for p in sorted_phases if p < phase), default=None)
    hi = min((p for p in sorted_phases if p > phase), default=None)
    if lo is None or hi is None:
        raise ValueError(
            f"phase {phase} outside checkpoint range "
            f"[{sorted_phases[0]}..{sorted_phases[-1]}]"
        )

    lo_by_stat = {e["stat"]: e for e in checkpoints[lo]}
    hi_by_stat = {e["stat"]: e for e in checkpoints[hi]}
    span = hi - lo
    pos = (phase - lo) / span

    def _emit(stat: str, lo_mag: float, hi_mag: float, direction: str | None) -> DollEffect:
        mag = lo_mag + (hi_mag - lo_mag) * pos
        out: DollEffect = {"stat": stat, "magnitude": round(mag, 4)}
        if direction:
            out["direction"] = direction
        return out

    out: list[DollEffect] = []
    seen: set[str] = set()
    for stat, lo_e in lo_by_stat.items():
        hi_e = hi_by_stat.get(stat, lo_e)
        out.append(_emit(stat, lo_e["magnitude"], hi_e["magnitude"], lo_e.get("direction")))
        seen.add(stat)
    for stat, hi_e in hi_by_stat.items():
        if stat in seen:
            continue
        # Stat appears only at upper checkpoint; ramp from 0.
        out.append(_emit(stat, 0.0, hi_e["magnitude"], hi_e.get("direction")))

    return out, True


def expand_skill_phases(
    skill_spec: DollSkillSpec, max_phase: int
) -> list[tuple[int, list[DollEffect], bool]]:
    """Yield ``(phase, effects, interpolated)`` rows for one skill.

    Skips phases below the lowest checkpoint (e.g. Grounding Pillar has
    no data for phases 1-5 because skill 2 unlocks at phase 6).
    """
    checkpoints = skill_spec["checkpoints"]
    min_phase = min(checkpoints.keys())
    rows: list[tuple[int, list[DollEffect], bool]] = []
    for phase in range(min_phase, max_phase + 1):
        effects, interpolated = interpolate_phase(phase, checkpoints)
        rows.append((phase, effects, interpolated))
    return rows


def _max_phase_for(rarity: str) -> int:
    """R dolls cap at phase 5; SR dolls cap at phase 15."""
    return 5 if rarity == "R" else 15


def seed_dolls(
    session: Session,
    *,
    specs: Iterable[DollSpec] | None = None,
) -> dict[str, int]:
    """Replace doll catalog with rows derived from ``specs``.

    Returns a count summary dict ``{"dolls": N, "skills": M, "phases": K}``.
    """
    specs_list = list(specs) if specs is not None else list(DOLL_CHECKPOINTS)

    # Wipe existing rows. Cascade rules on Doll → DollSkill → DollSkillPhase
    # take care of the children, but we delete explicitly here so the
    # delete works even when SQLAlchemy can't see in-memory relationships.
    session.exec(delete(DollSkillPhase))  # type: ignore[arg-type]
    session.exec(delete(DollSkill))  # type: ignore[arg-type]
    session.exec(delete(Doll))  # type: ignore[arg-type]
    session.commit()

    n_dolls = n_skills = n_phases = 0
    for spec in specs_list:
        max_phase = _max_phase_for(spec["rarity"])
        doll = Doll(
            name=spec["name"],
            weapon_class=WeaponClass(spec["weapon_class"]),
            rarity=Rarity(spec["rarity"]),
            max_phase=max_phase,
        )
        session.add(doll)
        session.flush()  # populate doll.id
        n_dolls += 1

        for skill_spec in spec["skills"]:
            skill = DollSkill(
                doll_id=doll.id,
                skill_index=skill_spec["skill_index"],
                name=skill_spec["name"],
                trigger_text=skill_spec.get("trigger"),
            )
            session.add(skill)
            session.flush()
            n_skills += 1

            for phase, effects, interpolated in expand_skill_phases(
                skill_spec, max_phase
            ):
                session.add(
                    DollSkillPhase(
                        skill_id=skill.id,
                        phase=phase,
                        effects=list(effects),
                        interpolated=interpolated,
                    )
                )
                n_phases += 1

    session.commit()
    return {"dolls": n_dolls, "skills": n_skills, "phases": n_phases}


def lookup_phase(
    session: Session,
    *,
    weapon_class: str,
    rarity: str,
    skill_index: int,
    phase: int,
) -> DollSkillPhase | None:
    """Convenience read: fetch one (doll, skill_index, phase) row.

    Returns ``None`` when the doll isn't in the catalog or the phase has
    no data for that skill (e.g. Grounding Pillar at phase < 6).
    """
    doll = session.exec(
        select(Doll)
        .where(Doll.weapon_class == WeaponClass(weapon_class))
        .where(Doll.rarity == Rarity(rarity))
    ).first()
    if doll is None:
        return None
    skill = session.exec(
        select(DollSkill)
        .where(DollSkill.doll_id == doll.id)
        .where(DollSkill.skill_index == skill_index)
    ).first()
    if skill is None:
        return None
    return session.exec(
        select(DollSkillPhase)
        .where(DollSkillPhase.skill_id == skill.id)
        .where(DollSkillPhase.phase == phase)
    ).first()
