"""Collecting and running the checks.

The collection loop lives here rather than in an entry point so a second entry
point can stand in for the first without importing it.
"""

import importlib
import pkgutil
import traceback


def collect(package="tests", prefix="test_"):
    """Every callable named check_ in every module named test_, in a stable order."""
    pkg = importlib.import_module(package)
    found = []
    names = sorted(
        m.name for m in pkgutil.iter_modules(pkg.__path__) if m.name.startswith(prefix)
    )
    for name in names:
        mod = importlib.import_module("%s.%s" % (package, name))
        for attr in sorted(dir(mod)):
            if attr.startswith("check_"):
                fn = getattr(mod, attr)
                if callable(fn):
                    found.append(("%s.%s" % (name, attr), fn))
    return found


def run_checks(checks, verbose=False):
    passed = 0
    failures = []
    for name, fn in checks:
        try:
            fn()
            passed += 1
            if verbose:
                print("ok   %s" % name)
        except Exception as exc:  # noqa: BLE001
            failures.append((name, exc, traceback.format_exc()))
            print("FAIL %s: %s" % (name, exc))

    if not checks:
        # A runner that exits 0 having collected nothing is a runner that
        # reports a clean tree it never looked at.
        raise SystemExit("collected no checks, which is a failure and not a pass")

    for name, _exc, tb in failures:
        print()
        print("=" * 70)
        print(name)
        print(tb)

    print()
    print("%d passed, %d failed, %d collected" % (passed, len(failures), len(checks)))
    return 1 if failures else 0
