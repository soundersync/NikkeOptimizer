"""Apple Vision feature-print embeddings (macOS).

Wraps `VNGenerateImageFeaturePrintRequest`, which produces a learned image
embedding (`VNFeaturePrintObservation`). Two observations expose
``computeDistance:toFeaturePrintObservation:error:`` returning a small float for
similar images and a large float for dissimilar ones.

This is far more discriminative than perceptual hashing for stylized character
art — phash collapses too many distinct characters to similar hashes.
"""

import io
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

try:
    import objc
    import Quartz
    import Vision
    from Foundation import NSData
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Vision feature embeddings require pyobjc; "
        "install pyobjc-framework-Vision pyobjc-framework-Quartz pyobjc-framework-Cocoa"
    ) from exc

log = logging.getLogger(__name__)


# pyobjc doesn't auto-detect that VNFeaturePrintObservation's
# `computeDistance:toFeaturePrintObservation:error:` has an output `float *`
# parameter — without this metadata registration, the call returns the BOOL
# but the float distance comes back as None. Registering once at module import
# is safe and idempotent.
objc.registerMetaDataForSelector(
    b"VNFeaturePrintObservation",
    b"computeDistance:toFeaturePrintObservation:error:",
    {
        "arguments": {
            2: {"type": b"^f", "type_modifier": b"o"},
            4: {"type": b"^@", "type_modifier": b"o"},
        }
    },
)


def _pil_to_cgimage(image: Image.Image) -> "Quartz.CGImageRef":
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    nsdata = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    provider = Quartz.CGDataProviderCreateWithCFData(nsdata)
    cgimage = Quartz.CGImageCreateWithPNGDataProvider(
        provider, None, True, Quartz.kCGRenderingIntentDefault
    )
    if cgimage is None:
        raise RuntimeError("failed to create CGImage from PIL image")
    return cgimage


class FeaturePrintEmbedder:
    """Compute VNFeaturePrintObservation embeddings for arbitrary images.

    The observations are opaque to Python — we keep them as native objects and
    use `compute_distance` to compare. For larger indexes we cache the raw data
    bytes (so embeddings can be persisted to disk later if needed).
    """

    def __init__(self, *, image_crop_and_scale_option: int = 0) -> None:
        # 0 = VNImageCropAndScaleOptionCenterCrop (default)
        # 1 = VNImageCropAndScaleOptionScaleFit
        # 2 = VNImageCropAndScaleOptionScaleFill
        self.image_crop_and_scale_option = image_crop_and_scale_option

    def embed_pil(self, image: Image.Image) -> "Vision.VNFeaturePrintObservation":
        if image.mode != "RGB":
            image = image.convert("RGB")
        cgimage = _pil_to_cgimage(image)
        request = Vision.VNGenerateImageFeaturePrintRequest.alloc().init()
        request.setImageCropAndScaleOption_(self.image_crop_and_scale_option)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            cgimage, None
        )
        success, error = handler.performRequests_error_([request], None)
        if not success:
            raise RuntimeError(f"feature-print failed: {error}")
        results = request.results() or []
        if not results:
            raise RuntimeError("feature-print returned no observations")
        return results[0]

    def embed_path(self, path: Path) -> "Vision.VNFeaturePrintObservation":
        return self.embed_pil(Image.open(path))

    @staticmethod
    def compute_distance(
        a: "Vision.VNFeaturePrintObservation",
        b: "Vision.VNFeaturePrintObservation",
    ) -> float:
        """Return the L2 distance between two embeddings.

        Smaller = more similar. Apple's docs say
        ``VNFeaturePrintObservation`` distances are unitless but consistent;
        in our calibration runs identical images give 0.0, same character /
        different skin gives 5–12, different characters cluster in 12–25.
        """
        ok, distance, error = b.computeDistance_toFeaturePrintObservation_error_(
            None, a, None
        )
        if not ok:
            raise RuntimeError(f"computeDistance failed: {error}")
        return float(distance)
