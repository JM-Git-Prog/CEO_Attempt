"""Physics classification based on estimated weight.

Classifies objects as dynamic (grabbable/pushable) or static (immovable)
based on their estimated mass computed from volume × material density,
with an architectural override for structural elements.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

from __future__ import annotations

from src.photo_pipeline.models_v14 import PhysicsClassification


class PhysicsClassifier:
    """Classify objects as dynamic or static based on estimated weight.

    Rules:
    - mass ≤ 25kg → DYNAMIC (grabbable/pushable)
    - mass > 25kg → STATIC (immovable)
    - Architectural objects → always STATIC regardless of mass
    """

    DENSITY_TABLE: dict[str, float] = {
        "wood": 600,
        "metal": 7800,
        "glass": 2500,
        "fabric": 200,
        "ceramic": 2300,
        "plastic": 950,
    }
    MASS_THRESHOLD_KG: float = 25.0

    def classify(
        self,
        dimensions_m: tuple[float, float, float],
        material: str,
        is_architectural: bool,
    ) -> PhysicsClassification:
        """Compute mass from volume × density, apply threshold.

        Args:
            dimensions_m: Object dimensions (width, height, depth) in meters.
            material: Primary material name for density lookup.
            is_architectural: Whether the object has architectural function.

        Returns:
            PhysicsClassification with body_mode, mass, friction, restitution, etc.
        """
        volume = dimensions_m[0] * dimensions_m[1] * dimensions_m[2]
        density = self.DENSITY_TABLE.get(material, 950.0)  # default to plastic
        mass = volume * density

        if is_architectural:
            return PhysicsClassification(
                body_mode="STATIC",
                mass_kg=0.0,
                volume_m3=volume,
                material_density=density,
                friction=0.6,
                restitution=0.1,
                can_topple=False,
                override_reason="architectural_function",
            )

        if mass <= self.MASS_THRESHOLD_KG:
            return PhysicsClassification(
                body_mode="DYNAMIC",
                mass_kg=mass,
                volume_m3=volume,
                material_density=density,
                friction=0.5,
                restitution=0.2,
                can_topple=True,
                override_reason=None,
            )
        else:
            return PhysicsClassification(
                body_mode="STATIC",
                mass_kg=0.0,
                volume_m3=volume,
                material_density=density,
                friction=0.6,
                restitution=0.1,
                can_topple=False,
                override_reason=None,
            )
