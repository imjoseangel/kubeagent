DIAGNOSIS_COMPLETE_MARKER = "DIAGNOSIS_COMPLETE"


class Trail:
    """Per-investigation hop-budget tracker.

    Kept as an instance (not module-level state, unlike the standalone
    example) because the service handles concurrent investigations. Each
    read/write tool call records a step here and gets back a `[steer]` note
    to append to its summary — live guidance nudging the agent toward
    convergence, the same mechanism the reference wiki-rabbit-hole loop
    uses to avoid wandering forever.
    """

    def __init__(self, max_hops: int, steps: list[str] | None = None) -> None:
        self.max_hops = max_hops
        # Accepts an external list (e.g. Investigation.trail) so the
        # caller can observe recorded steps without polling this object.
        self.steps: list[str] = steps if steps is not None else []

    def record(self, step: str) -> str:
        if step in self.steps:
            return (
                f"\n\n[steer] You already did {step!r} — you're looping. "
                "Try a different tool or target, or converge now."
            )
        self.steps.append(step)
        used = len(self.steps)
        if used >= self.max_hops:
            return (
                f"\n\n[steer] Hop budget spent ({used}/{self.max_hops}). "
                f"Decide NOW: emit {DIAGNOSIS_COMPLETE_MARKER} "
                "with your report."
            )
        if used >= self.max_hops - 2:
            return (
                f"\n\n[steer] {used}/{self.max_hops} hops used — "
                "start converging on a root cause."
            )
        return (
            f"\n\n[steer] {used}/{self.max_hops} hops · "
            f"trail so far: {' -> '.join(self.steps)}"
        )
