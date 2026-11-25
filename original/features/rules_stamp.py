"""The rules-version stamp stored with a measurement made under versioned
rules: the splitter's (``features/matter.py`` ``RULES_VERSION``) and the
paragraph rule's (``features/paragraphs.py`` ``RULES_VERSION``).

A stored measurement (``BaselineSample.extra_vectors`` with its stamps in
``extra_vector_rules``, a teacher's ``choice_vectors`` with ``choice_rules``)
is current only when every rule set its measurement id uses
(``feature_flags.MEASUREMENTS``: the splitter bit, the paragraph bit) is at
today's version. One that is not is served as missing and refilled by
``scripts/backfill_measurements.py``.

Stamp format, per measurement id:

* splitter only ("matter", "fs2+matter"): the splitter version as an int,
  ``1``, exactly as stored before the paragraph rule was versioned;
* paragraph rule only ("para", "fs2+para"): ``"p1"``;
* both ("matter+para", "fs2+matter+para"): ``"m1.p1"``.

An int read on an id with the paragraph bit (written before the paragraph
rule was versioned) is that id's splitter version, its paragraph version
unstamped. Unstamped parts are taken as each module's
``UNSTAMPED_RULES_VERSION``. Ids with neither bit ("v1", "fs2") carry no stamp.
"""

from __future__ import annotations

import re

from . import matter as _matter
from . import paragraphs as _paragraphs

_STAMP = re.compile(r"(?:m([1-9]\d{0,8})\.)?p([1-9]\d{0,8})")


def _bits(measurement: str) -> tuple[bool, bool]:
    from . import feature_flags as _ff

    key = _ff.MEASUREMENTS.get(measurement, (1, False, False))
    return bool(key[1]), bool(key[2])


def uses_rules(measurement: str) -> bool:
    """Does ``measurement`` use a versioned rule set (splitter or paragraphs)?"""
    return any(_bits(measurement))


def stamp(measurement: str) -> int | str | None:
    """Today's stamp for ``measurement`` (None: it uses no versioned rules)."""
    matter_on, para_on = _bits(measurement)
    if not para_on:
        return _matter.RULES_VERSION if matter_on else None
    para = f"p{_paragraphs.RULES_VERSION}"
    return f"m{_matter.RULES_VERSION}.{para}" if matter_on else para


def parse(raw: object) -> dict[str, int] | None:
    """A stored stamp's versions (``{"m": .., "p": ..}``, parts it does not
    name left out), or None when it is not a stamp."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        return {"m": raw}
    if isinstance(raw, str):
        found = _STAMP.fullmatch(raw)
        if found:
            out = {"p": int(found.group(2))}
            if found.group(1):
                out["m"] = int(found.group(1))
            return out
    return None


def current(measurement: str, raw: object) -> bool:
    """A stored ``measurement`` with this stamp (None: unstamped) was made
    under every rule set it uses as they are now. A version other than
    today's (older, or newer from a rolled-back deploy) and a stamp that is
    not one are not."""
    versions = {} if raw is None else parse(raw)
    if versions is None:
        return False
    matter_on, para_on = _bits(measurement)
    if matter_on and _matter.RULES_VERSION != versions.get("m", _matter.UNSTAMPED_RULES_VERSION):
        return False
    return not para_on or _paragraphs.RULES_VERSION == versions.get(
        "p", _paragraphs.UNSTAMPED_RULES_VERSION
    )
