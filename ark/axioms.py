"""Starter SD-ARK axiom evaluation for replay fixtures.

What: deterministic policy selection over S[6] for behavioral simulations.
Why: replay fixtures should prove useful choices, not only runnable plumbing.
Where: tests/replay fixtures for home lab, health, and finance scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass

from ark.sd_trisca import SVector

MAX_AXIOMS = 10


@dataclass(frozen=True)
class Axiom:
    id: str
    action: str
    priority: float

    def matches(self, s: SVector) -> bool:
        match self.id:
            case "entropy-control":
                return s.entropy > 0.7
            case "signal-amplification":
                return s.signal_density > 0.75
            case "efficiency-recovery":
                return s.efficiency < 0.4
            case "temporal-drift":
                return s.temporal < 0.3
            case "inequality-spike":
                return s.inequality > 0.65
            case "structure-collapse":
                return s.structure < 0.35
            case "exploit-stable-efficient":
                return s.entropy < 0.3 and s.efficiency > 0.7
            case "prune-noise":
                return s.entropy > 0.75 and s.signal_density < 0.4
            case "redirect-misuse":
                return s.signal_density > 0.7 and s.efficiency < 0.5
            case "maintain-balanced":
                return s.entropy < 0.5 and s.efficiency > 0.6 and s.inequality < 0.5
            case _:
                return False


AXIOMS: tuple[Axiom, ...] = (
    Axiom("entropy-control", "reduce_load", 0.8),
    Axiom("signal-amplification", "increase_focus", 0.7),
    Axiom("efficiency-recovery", "optimize_path", 0.75),
    Axiom("temporal-drift", "refresh_state", 0.6),
    Axiom("inequality-spike", "rebalance", 0.7),
    Axiom("structure-collapse", "stabilize", 0.85),
    Axiom("exploit-stable-efficient", "scale_up", 0.9),
    Axiom("prune-noise", "prune_noise", 0.8),
    Axiom("redirect-misuse", "redirect_resources", 0.75),
    Axiom("maintain-balanced", "maintain", 0.5),
)


def choose_action(s: SVector, axioms: tuple[Axiom, ...] = AXIOMS) -> str:
    """Choose the highest-priority matching action.

    Runtime: O(10). Memory: O(1). Failure: returns "noop" if no axiom matches.
    """

    best: Axiom | None = None
    for index in range(min(len(axioms), MAX_AXIOMS)):
        axiom = axioms[index]
        if not axiom.matches(s):
            continue
        if best is None or axiom.priority > best.priority:
            best = axiom
    return best.action if best else "noop"
