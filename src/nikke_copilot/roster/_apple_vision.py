"""Apple Vision OCR backend (macOS).

Uses VNRecognizeTextRequest with the 'accurate' recognition level — best for
the small, stylized numerals that appear on Nikke roster tiles.

Coordinate convention conversion: Vision returns normalized bboxes with the
origin in the *bottom-left*. We convert to absolute pixel coordinates with the
origin in the *top-left* to match the rest of the pipeline (PIL/OpenCV).
"""

from __future__ import annotations

import io
from typing import Optional, Sequence

import numpy as np
from PIL import Image

try:
    import Quartz
    import Vision
    from Foundation import NSData
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Apple Vision backend requires pyobjc; "
        "install pyobjc-framework-Vision pyobjc-framework-Quartz pyobjc-framework-Cocoa"
    ) from exc

from .ocr import ImageLike, TextRegion, _load_image


def _pil_to_cgimage(image: Image.Image) -> "Quartz.CGImageRef":
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    nsdata = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    provider = Quartz.CGDataProviderCreateWithCFData(nsdata)
    cgimage = Quartz.CGImageCreateWithPNGDataProvider(provider, None, True, Quartz.kCGRenderingIntentDefault)
    if cgimage is None:
        raise RuntimeError("failed to create CGImage from PIL image")
    return cgimage


class AppleVisionEngine:
    """OCR engine wrapping VNRecognizeTextRequest."""

    def __init__(
        self,
        *,
        recognition_level: str = "accurate",
        uses_language_correction: bool = False,
        minimum_text_height: float = 0.0,
    ) -> None:
        if recognition_level not in ("accurate", "fast"):
            raise ValueError("recognition_level must be 'accurate' or 'fast'")
        self.recognition_level = recognition_level
        self.uses_language_correction = uses_language_correction
        self.minimum_text_height = minimum_text_height

    def recognize(
        self, image: ImageLike, *, languages: Optional[Sequence[str]] = None
    ) -> list[TextRegion]:
        pil = _load_image(image)
        width, height = pil.size
        cgimage = _pil_to_cgimage(pil)

        request = Vision.VNRecognizeTextRequest.alloc().init()
        if self.recognition_level == "accurate":
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        else:
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast)
        request.setUsesLanguageCorrection_(self.uses_language_correction)
        request.setMinimumTextHeight_(self.minimum_text_height)
        if languages:
            request.setRecognitionLanguages_(list(languages))

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cgimage, None)
        success, error = handler.performRequests_error_([request], None)
        if not success:
            raise RuntimeError(f"Vision OCR failed: {error}")

        results = request.results() or []
        regions: list[TextRegion] = []
        for obs in results:
            candidates = obs.topCandidates_(1)
            if not candidates:
                continue
            top = candidates[0]
            text = str(top.string())
            confidence = float(top.confidence())
            bb = obs.boundingBox()  # CGRect in normalized [0,1], origin bottom-left
            nx, ny, nw, nh = bb.origin.x, bb.origin.y, bb.size.width, bb.size.height
            x = int(nx * width)
            w = int(nw * width)
            h = int(nh * height)
            # convert origin to top-left
            y = int((1.0 - ny - nh) * height)
            regions.append(TextRegion(text=text, confidence=confidence, bbox=(x, y, w, h)))
        return regions
