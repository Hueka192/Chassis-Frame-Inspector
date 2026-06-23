"""
Vehicle Model Registry
=======================
Defines which checklist items apply to each vehicle model.
Each model has a unique MODEL_CODE and a list of ChecklistItem definitions.

Operators scan a VC (Vehicle Chassis) number like:
  4832TK0012345   → model prefix "4832TK" → TK Long Member model

Add new models by extending VEHICLE_MODELS dict.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ChecklistItem:
    id: str            # e.g. "CL-01"
    name: str          # e.g. "Trunnion Bracket – Long Member"
    description: str
    qty: int = 1
    location: str = ""
    critical: bool = True    # critical = must be OK for overall OK


@dataclass
class VehicleModel:
    code: str            # e.g. "4832TK"
    name: str            # e.g. "Tata 4832 TK Long Member"
    description: str
    checklist: List[ChecklistItem] = field(default_factory=list)


# ── Master checklist from qg-1.pptx / new_qa.png (final 8-point inspection) ──

_PREFITMENT_CHECKLIST = [
    ChecklistItem("CL-01", "Resilience bkt.", "", 1, ""),
    ChecklistItem("CL-04", "B/S Bumper support bkt.", "", 1, ""),
    ChecklistItem("CL-05", "Bumper support bkt", "", 1, ""),
    ChecklistItem("CL-08", "B/S Trunnion bkt mtg on frame", "", 1, ""),
    ChecklistItem("CL-12", "B/S Eng Mtg Bkt", "", 1, ""),
    ChecklistItem("CL-15", "APU Fitment with bkt", "", 1, ""),
    ChecklistItem("CL-18", "B/S ARB Rear mtg BKT", "", 1, ""),
    ChecklistItem("CL-19", "Articulation Stopper", "", 1, ""),
]

# ── Vehicle model registry ─────────────────────────────────────────────────────
# Key = prefix that appears at the start of the VC number (case-insensitive)

VEHICLE_MODELS: Dict[str, VehicleModel] = {
    "4832TK": VehicleModel(
        code="4832TK",
        name="Tata 4832 TK – Long Member Frame",
        description="Heavy duty long member chassis frame — 8-point checklist",
        checklist=_PREFITMENT_CHECKLIST,
    ),
    "2518": VehicleModel(
        code="2518",
        name="Tata 2518 – Medium Frame",
        description="Medium duty chassis — 8-point checklist",
        checklist=_PREFITMENT_CHECKLIST,
    ),
    "3118": VehicleModel(
        code="3118",
        name="Tata 3118 – Heavy Frame",
        description="Heavy duty chassis — 8-point checklist",
        checklist=_PREFITMENT_CHECKLIST,
    ),
    "4923": VehicleModel(
        code="4923",
        name="Tata 4923 – Extra Heavy Frame",
        description="Extra heavy chassis — 8-point checklist",
        checklist=_PREFITMENT_CHECKLIST,
    ),
    "DEFAULT": VehicleModel(
        code="DEFAULT",
        name="Generic Frame",
        description="Default checklist — 8-point checklist",
        checklist=_PREFITMENT_CHECKLIST,
    ),
}


def resolve_model(vc_number: str) -> VehicleModel:
    """
    Resolve a VC number to a VehicleModel by prefix matching.
    Falls back to DEFAULT if no prefix matches.
    """
    vc = vc_number.strip().upper()
    for prefix in sorted(VEHICLE_MODELS.keys(), key=len, reverse=True):
        if prefix == "DEFAULT":
            continue
        if vc.startswith(prefix):
            return VEHICLE_MODELS[prefix]
    return VEHICLE_MODELS["DEFAULT"]
