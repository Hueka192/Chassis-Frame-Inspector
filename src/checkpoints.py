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
    Checkpoint(1,  "CL-01", "Resilience bkt.",
               "Resilience bracket fitment", 1,
               "Frame middle", "CENTER", "any",
               ["resilience", "bkt"], "new_qa.png"),

    Checkpoint(2,  "CL-04", "B/S Bumper support bkt.",
               "Both sides bumper support bracket", 1,
               "Front left", "BOTH", "any",
               ["bumper", "support", "bkt"], "new_qa.png"),

    Checkpoint(3,  "CL-05", "Bumper support bkt",
               "Bumper support bracket", 1,
               "Front", "CENTER", "any",
               ["bumper", "support"], "new_qa.png"),

    Checkpoint(4,  "CL-08", "B/S Trunnion bkt mtg on frame",
               "Both sides trunnion bracket mounting on frame", 1,
               "Rear axle", "BOTH", "any",
               ["trunnion", "bkt", "mtg"], "new_qa.png"),

    Checkpoint(5,  "CL-12", "B/S Eng Mtg Bkt",
               "Both sides engine mounting bracket", 1,
               "Engine area", "BOTH", "any",
               ["engine", "mtg", "bkt"], "new_qa.png"),

    Checkpoint(6,  "CL-15", "APU Fitment with bkt",
               "APU fitment with bracket", 1,
               "Underside", "CENTER", "any",
               ["apu", "fitment", "bkt"], "new_qa.png"),

    Checkpoint(7,  "CL-18", "B/S ARB Rear mtg BKT",
               "Both sides anti-roll bar rear mounting bracket", 1,
               "Rear", "BOTH", "any",
               ["arb", "rear", "mtg"], "new_qa.png"),

    Checkpoint(8,  "CL-19", "Articulation Stopper",
               "Articulation stopper fitment", 1,
               "Rear axle zone", "CENTER", "any",
               ["articulation", "stopper"], "new_qa.png"),
]

CHECKPOINT_MAP = {cp.id: cp for cp in CHECKPOINTS}
