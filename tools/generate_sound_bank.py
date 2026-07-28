"""
Generate sound bank WAV assets for the photo-to-playable-world pipeline.

Each material gets a distinct impact sound synthesized from exponentially decaying
sine waves at different frequencies and harmonics. All outputs are:
- Mono, 44100 Hz, 16-bit PCM
- Duration 0.1–2.0 seconds
- Normalized to -3 dBFS peak

Usage:
    python tools/generate_sound_bank.py

Output:
    assets/sound_bank/wood_impact.wav
    assets/sound_bank/metal_impact.wav
    assets/sound_bank/glass_impact.wav
    assets/sound_bank/fabric_impact.wav
    assets/sound_bank/ceramic_impact.wav
    assets/sound_bank/plastic_impact.wav
    assets/sound_bank/default_impact.wav
"""

import math
import os
import struct
import wave

import numpy as np

# Constants
SAMPLE_RATE = 44100
BIT_DEPTH = 16
CHANNELS = 1  # mono
TARGET_PEAK_DBFS = -3.0  # dBFS

# Output directory relative to project root
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sound_bank")


def db_to_linear(db: float) -> float:
    """Convert dBFS to linear amplitude (0.0–1.0)."""
    return 10.0 ** (db / 20.0)


def normalize_to_peak(samples: np.ndarray, target_db: float = TARGET_PEAK_DBFS) -> np.ndarray:
    """Normalize audio samples so peak amplitude equals target_db in dBFS."""
    peak = np.max(np.abs(samples))
    if peak == 0:
        return samples
    target_linear = db_to_linear(target_db)
    return samples * (target_linear / peak)


