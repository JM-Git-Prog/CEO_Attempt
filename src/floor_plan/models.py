"""Typed contract for the approved spatial plan."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlanRoom(BaseModel):
    width: float = Field(ge=2.5, le=30.0)
    depth: float = Field(ge=2.5, le=30.0)
    height: float = Field(default=2.8, ge=2.1, le=8.0)


class PlanItem(BaseModel):
    id: str
    name: str
    category: Literal["furniture", "fixture", "architectural", "decor"]
    x: float
    z: float
    width: float = Field(gt=0.0, le=20.0)
    depth: float = Field(gt=0.0, le=20.0)
    height: float = Field(gt=0.0, le=8.0)
    elevation: float = Field(default=0.0, ge=0.0, le=8.0)
    rotation_deg: float = 0.0
    fixed: bool = False
    clearance_m: float = Field(default=0.75, ge=0.0, le=3.0)
    description: str = ""


class PlanOpening(BaseModel):
    id: str
    kind: Literal["door", "window"]
    wall: Literal["north", "south", "east", "west"]
    offset: float = 0.0
    width: float = Field(default=0.9, gt=0.2, le=8.0)
    height: float = Field(default=2.1, gt=0.2, le=5.0)
    sill_height: float = Field(default=0.0, ge=0.0, le=4.0)


class PlanCamera(BaseModel):
    x: float
    y: float = Field(default=1.6, ge=0.2, le=5.0)
    z: float
    target_x: float = 0.0
    target_y: float = 1.1
    target_z: float = 0.0
    fov_deg: float = Field(default=55.0, ge=30.0, le=90.0)


class FloorPlan(BaseModel):
    name: str
    room: PlanRoom
    items: list[PlanItem] = Field(default_factory=list)
    openings: list[PlanOpening] = Field(default_factory=list)
    camera: PlanCamera
    circulation_notes: list[str] = Field(default_factory=list)
    design_notes: list[str] = Field(default_factory=list)
