# Bugfix Requirements Document

## Introduction

For generated reference images — the case where the pipeline fully controls the
camera — overlay/metadata channels are not all emitted correctly at generation
time. The SAM3 "twin-layers" instance-ID mask is already emitted as a proper,
separate instance-ID channel and works correctly. Depth (and any other overlay
data) is not: it is encoded into the visible RGB pixels of the image, or it is
missing entirely and must be re-derived later.

This is a defect because data hidden inside visible RGB pixels does not survive
lossy compression (JPEG, video encode, or any re-encode of the visible image).
Once that visible image is compressed, the smuggled overlay data is corrupted or
lost, so downstream deterministic unprojection of each cutout becomes unreliable.
Because the camera is fully controlled for generated reference images, the correct
behavior is to emit overlays "at birth" as real, separate, lossless auxiliary
channels (an EXR-style multi-channel image), exactly as the instance-ID mask
already is. With both instance-ID and depth present as real channels, each cutout
can be unprojected deterministically.

The fix is scoped to the generated reference-image emission path (fully controlled
camera). It must not change the separate monocular depth-estimation path used for
input photographs where the camera is not controlled by the pipeline, and it must
not disturb the already-correct instance-ID mask emission.

## Bug Analysis

### Current Behavior (Defect)

For generated reference images with a fully controlled camera, only the
instance-ID mask is emitted as a real channel; depth and other overlays are
smuggled into visible pixels or omitted.

1.1 WHEN the pipeline generates a reference image with a fully controlled camera THEN the system emits only the SAM3 instance-ID mask as a real auxiliary channel and does NOT emit depth as a real auxiliary channel at generation time.

1.2 WHEN depth or other overlay data is associated with a generated reference image THEN the system encodes that data into the visible RGB pixels, or omits it entirely, instead of writing it to a separate lossless channel.

1.3 WHEN a generated reference image (or a cutout derived from it) passes through any lossy image or video encode THEN the overlay data hidden in the visible pixels is corrupted or destroyed.

1.4 WHEN a downstream consumer attempts deterministic unprojection of a cutout THEN it cannot reliably obtain depth for that cutout, because the depth was destroyed by compression or was never emitted, making the unprojection unreliable.

### Expected Behavior (Correct)

Overlays are emitted "at birth" as real, separate, lossless auxiliary channels
alongside the existing instance-ID mask channel.

2.1 WHEN the pipeline generates a reference image with a fully controlled camera THEN the system SHALL emit depth as an explicit, separate auxiliary channel alongside the existing SAM3 instance-ID mask channel.

2.2 WHEN depth or any other overlay data is associated with a generated reference image THEN the system SHALL write it into a lossless multi-channel container (EXR-style) and SHALL NOT encode it into the visible RGB pixels.

2.3 WHEN a generated reference image and its auxiliary channels are persisted THEN the system SHALL store the overlay channels losslessly so that they survive any subsequent lossy encode of the visible RGB.

2.4 WHEN a downstream consumer performs deterministic unprojection of a cutout THEN it SHALL read the depth and instance-ID values directly from the lossless auxiliary channels and SHALL unproject each cutout deterministically.

### Unchanged Behavior (Regression Prevention)

The already-correct instance-ID emission, the appearance-only role of the Canon,
and the separate non-controlled-camera depth-estimation path must be preserved.

3.1 WHEN the pipeline emits SAM3 instance-ID masks for generated reference images THEN the system SHALL CONTINUE TO emit them as a proper instance-ID channel, unchanged.

3.2 WHEN object isolation produces RGBA cutouts THEN the system SHALL CONTINUE TO carry each object's instance mask in the alpha channel under the current quality gates.

3.3 WHEN depth is produced for an input photograph whose camera is NOT controlled by the pipeline (monocular estimation) THEN the system SHALL CONTINUE TO treat that depth as optional, non-authoritative evidence and SHALL NOT grant it spatial authority.

3.4 WHEN the Scene_Canon is generated THEN the system SHALL CONTINUE TO own appearance only (materials, lighting, identity), and depth or overlay channels SHALL NOT override MetricPlan spatial authority.

3.5 WHEN mesh generation prepares a cutout for an RGB-only encoder THEN the system SHALL CONTINUE TO composite the approved alpha onto a white background and discard hidden RGB as it does today.

3.6 WHEN the visible RGB of a generated reference image is consumed for appearance THEN the system SHALL CONTINUE TO produce the same visible RGB result as before the fix.
