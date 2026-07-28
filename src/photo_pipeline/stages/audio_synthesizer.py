"""Audio Synthesizer — per-object impact sound generation.

Produces a WAV impact sound for each segmented object. Tries ComfyUI audio
nodes first; on failure, falls back to a material-based sound bank lookup.
If both methods fail, assigns a generic default impact sound.

Material estimation uses a color histogram heuristic on the Object_PNG to
classify objects into {wood, metal, glass, fabric, ceramic, plastic}.

All output WAV files are normalized to -3dBFS peak, mono, 44100Hz, 16-bit,
with duration clamped to [0.1, 2.0] seconds.

Pure computation functions (estimate_material, normalize_audio) are separated
from ComfyUI orchestration for independent testability.
"""

from __future__ import annotations

import logging
import shutil
import struct
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
)
from src.photo_pipeline.models import (
    AudioResult,
    PhotoPipelineConfig,
)
from src.photo_pipeline.workflows import load_workflow

logger = logging.getLogger(__name__)

# Sound bank directory relative to project root
_SOUND_BANK_DIR = Path(__file__).resolve().parents[3] / "assets" / "sound_bank"

# Valid material categories
VALID_MATERIALS = frozenset({"wood", "metal", "glass", "fabric", "ceramic", "plastic"})

# Material-to-WAV filename mapping
_MATERIAL_WAV_MAP: dict[str, str] = {
    "wood": "wood_impact.wav",
    "metal": "metal_impact.wav",
    "glass": "glass_impact.wav",
    "fabric": "fabric_impact.wav",
    "ceramic": "ceramic_impact.wav",
    "plastic": "plastic_impact.wav",
}

# Target audio constraints
SAMPLE_RATE = 44100
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
MIN_DURATION_S = 0.1
MAX_DURATION_S = 2.0
TARGET_DBFS = -3.0


# ---------------------------------------------------------------------------
# Pure helper functions (testable without ComfyUI)
# ---------------------------------------------------------------------------


def estimate_material(object_png_path: Path) -> str:
    """Classify an object into a material category based on color heuristic.

    Analyzes the average color of non-transparent pixels in the Object_PNG
    and uses a simplified color-space heuristic to estimate the material:

    - Warm browns (high R, moderate G, low B, low saturation) → wood
    - Gray/silver (low saturation, medium-high lightness) → metal
    - Bright with high saturation in blue/cyan range → glass
    - Soft/muted colors with very low saturation → fabric
    - Default → plastic

    Parameters
    ----------
    object_png_path : Path
        Path to the isolated RGBA Object_PNG.

    Returns
    -------
    str
        Material category: one of wood, metal, glass, fabric, ceramic, plastic.
    """
    try:
        img = Image.open(object_png_path).convert("RGBA")
        data = np.array(img)
    except Exception:
        logger.warning("Could not open %s for material estimation, defaulting to plastic", object_png_path)
        return "plastic"

    # Get non-transparent pixels
    alpha = data[:, :, 3]
    opaque_mask = alpha > 0

    if not np.any(opaque_mask):
        return "plastic"

    rgb = data[:, :, :3].astype(np.float64)
    r = rgb[:, :, 0][opaque_mask]
    g = rgb[:, :, 1][opaque_mask]
    b = rgb[:, :, 2][opaque_mask]

    avg_r = float(np.mean(r))
    avg_g = float(np.mean(g))
    avg_b = float(np.mean(b))

    # Compute HSL-like metrics
    max_c = max(avg_r, avg_g, avg_b)
    min_c = min(avg_r, avg_g, avg_b)
    lightness = (max_c + min_c) / 2.0
    chroma = max_c - min_c

    # Saturation (HSL-style)
    if lightness == 0.0 or lightness == 255.0:
        saturation = 0.0
    else:
        saturation = chroma / (255.0 - abs(2.0 * lightness - 255.0)) if (255.0 - abs(2.0 * lightness - 255.0)) > 0 else 0.0

    # Classification heuristic
    # Warm browns → wood: R > G > B, moderate saturation, warmth
    warmth = avg_r - avg_b  # positive = warm
    if warmth > 40 and avg_r > avg_g > avg_b and saturation > 0.15 and saturation < 0.7:
        return "wood"

    # Gray/silver → metal: very low saturation, medium-high lightness
    if saturation < 0.1 and 80 < lightness < 220:
        return "metal"

    # Bright with transparency hue → glass: high lightness, moderate-high saturation in blue/cyan
    if lightness > 160 and avg_b > avg_r and saturation > 0.2:
        return "glass"

    # Very low saturation with low-medium lightness → fabric
    if saturation < 0.15 and lightness < 160:
        return "fabric"

    # Earthy tones with moderate saturation → ceramic
    if 0.15 <= saturation <= 0.5 and warmth > 20 and lightness < 180:
        # Distinguish from wood by lower warmth differential
        if warmth < 40:
            return "ceramic"

    # Default to plastic
    return "plastic"


