"""Run the whole pipeline, or one step.

    python -m pipeline.run            # fetch, census, geometry, qa, export
    python -m pipeline.run census     # a single step
"""

from __future__ import annotations

import sys

from . import census, export, fetch, geometry, qa

STEPS = {
    "fetch": lambda: fetch.main([]),
    "census": census.main,
    "geometry": geometry.build,
    "qa": qa.main,
    "export": export.main,
}


def main(argv: list[str]) -> int:
    wanted = argv or list(STEPS)
    unknown = [s for s in wanted if s not in STEPS]
    if unknown:
        print(f"Unknown step(s): {unknown}. Choose from {list(STEPS)}.")
        return 2
    for step in wanted:
        code = STEPS[step]()
        if code:
            print(f"Stopped: step '{step}' failed.")
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
