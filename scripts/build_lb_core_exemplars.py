"""Pick one representative crop per LB/Core class for the audit page.

For each class key in ``EXEMPLAR_FILES`` (everything except
``unknown``), find the highest-confidence ``manually_corrected=False``
``%.lb_core`` row currently labeled with that key, crop the source
screenshot at the canonical region bbox, and save as PNG under
``src/nikke_optimizer/web/static/lb-core-icons/<key>.png``.

Run once. Outputs are committed to the repo. Re-run when the class
taxonomy changes or when a class gets a noticeably better exemplar.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from nikke_optimizer.data.db import init_db, make_engine  # noqa: E402
from nikke_optimizer.data.models import (  # noqa: E402
    PromoExtractedField,
    PromoMatchScreenshot,
)
from nikke_optimizer.roster.promo_tournament_lb_core_audit import (  # noqa: E402
    EXEMPLAR_FILES,
)
from nikke_optimizer.roster.promo_tournament_regions import PLAYER_LOADOUT  # noqa: E402

OUT_DIR = repo_root / "src" / "nikke_optimizer" / "web" / "static" / "lb-core-icons"
OUT_DIR.mkdir(parents=True, exist_ok=True)

LB_CORE_BBOX = {
    r.slug: r.bbox for r in PLAYER_LOADOUT if r.slug.endswith(".lb_core")
}


def main() -> int:
    engine = make_engine(None)
    init_db(engine)
    written = 0
    skipped: list[str] = []
    with Session(engine) as session:
        for class_key, fname in EXEMPLAR_FILES.items():
            row = session.exec(
                select(PromoExtractedField)
                .where(
                    PromoExtractedField.region_slug.like("%.lb_core"),
                    PromoExtractedField.normalized == class_key,
                )
                .order_by(PromoExtractedField.confidence.desc().nulls_last())
                .limit(1)
            ).first()
            if row is None:
                skipped.append(class_key)
                continue
            bbox = LB_CORE_BBOX.get(row.region_slug)
            shot = session.get(PromoMatchScreenshot, row.screenshot_id)
            if bbox is None or shot is None:
                skipped.append(class_key)
                continue
            try:
                img = Image.open(shot.file_path).convert("RGB")
            except OSError as exc:
                print(f"  open failed for {class_key}: {exc}")
                skipped.append(class_key)
                continue
            crop = img.crop(bbox)
            out = OUT_DIR / fname
            crop.save(out, "PNG")
            print(f"  wrote {class_key:8s} → {out.name}")
            written += 1
    if skipped:
        print(f"\nSkipped (no row in DB): {', '.join(skipped)}")
    print(f"\nWrote {written}/{len(EXEMPLAR_FILES)} exemplars to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