def lookup_sound_bank(material: str, sound_bank_dir: Path | None = None) -> Path | None:
    """Map a material category to the corresponding WAV file in the sound bank.

    Parameters
    ----------
    material : str
        Material category (wood, metal, glass, fabric, ceramic, plastic).
    sound_bank_dir : Path | None
        Override for the sound bank directory (used in testing).
        Defaults to assets/sound_bank/.

    Returns
    -------
    Path | None
        Path to the WAV file if it exists, None otherwise.
    """
    bank_dir = sound_bank_dir or _SOUND_BANK_DIR

    filename = _MATERIAL_WAV_MAP.get(material)
    if filename is None:
        return None

    wav_path = bank_dir / filename
    if wav_path.exists():
        return wav_path
    return None


def normalize_audio(wav_path: Path, target_dbfs: float = TARGET_DBFS) -> None:
    """Normalize a WAV file's peak amplitude to the target dBFS in-place.

    Reads the WAV as 16-bit PCM samples, computes peak amplitude, scales
    all samples to achieve the target peak dBFS, and writes back.

    Parameters
    ----------
    wav_path : Path
        Path to the WAV file to normalize (modified in-place).
    target_dbfs : float
        Target peak amplitude in dBFS (default -3.0).

    Notes
    -----
    If the file contains only silence (all zero samples), no modification
    is performed. The WAV is re-written as mono, 44100Hz, 16-bit PCM.
    """
    # Read WAV data
    with wave.open(str(wav_path), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        frame_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_data = wf.readframes(n_frames)

    if n_frames == 0:
        return

    # Convert to numpy array of int16
    if sample_width == 2:
        samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float64)
    elif sample_width == 1:
        samples = np.frombuffer(raw_data, dtype=np.uint8).astype(np.float64)
        samples = (samples - 128.0) * 256.0  # Convert to int16 range
    elif sample_width == 4:
        samples = np.frombuffer(raw_data, dtype=np.int32).astype(np.float64)
        samples = samples / 65536.0  # Scale to int16 range
    else:
        logger.warning("Unsupported sample width %d, skipping normalization", sample_width)
        return

    # If multi-channel, downmix to mono by averaging channels
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    # Find peak amplitude
    peak = np.max(np.abs(samples))
    if peak == 0:
        # All silence, nothing to normalize
        return

    # Compute target peak in linear scale
    # dBFS is referenced to full scale (32767 for 16-bit)
    # target_linear = 10^(target_dbfs / 20) * 32767
    target_linear = (10.0 ** (target_dbfs / 20.0)) * 32767.0

    # Scale samples
    scale_factor = target_linear / peak
    samples = samples * scale_factor

    # Clip to int16 range
    samples = np.clip(samples, -32768, 32767).astype(np.int16)

    # Enforce duration constraints
    target_rate = SAMPLE_RATE
    min_samples = int(MIN_DURATION_S * target_rate)
    max_samples = int(MAX_DURATION_S * target_rate)

    # Resample if needed
    if frame_rate != target_rate:
        # Simple resampling via interpolation
        original_duration = len(samples) / frame_rate
        new_n_samples = int(original_duration * target_rate)
        indices = np.linspace(0, len(samples) - 1, new_n_samples)
        samples = np.interp(indices, np.arange(len(samples)), samples.astype(np.float64))
        samples = np.clip(samples, -32768, 32767).astype(np.int16)

    # Enforce duration bounds
    if len(samples) < min_samples:
        # Pad with silence
        padding = np.zeros(min_samples - len(samples), dtype=np.int16)
        samples = np.concatenate([samples, padding])
    elif len(samples) > max_samples:
        # Truncate
        samples = samples[:max_samples]

    # Write normalized WAV
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(samples.tobytes())


