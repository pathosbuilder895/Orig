"""Lockset import probe — the subprocess half of T-07.

Simulates *installing only a given requirements set* without actually
building a venv: a ``sys.meta_path`` finder refuses to resolve any
top-level module that the requirements set does not provide. Then it
imports ``original.repository`` and calls ``get_repository()`` with
whatever ``REPO_BACKEND`` / ``REPO_SHADOW`` the environment carries — i.e.
the import work Render's pilot service does at boot.

Run as a script so ``sys.modules`` starts clean (the pytest process has
every dev dependency imported already, which is exactly the blindness this
probe exists to remove)::

    python -m tests.config.lockset_probe requirements-pilot.lock.txt

Exit 0 and one JSON line on stdout when every import resolved; exit 1 and
``BLOCKED: <module> is not in <lockset>`` on stderr when it did not.

Distribution name → importable top-level module comes from
``importlib.metadata.packages_distributions()`` in the *current* venv (the
dev venv, which has everything), so ``PyYAML`` → ``yaml`` and
``python-jose`` → ``jose`` map correctly without a hand-maintained table. A
distribution that is pinned but not installed here is reported in
``pinned_not_installed`` and treated as allowed: whether the dev venv
happens to have it is not what is under test.
"""

from __future__ import annotations

import json
import importlib.machinery
import os
import re
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9._-]+)")


class LocksetImportError(ModuleNotFoundError):
    """Raised by the finder for a module the requirements set does not pin.

    Subclasses ``ModuleNotFoundError``, not plain ``ImportError``: that is
    what a genuinely uninstalled package raises, and library code guards on
    it specifically (anyio wraps ``import sniffio`` in
    ``except ModuleNotFoundError``). Raising the wrong class would make the
    probe stricter than a real pilot install.
    """


class LocksetFinder:
    """A ``sys.meta_path`` finder that refuses modules outside ``allowed``.

    Returning ``None`` means "not my business" and lets the normal finders
    run; raising propagates out of the import statement, which is what a
    genuinely absent package does on the pilot install.
    """

    def __init__(self, allowed: set[str], label: str) -> None:
        self._allowed = allowed
        self._label = label

    def find_spec(self, fullname, path=None, target=None):  # finder protocol
        top = fullname.partition(".")[0]
        if top in self._allowed:
            return None
        if _lives_in_stdlib(top):
            # sys.stdlib_module_names omits platform-generated stdlib modules
            # (e.g. _sysconfigdata__darwin_darwin, pulled in by zoneinfo /
            # sysconfig); resolving the file under the stdlib directory is
            # the honest test of "part of the interpreter, not a dependency".
            self._allowed.add(top)
            return None
        raise LocksetImportError(f"{top} is not in {self._label}", name=fullname)


_STDLIB_DIR = os.path.dirname(os.__file__)


def _lives_in_stdlib(top: str) -> bool:
    spec = importlib.machinery.PathFinder.find_spec(top)
    origin = getattr(spec, "origin", None) if spec is not None else None
    if not origin or origin in ("built-in", "frozen"):
        return bool(spec) and not origin  # namespace pkgs have no origin; not stdlib
    return origin.startswith(_STDLIB_DIR) and "site-packages" not in origin


def normalise(name: str) -> str:
    """PEP 503 distribution-name normalisation."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(path: Path) -> set[str]:
    """Normalised distribution names named by a requirements file.

    Follows ``-r`` includes (``requirements.txt`` chains to
    ``requirements-demo.txt``); the compiled ``*.lock.txt`` files have none.
    Handles extras and any specifier form (``==``, ``>=``, markers).
    """
    names: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r") or line.startswith("--requirement"):
            included = line.split(maxsplit=1)[1].strip() if " " in line else line[2:].strip()
            names |= parse_pins(path.parent / included)
            continue
        if line.startswith("-"):
            continue
        match = _REQ_NAME_RE.match(line)
        if match:
            names.add(normalise(match.group(1)))
    return names


def top_level_modules(pinned: set[str]) -> tuple[set[str], list[str]]:
    """(top-level module names the pinned dists provide, pinned-but-absent dists)."""
    dist_to_modules: dict[str, set[str]] = {}
    for module, dists in packages_distributions().items():
        for dist in dists:
            dist_to_modules.setdefault(normalise(dist), set()).add(module)
    modules = {m for dist in pinned for m in dist_to_modules.get(dist, ())}
    not_installed = sorted(pinned - dist_to_modules.keys())
    # A pinned distribution this venv does not have contributes its own name
    # (both spellings) as a best-effort module guess, so it is allowed rather
    # than silently blocked: whether the dev venv happens to have it installed
    # is not what is under test. Empty today for every requirements set here.
    modules |= {name for dist in not_installed for name in (dist, dist.replace("-", "_"))}
    return modules, not_installed


def main(argv: list[str]) -> int:
    req_files = [Path(a).resolve() for a in argv[1:]]
    label = " + ".join(f.name for f in req_files)
    pinned: set[str] = set()
    for f in req_files:
        pinned |= parse_pins(f)
    modules, pinned_not_installed = top_level_modules(pinned)

    allowed = modules | {"original"} | set(sys.stdlib_module_names) | set(sys.builtin_module_names)
    sys.meta_path.insert(0, LocksetFinder(allowed, label))

    try:
        from original import repository
    except LocksetImportError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    try:
        repository.get_repository()
    except LocksetImportError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "backend": repository.backend_name(),
                "lockset": label,
                "pinned_not_installed": pinned_not_installed,
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    sys.exit(main(sys.argv))
