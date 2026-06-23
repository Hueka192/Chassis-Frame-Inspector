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


# ── Master checklist (shared base — same PPTX checkpoints) ────────────────────

_BASE_CHECKLIST = [
    ChecklistItem("CL-01", "Trunnion Bracket – Long Member",
                  "Trunnion bracket fitted with Long Member", 1, "Centre/Rear axle zone"),
    ChecklistItem("CL-02", "V-Rod Corner Bracket – Frame",
                  "V Rod corner bracket assembled with frame", 1, "Rear section"),
    ChecklistItem("CL-03", "Articulation Stopper – Frame",
                  "Articulation stopper fitted with frame", 1, "Rear axle zone"),
    ChecklistItem("CL-04", "Trunnion Bracket – Cross Member",
                  "Trunnion bracket fitted with Cross Member", 1, "Centre cross member"),
    ChecklistItem("CL-05", "Anti-Roll Bar Sub-Assembly",
                  "Anti roll bar sub assembled mounting with frame", 1, "Rear"),
    ChecklistItem("CL-06", "V-Rod Mounting – Corner Bracket",
                  "V rod mounting with corner bracket", 1, "Rear axle"),
    ChecklistItem("CL-07", "Parking Relay Valve – Fitment",
                  "Parking Relay valve fitment on aligated X/M", 1, "Cross member"),
    ChecklistItem("CL-08", "Parking Relay Valve – Pipe Connection",
                  "Parking Relay valve pipe connection on aligated X/M", 1, "Cross member"),
    ChecklistItem("CL-09", "PTC Connector – Rear Brake Pipe",
                  "PTC connector on Rear Brake pipe Voss connector", 1, "Rear brake area"),
    ChecklistItem("CL-10", "Resilience Brackets – Frame (×5)",
                  "5 resilience brackets on frame (2 RH + 3 LH)", 5, "Both sides of LM"),
    ChecklistItem("CL-11", "Front Shock Absorber Brackets (×4)",
                  "Front Shock absorber bracket qty 04 on Frame", 4, "Front zone"),
]

# Subset for shorter models (e.g. 2518 without rear ARB items)
_SHORT_CHECKLIST = [
    ChecklistItem("CL-01", "Trunnion Bracket – Long Member",
                  "Trunnion bracket fitted with Long Member", 1, "Centre/Rear axle zone"),
    ChecklistItem("CL-02", "V-Rod Corner Bracket – Frame",
                  "V Rod corner bracket assembled with frame", 1, "Rear section"),
    ChecklistItem("CL-03", "Articulation Stopper – Frame",
                  "Articulation stopper fitted with frame", 1, "Rear axle zone"),
    ChecklistItem("CL-04", "Trunnion Bracket – Cross Member",
                  "Trunnion bracket fitted with Cross Member", 1, "Centre cross member"),
    ChecklistItem("CL-06", "V-Rod Mounting – Corner Bracket",
                  "V rod mounting with corner bracket", 1, "Rear axle"),
    ChecklistItem("CL-07", "Parking Relay Valve – Fitment",
                  "Parking Relay valve fitment on aligated X/M", 1, "Cross member"),
    ChecklistItem("CL-09", "PTC Connector – Rear Brake Pipe",
                  "PTC connector on Rear Brake pipe Voss connector", 1, "Rear brake area"),
    ChecklistItem("CL-10", "Resilience Brackets – Frame (×5)",
                  "5 resilience brackets on frame (2 RH + 3 LH)", 5, "Both sides of LM"),
]

# ── Vehicle model registry ─────────────────────────────────────────────────────
# Key = prefix that appears at the start of the VC number (case-insensitive)

VEHICLE_MODELS: Dict[str, VehicleModel] = {
    "4832TK": VehicleModel(
        code="4832TK",
        name="Tata 4832 TK – Long Member Frame",
        description="Heavy duty long member chassis frame — full 11-point checklist",
        checklist=_BASE_CHECKLIST,
    ),
    "2518": VehicleModel(
        code="2518",
        name="Tata 2518 – Medium Frame",
        description="Medium duty chassis — 8-point checklist",
        checklist=_SHORT_CHECKLIST,
    ),
    "3118": VehicleModel(
        code="3118",
        name="Tata 3118 – Heavy Frame",
        description="Heavy duty chassis — full 11-point checklist",
        checklist=_BASE_CHECKLIST,
    ),
    "4923": VehicleModel(
        code="4923",
        name="Tata 4923 – Extra Heavy Frame",
        description="Extra heavy chassis — full 11-point checklist",
        checklist=_BASE_CHECKLIST,
    ),
    "DEFAULT": VehicleModel(
        code="DEFAULT",
        name="Generic Frame",
        description="Default checklist — all 11 checkpoints",
        checklist=_BASE_CHECKLIST,
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
