"""OCR engine abstraction.

We isolate the recognition backend behind a small interface so we can swap
implementations (Apple Vision on macOS, PaddleOCR cross-platform) without
touching the row segmenter or the importer orchestrator.

For each recognized text region we return a `TextRegion` with:
  - text: the recognized string
  - confidence: 0.0 - 1.0
  - bbox: (x, y, w, h) in pixel coordinates, top-left origin

Image input is a `numpy.ndarray` (H, W, 3) RGB or a `PIL.Image.Image`. The
backend handles conversion internally.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Protocol, Sequence, Tuple, Union

import numpy as np
from PIL import Image

ImageLike = Union[np.ndarray, Image.Image, str, Path]


@dataclass(frozen=True)
class TextRegion:
    text: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x, y, w, h), top-left origin, pixels

    @property
    def cx(self) -> float:
        return self.bbox[0] + self.bbox[2] / 2.0

    @property
    def cy(self) -> float:
        return self.bbox[1] + self.bbox[3] / 2.0


def _load_image(image: ImageLike) -> Image.Image:
    if isinstance(image, (str, Path)):
        return Image.open(image).convert("RGB")
    if isinstance(image, Image.Image):
        return image.convert("RGB") if image.mode != "RGB" else image
    if isinstance(image, np.ndarray):
        return Image.fromarray(image).convert("RGB")
    raise TypeError(f"unsupported image type: {type(image)!r}")


def preprocess_for_ocr(
    image: Image.Image, *, upscale: float = 2.0, sharpen: bool = True
) -> Image.Image:
    """Light preprocessing: upscale + optional sharpen.

    Stylized game UI text is small and often anti-aliased; upscaling 2x before
    OCR significantly improves recognition on tight numerals like 'OL roll' tiles.
    """
    from PIL import ImageFilter

    if upscale and upscale != 1.0:
        new_size = (int(image.width * upscale), int(image.height * upscale))
        image = image.resize(new_size, Image.LANCZOS)
    if sharpen:
        image = image.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=2))
    return image


class OCREngine(Protocol):
    """Backend interface. Implementations live in `_apple_vision.py`, `_paddle.py`."""

    def recognize(
        self, image: ImageLike, *, languages: Optional[Sequence[str]] = None
    ) -> list[TextRegion]: ...


_DEFAULT_ENGINE: Optional[OCREngine] = None


def get_default_engine() -> OCREngine:
    """Return a singleton default OCR engine, choosing per-platform.

    Order of preference:
      1. Apple Vision (macOS native, no large model download)
      2. PaddleOCR (cross-platform, requires `pip install nikke-copilot[paddle]`)
    """
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is not None:
        return _DEFAULT_ENGINE

    try:
        from ._apple_vision import AppleVisionEngine  # type: ignore

        _DEFAULT_ENGINE = AppleVisionEngine()
        return _DEFAULT_ENGINE
    except ImportError:
        pass
    try:
        from ._paddle import PaddleOCREngine  # type: ignore

        _DEFAULT_ENGINE = PaddleOCREngine()
        return _DEFAULT_ENGINE
    except ImportError as exc:
        raise RuntimeError(
            "no OCR engine available; install pyobjc-framework-Vision (macOS) "
            "or `pip install paddleocr paddlepaddle`"
        ) from exc


def recognize(
    image: ImageLike,
    *,
    engine: Optional[OCREngine] = None,
    preprocess: bool = True,
    languages: Optional[Sequence[str]] = None,
) -> list[TextRegion]:
    """Convenience wrapper: load → preprocess → engine.recognize.

    Returned `TextRegion.bbox` is always expressed in the *original* image's
    pixel coordinate space, even when preprocessing upscales the image internally.
    """
    pil = _load_image(image)
    orig_w, orig_h = pil.size
    if preprocess:
        pil = preprocess_for_ocr(pil)
    eng = engine or get_default_engine()
    regions = eng.recognize(pil, languages=languages)
    if preprocess and pil.size != (orig_w, orig_h):
        sx = orig_w / pil.size[0]
        sy = orig_h / pil.size[1]
        regions = [
            TextRegion(
                text=r.text,
                confidence=r.confidence,
                bbox=(
                    int(round(r.bbox[0] * sx)),
                    int(round(r.bbox[1] * sy)),
                    int(round(r.bbox[2] * sx)),
                    int(round(r.bbox[3] * sy)),
                ),
            )
            for r in regions
        ]
    return regions


def regions_in_bbox(
    regions: Iterable[TextRegion], bbox: Tuple[int, int, int, int]
) -> list[TextRegion]:
    """Filter `regions` whose center falls inside `bbox` (x, y, w, h, top-left)."""
    x, y, w, h = bbox
    return [r for r in regions if x <= r.cx <= x + w and y <= r.cy <= y + h]
