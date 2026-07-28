"""Property-based tests for photo pipeline audio synthesizer.

# Feature: photo-to-playable-world

## Property 8: Audio Output Format Constraints

**Validates: Requirements 5.1**

For any generated impact audio file, the output SHALL be mono (1 channel),
44100Hz sample rate, 16-bit depth, and duration between 0.1 and 2.0 seconds
inclusive.

## Property 9: Audio Normalization to Target Peak

**Validates: Requirements 5.5**

For any input WAV data with at least one non-zero sample, after normalization
the peak amplitude SHALL be within 0.1 dB of -3.0 dBFS.

## Property 10: Material-to-Sound Mapping Completeness

**Validates: Requirements 5.3**

For any valid material category in {wood, metal, glass, fabric, ceramic, plastic},
the sound bank lookup SHALL return a non-null path to an existing WAV file.

Uses Hypothesis with numpy strategies.
"""

from __future__ import annotations

import math
import tempfile
import wave
from pathlib import Path

import numpy as np
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.photo_pipeline.stages.audio_synthesizer import (
    normalize_audio,
    lookup_sound_bank,
    SAMPLE_RATE,
    CHANNELS,
    SAMPLE_WIDTH,
    MIN_DURATION_S,
    MAX_DURATION_S,
    TARGET_DBFS,
    VALID_MATERIALS,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def random_wav_params(draw: st.DrawFn) -> tuple[int, int, int, float]:
    """Generate random WAV parameters for testing normalize_audio.

    Returns (sample_rate, channels, sample_width_bytes, duration_s).
    """
    sample_rate = draw(st.sampled_from([8000, 11025, 22050, 44100, 48000, 96000]))
    channels = draw(st.integers(min_value=1, max_value=2))
    sample_width = draw(st.sampled_from([2]))  # normalize_audio supports int16 directly
    duration_s = draw(st.floats(min_value=0.01, max_value=5.0))
    return (sample_rate, channels, sample_width, duration_s)


@st.composite
def non_silent_int16_samples(draw: st.DrawFn) -> np.ndarray:
    """Generate a random int16 array with at least one non-zero sample.

    Length between 100 and 100000 samples (before mono conversion).
    """
    length = draw(st.integers(min_value=100, max_value=50000))
    # Generate random int16 samples
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    rng = np.random.default_rng(seed)
    samples = rng.integers(-32768, 32767, size=length, dtype=np.int16)

    # Ensure at least one non-zero sample
    if np.all(samples == 0):
        samples[0] = draw(st.integers(min_value=1, max_value=32767))

    return samples


# ---------------------------------------------------------------------------
# Helper: write a WAV from parameters
# ---------------------------------------------------------------------------


def _write_test_wav(
    path: Path,
    samples: np.ndarray,
    sample_rate: int = 44100,
    channels: int = 1,
    sample_width: int = 2,
) -> None:
    """Write a WAV file from int16 sample data."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())


def _read_wav_properties(path: Path) -> tuple[int, int, int, int, float]:
    """Read WAV properties: (channels, sample_width, framerate, nframes, duration_s)."""
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sw = wf.getsampwidth()
        fr = wf.getframerate()
        nf = wf.getnframes()
        duration = nf / fr if fr > 0 else 0.0
    return (n_channels, sw, fr, nf, duration)


def _read_wav_peak_dbfs(path: Path) -> float:
    """Read a WAV file and return peak amplitude in dBFS."""
    with wave.open(str(path), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    peak = np.max(np.abs(samples))
    if peak == 0:
        return float("-inf")
    # dBFS: 20 * log10(peak / 32767)
    return 20.0 * math.log10(peak / 32767.0)


# ---------------------------------------------------------------------------
# Property 8: Audio Output Format Constraints
# ---------------------------------------------------------------------------


class TestAudioOutputFormatConstraints:
    """Property 8: Audio Output Format Constraints.

    **Validates: Requirements 5.1**

    For any generated audio, output is mono (1 channel), 44100Hz sample rate,
    16-bit depth, and duration between 0.1 and 2.0 seconds inclusive.
    """

    @given(
        wav_params=random_wav_params(),
        samples=non_silent_int16_samples(),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_normalize_produces_correct_format(
        self,
        wav_params: tuple[int, int, int, float],
        samples: np.ndarray,
    ):
        """After normalize_audio, output WAV is mono 44100Hz 16-bit within duration bounds."""
        sample_rate, channels, sample_width, _ = wav_params

        # If multi-channel, interleave samples
        if channels > 1:
            # Duplicate samples for stereo
            stereo = np.column_stack([samples, samples]).flatten().astype(np.int16)
            wav_data = stereo
        else:
            wav_data = samples

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            _write_test_wav(tmp_path, wav_data, sample_rate, channels, sample_width)

            # Run normalization
            normalize_audio(tmp_path)

            # Verify output format constraints
            n_channels, sw, fr, nf, duration = _read_wav_properties(tmp_path)

            assert n_channels == CHANNELS, (
                f"Expected mono ({CHANNELS} channel), got {n_channels}"
            )
            assert fr == SAMPLE_RATE, (
                f"Expected {SAMPLE_RATE}Hz, got {fr}"
            )
            assert sw == SAMPLE_WIDTH, (
                f"Expected {SAMPLE_WIDTH}-byte (16-bit), got {sw}-byte"
            )
            assert MIN_DURATION_S <= duration <= MAX_DURATION_S, (
                f"Expected duration in [{MIN_DURATION_S}, {MAX_DURATION_S}]s, "
                f"got {duration:.4f}s"
            )
        finally:
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Property 9: Audio Normalization to Target Peak
# ---------------------------------------------------------------------------


class TestAudioNormalizationToTargetPeak:
    """Property 9: Audio Normalization to Target Peak.

    **Validates: Requirements 5.5**

    For any input WAV data with at least one non-zero sample, after
    normalization the peak amplitude SHALL be within 0.1 dB of -3.0 dBFS.
    """

    @given(samples=non_silent_int16_samples())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_peak_amplitude_within_tolerance(self, samples: np.ndarray):
        """After normalization, peak is within 0.1dB of -3.0 dBFS."""
        # Ensure at least one non-zero sample
        assume(np.any(samples != 0))

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            # Write mono 44100Hz 16-bit WAV
            _write_test_wav(tmp_path, samples, SAMPLE_RATE, CHANNELS, SAMPLE_WIDTH)

            # Run normalization
            normalize_audio(tmp_path, target_dbfs=TARGET_DBFS)

            # Measure resulting peak
            peak_dbfs = _read_wav_peak_dbfs(tmp_path)

            # Peak should be within 0.1 dB of target (-3.0 dBFS)
            tolerance_db = 0.1
            assert abs(peak_dbfs - TARGET_DBFS) <= tolerance_db, (
                f"Expected peak within {tolerance_db}dB of {TARGET_DBFS}dBFS, "
                f"got {peak_dbfs:.4f}dBFS (delta={abs(peak_dbfs - TARGET_DBFS):.4f}dB)"
            )
        finally:
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Property 10: Material-to-Sound Mapping Completeness
# ---------------------------------------------------------------------------


class TestMaterialToSoundMappingCompleteness:
    """Property 10: Material-to-Sound Mapping Completeness.

    **Validates: Requirements 5.3**

    For any valid material category in {wood, metal, glass, fabric, ceramic, plastic},
    the sound bank lookup SHALL return a non-null path to an existing WAV file.
    """

    @given(material=st.sampled_from(sorted(VALID_MATERIALS)))
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_lookup_returns_existing_wav(self, material: str):
        """lookup_sound_bank returns a non-null path to an existing WAV for all valid materials."""
        result = lookup_sound_bank(material)

        assert result is not None, (
            f"lookup_sound_bank('{material}') returned None — "
            f"expected a valid path to an existing WAV file"
        )
        assert result.exists(), (
            f"lookup_sound_bank('{material}') returned {result}, "
            f"but that file does not exist on disk"
        )
        assert result.suffix.lower() == ".wav", (
            f"lookup_sound_bank('{material}') returned {result}, "
            f"expected a .wav file extension"
        )
