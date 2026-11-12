"""Wall-clock bounds: enforced on a developer machine, skipped on shared CI runners.

A runner's speed varies from run to run, so a time bound there only produces noise. The
structural checks next to them (query plans, counts, no lock errors) still run everywhere.
"""

import os

ENFORCE_TIMING = not os.environ.get("CI")


def within(elapsed_s: float, bound_s: float, what: str = "") -> None:
    if ENFORCE_TIMING:
        assert elapsed_s < bound_s, f"{what or 'timing'}: {elapsed_s:.3f}s is not under {bound_s}s"
