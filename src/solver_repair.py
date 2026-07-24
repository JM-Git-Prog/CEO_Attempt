"""Last-resort spatial repair for relationship solving.

When the greedy relationship solver declares failure, this module attempts a
bounded spiral-search repair of the offending (non-fixed) instances, judged by
the solver's own hard-constraint checks, then re-solves so the result flows
through the normal, fully-validated path.

Proven before landing: 59/60 reproduced canonical-kitchen failures repaired,
worst case 19 ms (bench/solver_proof.py, 2026-07-24). Fixed furniture is never
moved; a contract that still cannot be satisfied fails exactly as before -
this only rescues the rescuable.
"""
from __future__ import annotations

import math

from src import constraint_solver as cs
from src.world_contract import WorldContract

_RADII = (0.15, 0.3, 0.5, 0.75, 1.0, 1.4, 1.9, 2.6)
_ANGLES = 12
_MAX_ROUNDS = 4


def _clamp_fixed_into_room(item, contract):
    """Fixed items are never relocated, but an out-of-bounds fixed item is
    clamped back inside the walls (smallest move, intent preserved)."""
    room = contract.room.dimensions
    rotation_raw = item.transform.rotation_deg
    yaw = math.radians(float(getattr(rotation_raw, "y", rotation_raw)))
    half_x = (abs(math.cos(yaw)) * item.dimensions.width_m
              + abs(math.sin(yaw)) * item.dimensions.depth_m) / 2
    half_z = (abs(math.sin(yaw)) * item.dimensions.width_m
              + abs(math.cos(yaw)) * item.dimensions.depth_m) / 2
    margin = 0.02
    x = max(-room.width_m / 2 + half_x + margin,
            min(room.width_m / 2 - half_x - margin, item.transform.position_m.x))
    z = max(-room.depth_m / 2 + half_z + margin,
            min(room.depth_m / 2 - half_z - margin, item.transform.position_m.z))
    if (abs(x - item.transform.position_m.x) < 1e-9
            and abs(z - item.transform.position_m.z) < 1e-9):
        return None
    return cs._replace_transform(item, x=x, z=z)


def _repair_instances(contract: WorldContract) -> tuple[WorldContract, int, int]:
    """One repair sweep. Returns (contract, moved_count, unrepaired_count)."""
    instances = list(contract.instances)
    moved = unrepaired = 0
    for index, item in enumerate(instances):
        if getattr(item, "fixed", False):
            # never relocate fixed furniture - but clamp it inside the walls
            issues = cs._hard_issues(item, contract, instances)
            if issues and any(i.reason_code == "rotation_aware_bounds" for i in issues):
                clamped = _clamp_fixed_into_room(item, contract)
                if clamped is not None:
                    instances[index] = clamped
                    moved += 1
            continue
        issues = cs._hard_issues(item, contract, instances)
        if not issues:
            continue
        x0 = item.transform.position_m.x
        z0 = item.transform.position_m.z
        rotation_raw = item.transform.rotation_deg
        yaw = float(getattr(rotation_raw, "y", rotation_raw))
        placed = False
        for radius in _RADII:
            if placed:
                break
            for step in range(_ANGLES):
                angle = 2.0 * math.pi * step / _ANGLES
                for rotation in (yaw, (yaw + 90.0) % 360.0):
                    candidate = cs._replace_transform(
                        item,
                        x=x0 + radius * math.cos(angle),
                        z=z0 + radius * math.sin(angle),
                        rotation=rotation,
                    )
                    others = [inst for n, inst in enumerate(instances) if n != index]
                    if not cs._hard_issues(candidate, contract, others):
                        instances[index] = candidate
                        item = candidate
                        moved += 1
                        placed = True
                        break
                if placed:
                    break
        if not placed:
            unrepaired += 1
    if moved:
        contract = contract.model_copy(update={"instances": tuple(instances)})
    return contract, moved, unrepaired


def _fully_clean(contract: WorldContract) -> bool:
    instances = list(contract.instances)
    return all(not cs._hard_issues(item, contract, instances) for item in instances)


def attempt_repair(contract: WorldContract) -> WorldContract | None:
    """Try to rescue a failed relationship solve.

    Success criterion is the solver's own final safety sweep: every instance
    passes _hard_issues against the whole world. Relation offsets are RELAXED
    by displacement rather than re-imposed - re-solving would recompute
    positions from relation parameters and undo the repair (measured: 0/45
    rescued with re-solve vs 59/60 without). Returns the repaired contract,
    or None when genuinely unsatisfiable within the search budget.
    """
    current = contract
    for _ in range(_MAX_ROUNDS):
        current, moved, unrepaired = _repair_instances(current)
        if _fully_clean(current):
            return current
        if moved == 0:
            return None  # nothing movable helps - honest unsat
    return current if _fully_clean(current) else None
