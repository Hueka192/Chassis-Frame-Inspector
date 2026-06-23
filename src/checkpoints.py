"""
Checkpoint definitions — matched 1:1 to PPTX slides.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import List
from enum import Enum


class CheckStatus(Enum):
    PENDING  = "PENDING"
    DETECTED = "DETECTED"
    MISSING  = "MISSING"
    SKIPPED  = "SKIPPED"


@dataclass
class Checkpoint:
    id: int
    code: str
    name: str
    description: str
    qty: int
    location: str
    side: str
    camera_hint: str
    keywords: List[str]
    slide_img: str
    # mutable state — always reset per-frame
    status: CheckStatus = CheckStatus.PENDING
    confidence: float = 0.0
    detected_count: int = 0

    def reset(self):
        self.status = CheckStatus.PENDING
        self.confidence = 0.0
        self.detected_count = 0


CHECKPOINTS: List[Checkpoint] = [
    Checkpoint(1,  "CP-01", "Trunnion Bracket – Long Member",
               "Trunnion bracket fitted with Long Member", 1,
               "Centre / Rear axle zone", "CENTER", "any",
               ["trunnion", "bracket", "long member"], "slide_01.png"),

    Checkpoint(2,  "CP-02", "V-Rod Corner Bracket – Frame",
               "V Rod corner bracket assembled with frame", 1,
               "Rear section", "CENTER", "any",
               ["v rod", "corner bracket", "frame"], "slide_01.png"),

    Checkpoint(3,  "CP-03", "Articulation Stopper – Frame",
               "Articulation stopper fitted with frame", 1,
               "Rear axle zone", "CENTER", "any",
               ["articulation", "stopper"], "slide_01.png"),

    Checkpoint(4,  "CP-04", "Trunnion Bracket – Cross Member",
               "Trunnion bracket fitted with Cross Member", 1,
               "Centre cross member", "CENTER", "cam1",
               ["trunnion", "cross member"], "slide_02.png"),

    Checkpoint(5,  "CP-05", "Anti-Roll Bar Sub-Assembly",
               "Anti roll bar sub assembled mounting with frame", 1,
               "Rear", "CENTER", "cam2",
               ["anti roll bar", "arb", "mounting"], "slide_03.png"),

    Checkpoint(6,  "CP-06", "V-Rod Mounting – Corner Bracket",
               "V rod mounting with corner bracket", 1,
               "Rear axle", "CENTER", "any",
               ["v rod", "mounting", "corner"], "slide_04.png"),

    Checkpoint(7,  "CP-07", "Parking Relay Valve – Fitment",
               "Parking Relay valve fitment on aligated X/M", 1,
               "Cross member", "CENTER", "cam1",
               ["parking relay valve", "relay valve", "fitment"], "slide_05.png"),

    Checkpoint(8,  "CP-08", "Parking Relay Valve – Pipe Conn.",
               "Parking Relay valve pipe connection on aligated X/M", 1,
               "Cross member", "CENTER", "cam1",
               ["parking relay", "pipe connection", "voss"], "slide_05.png"),

    Checkpoint(9,  "CP-09", "PTC Connector – Rear Brake Pipe",
               "PTC connector on Rear Brake pipe Voss connector", 1,
               "Rear brake area", "CENTER", "cam2",
               ["ptc connector", "brake pipe", "voss connector"], "slide_06.png"),

    Checkpoint(10, "CP-10", "Resilience Brackets – Frame (×5)",
               "5 resilience brackets on frame (2 RH + 3 LH)", 5,
               "Both sides of Long Member", "BOTH", "any",
               ["resilience bracket", "bracket"], "slide_07.png"),

    Checkpoint(11, "CP-11", "Front Shock Absorber Brackets (×4)",
               "Front Shock absorber bracket qty 04 on Frame", 4,
               "Front zone – both sides", "BOTH", "any",
               ["shock absorber bracket", "front shock", "bracket"], "slide_10.png"),
]

CHECKPOINT_MAP = {cp.id: cp for cp in CHECKPOINTS}
