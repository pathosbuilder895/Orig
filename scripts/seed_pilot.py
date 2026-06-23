#!/usr/bin/env python
"""
seed_pilot.py — populate a realistic, named pilot tenant so the logged-in
product actually looks alive (real roster, real baselines, real scored work).

Unlike the synthetic showcase baked into the frontend, this writes through the
*real* pipeline: it registers a tenant, creates named students, ingests several
authenticated baseline samples each, and scores a submission per student so the
arc, manifests, and roster status are genuine. A professor token for the tenant
is printed at the end so you can view it in the dashboard.

Run:
    .venv/bin/python scripts/seed_pilot.py            # writes to the default profiles.db
    ORIGINAL_DB=demo/seed.db .venv/bin/python scripts/seed_pilot.py

Then restart the dev/preview server (it caches profiles in memory) and, in the
browser console on professor.html, paste the token line printed below.
"""

import os
import sys

# The adaptive pipeline + manifests must be on so scoring records an arc/status.
os.environ.setdefault("CONTEXT_MANIFEST_ENABLED", "1")
os.environ.setdefault("ADAPTIVE_WEIGHTS_ENABLED", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env so the minted professor token is signed with the SAME SECRET_KEY the
# running server uses — otherwise the token won't verify and the roster falls
# back to the unscoped/demo view.
from original._env import load_env_file          # noqa: E402
load_env_file()

from original import store                       # noqa: E402
from original import principal as principal_mod  # noqa: E402
from original.schemas import AddSampleRequest, ScoreSubmissionRequest  # noqa: E402

# original/api.py is shadowed by the original.api package, so load the legacy
# demo module by path (exactly as run.py / the test-suite do) to reach its
# endpoint functions directly.
import run  # noqa: E402
run.load_legacy_demo_app()
_legacy = sys.modules["original._legacy_demo_api"]
add_baseline = _legacy.add_baseline
score_submission = _legacy.score_submission

TENANT_ID = "pilot-seminary"
TENANT_NAME = "Pilot Seminary"

# Five students, each with a distinct, recognisable voice across three samples.
STUDENTS = [
    {
        "slug": "alewis", "name": "Aiden Lewis",
        "samples": [
            "Justification is not a reward the conscience earns but a verdict the "
            "conscience receives. The believer does not climb toward acceptance; "
            "acceptance descends, and the climbing stops. When Paul presses this point "
            "in Romans he is not flattering the reader's effort but dismantling it, so "
            "that grace might stand alone and unembarrassed. The argument moves in plain "
            "declaratives, each one carrying a weight the next must answer for, until the "
            "conclusion arrives less as surprise than as something already half-known.",
            "Consider how the parable withholds its hand. The father runs, but the "
            "narrative does not tell us what the son felt; it shows the robe, the ring, "
            "the fattened calf, and lets the objects do the theology. This is restraint "
            "in service of mercy. The plainness is earned, for every word is common and "
            "the thought is not, and the reader is left to supply the weeping the text "
            "declines to name.",
            "Faith, then, is less a possession than a posture. It does not grip; it "
            "receives. The hand that clutches cannot also be open, and the gospel asks "
            "for the open hand. I have come to distrust the sermon that flatters the will "
            "and to trust the one that quietly empties it, leaving the hearer with nothing "
            "but the gift and the Giver.",
        ],
    },
    {
        "slug": "bokafor", "name": "Blessing Okafor",
        "samples": [
            "The doctrine of the Trinity is not a puzzle to be solved but a communion to "
            "be entered. We do not first understand and then adore; we adore, and in "
            "adoring begin to understand. The Cappadocians knew this, which is why their "
            "theology reads like prayer that has learned grammar. To speak of the divine "
            "persons is to speak of a love so complete that it overflows its own life and "
            "calls a world into being out of sheer abundance, not need.",
            "When the church confesses one essence in three persons, it is guarding "
            "something tender, not erecting something rigid. The guardrails exist because "
            "the road runs along a cliff of glory. Heresy is rarely malice; more often it "
            "is impatience, the refusal to hold two true things at once until they ripen "
            "into worship rather than contradiction.",
            "Pentecost completes what Christmas began: God not only with us but within us. "
            "The Spirit does not replace the Son's work but seals it, writing the gospel on "
            "the soft tissue of the will. I find that the deeper one goes into the doctrine "
            "of the Spirit, the quieter one becomes, for the Spirit's signature is not noise "
            "but fruit, grown slowly and in season.",
        ],
    },
    {
        "slug": "cmendez", "name": "Camila Mendez",
        "samples": [
            "Augustine's restlessness is not a flaw in the human heart but its compass. "
            "The same hunger that drives us toward lesser goods, when reordered, drives us "
            "home. Sin is not desire but desire misaimed, a bow drawn with great strength "
            "and pointed at the wrong target. Grace does not slacken the bow; it turns the "
            "archer, so that the very intensity that ruined us becomes the energy of our "
            "return.",
            "I have noticed that the saints are rarely tepid people. Their conversions do "
            "not extinguish their fire; they redirect it. Paul persecuting and Paul "
            "preaching are recognizably the same man, the same zeal, now serving instead "
            "of savaging. This consoles me, for it suggests that grace works with the "
            "temperament it finds rather than demanding a different one.",
            "Prayer, on this reading, is the slow education of desire. We bring our wants "
            "to God not because he is ignorant of them but because in the bringing they "
            "are sorted, weighed, and sometimes quietly withdrawn. The hand that learns to "
            "pray learns first to let go, and only then to ask.",
        ],
    },
    {
        "slug": "dpark", "name": "Daniel Park",
        "samples": [
            "Scripture interprets scripture, but it does so in the company of the church "
            "and under the lamp of the Spirit. The lone reader, however brilliant, is "
            "prone to mistake his own echo for revelation. Tradition is not a cage but a "
            "choir; it teaches the solitary voice to find its pitch. I read the fathers "
            "not to be told what to think but to be kept from thinking alone.",
            "The canon is not an arbitrary fence around inspired texts; it is the church's "
            "memory of which voices proved trustworthy under pressure. Councils did not "
            "create authority any more than a botanist creates a species; they recognized "
            "what was already growing. To confuse recognition with invention is to mistake "
            "the map for the territory.",
            "Exegesis without humility curdles into ideology. The text is older than my "
            "questions and wiser than my certainties, and the first discipline of "
            "interpretation is to let it ask me something before I cross-examine it. The "
            "best commentaries leave me quieter than they found me.",
        ],
    },
    {
        "slug": "erahman", "name": "Esther Rahman",
        "samples": [
            "Lament is not the failure of faith but one of its native tongues. The psalmist "
            "who cries out is not less devout than the one who praises; he is praying with "
            "the part of himself that hurts. A faith that cannot complain to God has not yet "
            "learned to trust him fully, for we withhold our wounds only from strangers.",
            "Hope is not optimism. Optimism reads the trend lines and expects improvement; "
            "hope reads the resurrection and expects God. The difference matters most in the "
            "dark, when the trend lines say nothing and only the promise remains. I would "
            "rather have a hope that can survive bad news than an optimism that depends on "
            "good.",
            "The church at its best is a community of the wounded who have stopped pretending. "
            "Confession is the door, and it only opens inward, toward honesty. I have found "
            "more healing in rooms where people told the truth about their failures than in "
            "any sermon that tidied them away.",
        ],
    },
]


def main() -> int:
    db_label = os.environ.get("ORIGINAL_DB", "profiles.db (default)")
    print(f"Seeding pilot tenant into: {db_label}\n")

    # 1) Register the tenant as a demo-visible environment so it is readable and a
    #    minted professor token works against it immediately.
    store.put_tenant(TENANT_ID, TENANT_NAME, environment="demo",
                     meta={"seeded_by": "seed_pilot.py"})
    print(f"✓ tenant {TENANT_ID!r} ({TENANT_NAME})")

    seeded = 0
    for i, s in enumerate(STUDENTS):
        sid = f"{TENANT_ID}:{s['slug']}"
        store.get_or_create(sid)
        store.set_display_name(sid, s["name"])
        for j, text in enumerate(s["samples"]):
            try:
                add_baseline(sid, AddSampleRequest(
                    text=text, assignment=f"Reflection {j + 1}", provenance="verified"))
            except Exception as e:  # pragma: no cover - seed is best-effort
                print(f"  ! baseline {j} failed for {s['name']}: {e}")

        # Score one submission so the arc + manifest + roster status are real.
        # Most students submit in-voice (→ clear); one is given a different
        # author's text so the roster shows a genuine "needs review".
        if i == len(STUDENTS) - 1:
            probe_text = STUDENTS[0]["samples"][0]      # someone else's voice
            label = "Take-home Essay (cross-voice probe)"
        else:
            probe_text = s["samples"][-1]
            label = "Take-home Essay"
        try:
            res = score_submission(sid, ScoreSubmissionRequest(text=probe_text, assignment=label))
            action = getattr(getattr(res, "recommendation", None), "action", "?")
            print(f"✓ {s['name']:<16} {sid:<28} 3 baselines · scored → {action}")
        except Exception as e:  # pragma: no cover
            print(f"✓ {s['name']:<16} {sid:<28} 3 baselines · score skipped ({e})")
        seeded += 1

    token = principal_mod.mint_principal_token("prof_pilot", "professor", TENANT_ID)
    print(f"\nSeeded {seeded} students into {TENANT_ID}.")
    print("\nTo view as the pilot professor, restart the server, open professor.html,")
    print("and paste this in the browser console, then reload:\n")
    print(f"  localStorage.setItem('original_principal_token', '{token}');")
    print(f"  localStorage.setItem('original_tenant', '{TENANT_ID}');")
    print(f"  localStorage.setItem('original_role', 'professor'); location.reload();")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
