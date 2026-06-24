"""
Checkpoint definitions — final 8-point inspection checklist from qg-1.pptx / new_qa.png.
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
    camera: int   # 0=both, 1=camera1, 2=camera2
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
    Checkpoint(1,  "CL-01", "Resilience bkt.",
               "Resilience bracket fitment", 1,
               "Frame middle", "CENTER", 1,
               ["resilience", "bkt"], "new_qa.png"),

    Checkpoint(2,  "CL-02", "B/S Bumper support bkt.",
               "Both sides bumper support bracket", 1,
               "Front left", "BOTH", 1,
               ["bumper", "support", "bkt"], "new_qa.png"),

    Checkpoint(3,  "CL-03", "Bumper support bkt",
               "Bumper support bracket", 1,
               "Front", "CENTER", 1,
               ["bumper", "support"], "new_qa.png"),

    Checkpoint(4,  "CL-04", "B/S Trunnion bkt mtg on frame",
               "Both sides trunnion bracket mounting on frame", 1,
               "Rear axle", "BOTH", 2,
               ["trunnion", "bkt", "mtg"], "new_qa.png"),

    Checkpoint(5,  "CL-05", "B/S Eng Mtg Bkt",
               "Both sides engine mounting bracket", 1,
               "Engine area", "BOTH", 2,
               ["engine", "mtg", "bkt"], "new_qa.png"),

    Checkpoint(6,  "CL-06", "APU Fitment with bkt",
               "APU fitment with bracket", 1,
               "Underside", "CENTER", 2,
               ["apu", "fitment", "bkt"], "new_qa.png"),

    Checkpoint(7,  "CL-07", "B/S ARB Rear mtg BKT",
               "Both sides anti-roll bar rear mounting bracket", 1,
               "Rear", "BOTH", 2,
               ["arb", "rear", "mtg"], "new_qa.png"),

    Checkpoint(8,  "CL-08", "Articulation Stopper",
               "Articulation stopper fitment", 1,
               "Rear axle zone", "CENTER", 2,
               ["articulation", "stopper"], "new_qa.png"),
]

CHECKPOINT_MAP = {cp.id: cp for cp in CHECKPOINTS}
