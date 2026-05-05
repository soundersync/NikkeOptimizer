"""Import cube screenshots into the local DB.

For each image in a directory, runs the cube extractor, then upserts a
``Cube`` row keyed by name. The user can re-run the import safely — it
overwrites existing fields with the latest extraction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlmodel import select

from ..data.db import get_session, init_db, make_engine
from ..data.models import Cube
from .cube_extractor import CubeExtraction, extract_cube

log = logging.getLogger(__name__)


@dataclass
class CubeImportReport:
    files_seen: int = 0
    upserted: int = 0
    incomplete: int = 0
    skipped: int = 0
    extractions: list[CubeExtraction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        log.warning(msg)
        self.warnings.append(msg)

    def to_dict(self) -> dict:
        return {
            "files_seen": self.files_seen,
            "upserted": self.upserted,
            "incomplete": self.incomplete,
            "skipped": self.skipped,
            "warnings": self.warnings,
        }


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def import_cubes(
    directory: Path,
    *,
    db_path: Optional[Path] = None,
    require_complete: bool = False,
) -> CubeImportReport:
    """Import every cube image under ``directory`` into the DB.

    When ``require_complete`` is True, only cubes whose extractor returned
    name + level + all three stats + equipping_count_owned are persisted.
    Defaults to False so partial extractions still create stub rows that
    can be hand-edited.
    """
    engine = make_engine(db_path)
    init_db(engine)
    report = CubeImportReport()

    paths = sorted(
        p for p in directory.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES
    )
    report.files_seen = len(paths)

    with get_session(engine) as session:
        for path in paths:
            try:
                extraction = extract_cube(path)
            except Exception as exc:  # noqa: BLE001
                report.skipped += 1
                report.warn(f"{path.name}: extractor crashed: {exc}")
                continue

            report.extractions.append(extraction)

            if extraction.name is None:
                report.skipped += 1
                report.warn(f"{path.name}: no cube name detected")
                continue
            if not extraction.is_complete:
                report.incomplete += 1
                missing = [
                    f for f, v in (
                        ("level", extraction.level),
                        ("atk", extraction.atk),
                        ("hp", extraction.hp),
                        ("def", extraction.def_),
                        ("owned_count", extraction.equipping_count_owned),
                    ) if v is None
                ]
                report.warn(
                    f"{path.name}: incomplete extraction for {extraction.name!r}; "
                    f"missing {missing}"
                )
                if require_complete:
                    continue

            existing = session.exec(
                select(Cube).where(Cube.name == extraction.name)
            ).one_or_none()
            if existing is None:
                cube = Cube(
                    name=extraction.name,
                    level=extraction.level,
                    atk=extraction.atk,
                    hp=extraction.hp,
                    def_=extraction.def_,
                    equipping_count_equipped=extraction.equipping_count_equipped,
                    equipping_count_owned=extraction.equipping_count_owned,
                    source_screenshot=str(path),
                )
                session.add(cube)
            else:
                # Only overwrite when we have a value — keeps old data when
                # the latest screenshot has a missing field.
                if extraction.level is not None:
                    existing.level = extraction.level
                if extraction.atk is not None:
                    existing.atk = extraction.atk
                if extraction.hp is not None:
                    existing.hp = extraction.hp
                if extraction.def_ is not None:
                    existing.def_ = extraction.def_
                if extraction.equipping_count_equipped is not None:
                    existing.equipping_count_equipped = extraction.equipping_count_equipped
                if extraction.equipping_count_owned is not None:
                    existing.equipping_count_owned = extraction.equipping_count_owned
                existing.source_screenshot = str(path)
            report.upserted += 1
        session.commit()

    return report
