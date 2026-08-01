function finite(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`${label} must be finite`);
  }
  return value;
}

export function toggleDoorTarget(currentDeg, lowerDeg, upperDeg) {
  finite(currentDeg, "current door angle");
  finite(lowerDeg, "lower door limit");
  finite(upperDeg, "upper door limit");
  if (lowerDeg >= upperDeg) throw new RangeError("door limits are invalid");
  return Math.abs(currentDeg - lowerDeg) <= Math.abs(currentDeg - upperDeg)
    ? upperDeg : lowerDeg;
}

export function advanceDoorAngle(
  currentDeg, targetDeg, speedDegPerSecond, deltaSeconds, lowerDeg, upperDeg
) {
  for (const [value, label] of [
    [currentDeg, "current door angle"], [targetDeg, "target door angle"],
    [speedDegPerSecond, "door angular speed"], [deltaSeconds, "door delta"],
    [lowerDeg, "lower door limit"], [upperDeg, "upper door limit"],
  ]) finite(value, label);
  if (lowerDeg >= upperDeg || speedDegPerSecond <= 0 || deltaSeconds < 0) {
    throw new RangeError("door integration metadata is invalid");
  }
  const boundedTarget = Math.max(lowerDeg, Math.min(upperDeg, targetDeg));
  const difference = boundedTarget - currentDeg;
  const step = speedDegPerSecond * deltaSeconds;
  const advanced = currentDeg + Math.sign(difference) * Math.min(Math.abs(difference), step);
  return Math.max(lowerDeg, Math.min(upperDeg, advanced));
}

export function createGrabConstraint(metadata, contractHash) {
  if (!metadata || typeof metadata !== "object") {
    throw new TypeError("grab metadata is required");
  }
  finite(metadata.hold_distance_m, "hold distance");
  finite(metadata.hold_stiffness, "hold stiffness");
  if (metadata.hold_distance_m <= 0 || metadata.hold_stiffness <= 0 || !contractHash) {
    throw new RangeError("grab constraint metadata is invalid");
  }
  return Object.freeze({
    holdDistanceM: metadata.hold_distance_m,
    stiffness: metadata.hold_stiffness,
    contractHash,
  });
}

export function releasedGrabState() {
  return Object.freeze({held: false, grabConstraint: null});
}

export function impulseVelocityDelta(impulse, massKg) {
  finite(massKg, "interaction mass");
  if (massKg <= 0) throw new RangeError("interaction mass must be positive");
  return Object.freeze({
    x: finite(impulse.x, "impulse.x") / massKg,
    y: finite(impulse.y, "impulse.y") / massKg,
    z: finite(impulse.z, "impulse.z") / massKg,
  });
}

export function localBoxAngularVelocityDelta(localAngularImpulse, dimensions, massKg) {
  finite(massKg, "interaction mass");
  const width = finite(dimensions.x, "collider width");
  const height = finite(dimensions.y, "collider height");
  const depth = finite(dimensions.z, "collider depth");
  if (massKg <= 0 || Math.min(width, height, depth) <= 0) {
    throw new RangeError("box inertia metadata must be positive");
  }
  const coefficient = massKg / 12;
  return Object.freeze({
    x: finite(localAngularImpulse.x, "angular impulse.x")
      / (coefficient * (height * height + depth * depth)),
    y: finite(localAngularImpulse.y, "angular impulse.y")
      / (coefficient * (width * width + depth * depth)),
    z: finite(localAngularImpulse.z, "angular impulse.z")
      / (coefficient * (width * width + height * height)),
  });
}
