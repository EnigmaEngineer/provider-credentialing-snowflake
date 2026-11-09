"""Run every check. This is the entry point the gates and the mutation pass use."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.runner import collect, run_checks  # noqa: E402


def main():
    return run_checks(collect(), verbose="-v" in sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