def generate_decaying_tone(
    frequency: float,
    decay_time: float,
    duration: float,
    amplitude: float = 1.0,
    phase: float = 0.0,
) -> np.ndarray:
    """Generate an exponentially decaying sine wave."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    # Exponential decay envelope: reaches ~0.001 at decay_time
    decay_rate = -np.log(0.001) / decay_time
    envelope = np.exp(-decay_rate * t)
    signal = amplitude * envelope * np.sin(2 * np.pi * frequency * t + phase)
    return signal


def generate_noise_burst(duration: float, decay_time: float, amplitude: float = 1.0) -> np.ndarray:
    """Generate a short noise burst with exponential decay (useful for transients)."""
    num_samples = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, num_samples, endpoint=False)
    decay_rate = -np.log(0.001) / decay_time
    envelope = np.exp(-decay_rate * t)
    noise = np.random.default_rng(42).uniform(-1, 1, num_samples)
    return amplitude * envelope * noise


def write_wav(filepath: str, samples: np.ndarray) -> None:
    """Write mono 16-bit 44100Hz WAV file from float samples in [-1, 1]."""
    # Clip to prevent overflow
    samples = np.clip(samples, -1.0, 1.0)
    # Convert to 16-bit integer
    int_samples = (samples * 32767).astype(np.int16)

    with wave.open(filepath, "w") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int_samples.tobytes())


# --- Material sound definitions ---


def generate_wood_impact() -> np.ndarray:
    """Wood: low-frequency thud with ~0.3s decay.
    
    Characteristics: warm, resonant low-mid thud.
    """
    duration = 0.3
    # Fundamental low thud
    signal = generate_decaying_tone(120, 0.25, duration, amplitude=1.0)
    # Second harmonic
    signal += generate_decaying_tone(240, 0.15, duration, amplitude=0.4)
    # Brief transient click
    signal += generate_noise_burst(duration, 0.02, amplitude=0.3)
    # Subtle body resonance
    signal += generate_decaying_tone(350, 0.1, duration, amplitude=0.2)
    return signal


def generate_metal_impact() -> np.ndarray:
    """Metal: high-frequency ring with ~1.0s decay.
    
    Characteristics: bright, sustained ringing with inharmonic overtones.
    """
    duration = 1.0
    # Fundamental ring
    signal = generate_decaying_tone(800, 0.8, duration, amplitude=1.0)
    # Inharmonic overtones (metallic character)
    signal += generate_decaying_tone(1247, 0.6, duration, amplitude=0.6)
    signal += generate_decaying_tone(2100, 0.4, duration, amplitude=0.3)
    signal += generate_decaying_tone(3580, 0.3, duration, amplitude=0.15)
    # Initial impact transient
    signal += generate_noise_burst(duration, 0.01, amplitude=0.5)
    return signal


def generate_glass_impact() -> np.ndarray:
    """Glass: crystalline sound with ~0.5s decay.
    
    Characteristics: high-pitched, clear, with close harmonic overtones.
    """
    duration = 0.5
    # High fundamental (crystalline)
    signal = generate_decaying_tone(2200, 0.4, duration, amplitude=1.0)
    # Close harmonics for shimmer
    signal += generate_decaying_tone(3300, 0.3, duration, amplitude=0.5)
    signal += generate_decaying_tone(4400, 0.2, duration, amplitude=0.25)
    signal += generate_decaying_tone(5500, 0.15, duration, amplitude=0.12)
    # Sharp initial transient
    signal += generate_noise_burst(duration, 0.005, amplitude=0.4)
    return signal


def generate_fabric_impact() -> np.ndarray:
    """Fabric: very soft/quiet with ~0.15s decay.
    
    Characteristics: muted, dull thud — almost entirely noise, no ring.
    """
    duration = 0.15
    # Very low, heavily damped thump
    signal = generate_decaying_tone(80, 0.08, duration, amplitude=0.6)
    # Soft noise (fabric rustle character)
    signal += generate_noise_burst(duration, 0.1, amplitude=1.0)
    # Low-pass effect via averaging adjacent samples happens naturally
    # with the low frequencies chosen
    signal += generate_decaying_tone(150, 0.05, duration, amplitude=0.3)
    return signal


def generate_ceramic_impact() -> np.ndarray:
    """Ceramic: sharp crack with ~0.4s decay.
    
    Characteristics: bright initial crack followed by short resonance.
    """
    duration = 0.4
    # Sharp initial crack (broadband transient)
    signal = generate_noise_burst(duration, 0.015, amplitude=0.8)
    # Mid-high resonance
    signal += generate_decaying_tone(1500, 0.3, duration, amplitude=1.0)
    # Higher partials for brightness
    signal += generate_decaying_tone(2800, 0.2, duration, amplitude=0.4)
    signal += generate_decaying_tone(4200, 0.12, duration, amplitude=0.2)
    # Low body thump
    signal += generate_decaying_tone(300, 0.1, duration, amplitude=0.3)
    return signal


def generate_plastic_impact() -> np.ndarray:
    """Plastic: hollow tap with ~0.3s decay.
    
    Characteristics: hollow, mid-range, slightly resonant.
    """
    duration = 0.3
    # Hollow mid-range tone
    signal = generate_decaying_tone(400, 0.2, duration, amplitude=1.0)
    # Second harmonic (hollow character)
    signal += generate_decaying_tone(800, 0.12, duration, amplitude=0.5)
    # Brief transient tap
    signal += generate_noise_burst(duration, 0.01, amplitude=0.4)
    # Slight high end for click
    signal += generate_decaying_tone(1600, 0.08, duration, amplitude=0.2)
    return signal


def generate_default_impact() -> np.ndarray:
    """Default: neutral thud with ~0.3s decay.
    
    Characteristics: generic, balanced, not strongly associated with any material.
    """
    duration = 0.3
    # Neutral mid-low tone
    signal = generate_decaying_tone(200, 0.2, duration, amplitude=1.0)
    # Subtle overtone
    signal += generate_decaying_tone(400, 0.12, duration, amplitude=0.35)
    # Transient
    signal += generate_noise_burst(duration, 0.015, amplitude=0.3)
    return signal


# --- Main generation ---

MATERIALS = {
    "wood_impact.wav": generate_wood_impact,
    "metal_impact.wav": generate_metal_impact,
    "glass_impact.wav": generate_glass_impact,
    "fabric_impact.wav": generate_fabric_impact,
    "ceramic_impact.wav": generate_ceramic_impact,
    "plastic_impact.wav": generate_plastic_impact,
    "default_impact.wav": generate_default_impact,
}


def main():
    """Generate all sound bank WAV files."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Generating sound bank in: {OUTPUT_DIR}")
    print(f"Format: mono, {SAMPLE_RATE}Hz, {BIT_DEPTH}-bit, peak at {TARGET_PEAK_DBFS} dBFS")
    print()

    for filename, generator_fn in MATERIALS.items():
        filepath = os.path.join(OUTPUT_DIR, filename)

        # Generate raw audio
        samples = generator_fn()

        # Normalize to -3 dBFS peak
        samples = normalize_to_peak(samples, TARGET_PEAK_DBFS)

        # Write WAV
        write_wav(filepath, samples)

        # Verify
        duration = len(samples) / SAMPLE_RATE
        peak_linear = np.max(np.abs(samples))
        peak_db = 20 * np.log10(peak_linear) if peak_linear > 0 else -float("inf")
        print(f"  {filename}: duration={duration:.3f}s, peak={peak_db:.1f} dBFS")

    print()
    print("Done. All files generated successfully.")


if __name__ == "__main__":
    main()
