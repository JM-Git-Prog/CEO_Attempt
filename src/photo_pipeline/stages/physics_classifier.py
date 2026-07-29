"""Physics classification stage for the Photo-to-Real-3D-World V14 pipeline.

Determines whether a reconstructed object should be treated as a dynamic or
static rigid-body based on estimated mass from volume × material density.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""
from __future__ import annotations

from src.photo_pipeline.models_v14 import PhysicsClassification


class PhysicsClassifier:
    """Classify an object's physics profile from geometry + material hints.

    Rules:
    - mass <= 25kg → DYNAMIC (grabbable/pushable)
    - mass > 25kg → STATIC (immovable)
    - Architectural objects → always STATIC regardless of mass
    """

    DENSITY_TABLE: dict[str, float] = {
        "wood": 600.0,
        "metal": 7800.0,
        "glass": 2500.0,
        "fabric": 200.0,
        "ceramic": 2300.0,
        "plastic": 950.0,
    }
    DEFAULT_DENSITY: float = 950.0
    MASS_THRESHOLD_KG: float = 25.0

    _DYNAMIC_FRICTION: float = 0.5
    _DYNAMIC_RESTITUTION: float = 0.2
    _STATIC_FRICTION: float = 0.6
    _STATIC_RESTITUTION: float = 0.1

    def classify(
        self,
        dimensions_m: tuple[float, float, float],
        material: str,
        is_architectural: bool,
    ) -> PhysicsClassification:
        """Compute mass from volume × density, apply threshold and overrides.

        Parameters
        ----------
        dimensions_m
            (width, height, depth) in metres from ScaleResult.
        material
            Lower-case material label used as key into DENSITY_TABLE.
        is_architectural
            True for walls, doors, built-in items — always STATIC.
        """
        w, h, d = dimensions_m
        volume = w * h * d
        density = self.DENSITY_TABLE.get(material.lower(), self.DEFAULT_DENSITY)
        mass = volume * density

        if is_architectural:
            return PhysicsClassification(
                body_mode="STATIC",
                mass_kg=0.0,
                volume_m3=volume,
                material_density=density,
                friction=self._STATIC_FRICTION,
                restitution=self._STATIC_RESTITUTION,
                can_topple=False,
                override_reason="architectural_function",
            )

        if mass <= self.MASS_THRESHOLD_KG:
            return PhysicsClassification(
                body_mode="DYNAMIC",
                mass_kg=mass,
                volume_m3=volume,
                material_density=density,
                friction=self._DYNAMIC_FRICTION,
                restitution=self._DYNAMIC_RESTITUTION,
                can_topple=True,
                override_reason=None,
            )

        return PhysicsClassification(
            body_mode="STATIC",
            mass_kg=0.0,
            volume_m3=volume,
            material_density=density,
            friction=self._STATIC_FRICTION,
            restitution=self._STATIC_RESTITUTION,
            can_topple=False,
            override_reason=None,
        )