# ---------------------------------------------------------------------------
# AudioSynthesizer class — orchestrates ComfyUI audio + sound bank fallback
# ---------------------------------------------------------------------------


class AudioSynthesizer:
    """Per-object impact sound generation with ComfyUI + sound bank fallback.

    Attempts ComfyUI audio synthesis first. On failure, falls back to the
    material-based sound bank. If both fail, uses a generic default impact.

    Parameters
    ----------
    client : ComfyUIClient
        Initialized async HTTP client for ComfyUI interaction.
    output_dir : Path
        Base output directory for this session's audio artifacts.
    sound_bank_dir : Path | None
        Override for the sound bank directory (defaults to assets/sound_bank/).
    """

    def __init__(
        self,
        client: ComfyUIClient,
        output_dir: Path,
        sound_bank_dir: Path | None = None,
    ) -> None:
        self.client = client
        self.output_dir = output_dir
        self.sound_bank_dir = sound_bank_dir or _SOUND_BANK_DIR

    async def synthesize(
        self,
        object_png: Path,
        mask_id: str,
        config: PhotoPipelineConfig,
    ) -> AudioResult:
        """Synthesize an impact sound for a segmented object.

        Workflow:
        1. Estimate material from Object_PNG visual features
        2. Try ComfyUI audio synthesis (if available)
        3. Fall back to sound bank lookup
        4. Fall back to default generic impact

        Parameters
        ----------
        object_png : Path
            Path to the isolated RGBA Object_PNG.
        mask_id : str
            Unique mask identifier for this object.
        config : PhotoPipelineConfig
            Pipeline configuration.

        Returns
        -------
        AudioResult
            Result with WAV path, method used, duration, and material category.
        """
        obj_dir = self.output_dir / "objects"
        obj_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Estimate material
        material = estimate_material(object_png)

        # Step 2: Try ComfyUI audio nodes
        wav_path = await self._try_comfyui_audio(mask_id, material, obj_dir)
        if wav_path is not None:
            normalize_audio(wav_path, TARGET_DBFS)
            duration = self._get_wav_duration(wav_path)
            return AudioResult(
                wav_path=wav_path,
                method_used="comfyui_audio",
                duration_s=duration,
                material_category=material,
            )

        # Step 3: Try sound bank
        wav_path = self._try_sound_bank(mask_id, material, obj_dir)
        if wav_path is not None:
            normalize_audio(wav_path, TARGET_DBFS)
            duration = self._get_wav_duration(wav_path)
            return AudioResult(
                wav_path=wav_path,
                method_used="sound_bank",
                duration_s=duration,
                material_category=material,
            )

        # Step 4: Default fallback
        logger.warning(
            "Both ComfyUI audio and sound bank failed for %s — using default impact",
            mask_id,
        )
        wav_path = self._use_default(mask_id, obj_dir)
        normalize_audio(wav_path, TARGET_DBFS)
        duration = self._get_wav_duration(wav_path)
        return AudioResult(
            wav_path=wav_path,
            method_used="default",
            duration_s=duration,
            material_category=material,
        )

    async def _try_comfyui_audio(
        self, mask_id: str, material: str, output_dir: Path
    ) -> Path | None:
        """Attempt audio synthesis via ComfyUI audio nodes.

        Parameters
        ----------
        mask_id : str
            Object identifier for output naming.
        material : str
            Estimated material category.
        output_dir : Path
            Directory for saving output WAV.

        Returns
        -------
        Path | None
            Path to generated WAV if successful, None otherwise.
        """
        try:
            workflow = load_workflow("audio_impact")
            placeholders = {
                "MATERIAL_CATEGORY": material,
                "AUDIO_OUTPUT_PREFIX": f"{mask_id}_impact",
                "OUTPUT_DIR": str(output_dir).replace("\\", "/"),
            }

            prompt_id = await self.client.submit_workflow(
                workflow, placeholders=placeholders
            )
            result = await self.client.wait_for_completion(prompt_id, timeout_s=60)

            # Look for audio output in the result
            outputs = result.get("outputs", {})
            for node_outputs in outputs.values():
                audio_files = node_outputs.get("audio", []) or node_outputs.get("files", [])
                if audio_files:
                    # Download/retrieve the audio file
                    audio_info = audio_files[0]
                    filename = audio_info.get("filename", "")
                    if filename:
                        wav_path = output_dir / f"{mask_id}_impact.wav"
                        # Retrieve via view endpoint
                        import httpx

                        async with httpx.AsyncClient(timeout=30.0) as http_client:
                            resp = await http_client.get(
                                f"{self.client.base_url}/view",
                                params={
                                    "filename": filename,
                                    "subfolder": audio_info.get("subfolder", ""),
                                    "type": audio_info.get("type", "output"),
                                },
                            )
                            if resp.status_code == 200:
                                wav_path.write_bytes(resp.content)
                                logger.info("ComfyUI audio generated for %s", mask_id)
                                return wav_path

            logger.info("ComfyUI audio produced no output for %s", mask_id)
            return None

        except (ComfyUIError, ComfyUITimeoutError) as exc:
            logger.info("ComfyUI audio failed for %s: %s", mask_id, exc)
            return None
        except Exception as exc:
            logger.info("ComfyUI audio unexpected error for %s: %s", mask_id, exc)
            return None

    def _try_sound_bank(
        self, mask_id: str, material: str, output_dir: Path
    ) -> Path | None:
        """Look up and copy a sound bank WAV for the given material.

        Parameters
        ----------
        mask_id : str
            Object identifier for output naming.
        material : str
            Estimated material category.
        output_dir : Path
            Directory to copy the WAV to.

        Returns
        -------
        Path | None
            Path to the copied WAV if found, None otherwise.
        """
        source_wav = lookup_sound_bank(material, self.sound_bank_dir)
        if source_wav is None:
            logger.info("Sound bank has no entry for material '%s'", material)
            return None

        # Copy to output directory with object-specific name
        dest_wav = output_dir / f"{mask_id}_impact.wav"
        try:
            shutil.copy2(str(source_wav), str(dest_wav))
            logger.info("Sound bank hit for %s (material=%s)", mask_id, material)
            return dest_wav
        except OSError as exc:
            logger.warning("Failed to copy sound bank WAV for %s: %s", mask_id, exc)
            return None

    def _use_default(self, mask_id: str, output_dir: Path) -> Path:
        """Copy the default generic impact sound to the output directory.

        Parameters
        ----------
        mask_id : str
            Object identifier for output naming.
        output_dir : Path
            Directory to copy the WAV to.

        Returns
        -------
        Path
            Path to the copied default WAV.
        """
        default_wav = self.sound_bank_dir / "default_impact.wav"
        dest_wav = output_dir / f"{mask_id}_impact.wav"

        if default_wav.exists():
            shutil.copy2(str(default_wav), str(dest_wav))
        else:
            # Generate a minimal silent WAV as absolute fallback
            self._generate_silent_wav(dest_wav)

        return dest_wav

    @staticmethod
    def _generate_silent_wav(path: Path) -> None:
        """Generate a minimal 0.1s silent WAV file.

        Parameters
        ----------
        path : Path
            Output path for the silent WAV.
        """
        n_samples = int(MIN_DURATION_S * SAMPLE_RATE)
        silence = np.zeros(n_samples, dtype=np.int16)

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(silence.tobytes())

    @staticmethod
    def _get_wav_duration(wav_path: Path) -> float:
        """Get the duration of a WAV file in seconds.

        Parameters
        ----------
        wav_path : Path
            Path to the WAV file.

        Returns
        -------
        float
            Duration in seconds.
        """
        try:
            with wave.open(str(wav_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate == 0:
                    return 0.0
                return frames / rate
        except Exception:
            return 0.0
