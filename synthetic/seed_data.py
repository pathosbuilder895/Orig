"""
synthetic/seed_data.py — Pre-built synthetic student profiles.

Populates the in-memory store with students whose feature vectors
match the personas already present in the frontend prototype.

Samples:
  - BASELINE_A–E: authentic theological prose (varied styles, hedging,
    first-person voice, questions, discourse markers).
  - BASELINE_LONG: 800+ word long-form authentic essay.
  - AUTHENTIC_SUBMISSION: submission matching baseline voice (low deviation).
  - ANOMALOUS_SUBMISSION: AI-generated prose (high deviation signal).
  - chen_m: single baseline only — lets demo watch confidence build live.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from original import store
from original.features.pipeline import feature_vector
from original.quantum.state import BaselineSample


# ── Authentic baseline texts ─────────────────────────────────────────────────
# Characteristics: first-person voice, hedging, questions, strong theological
# register, discourse markers, cohesion, varied sentence openers.

BASELINE_A = """
The doctrine of justification by faith alone remains perhaps the most contested
terrain in contemporary ecumenical theology. When Paul writes in Romans 3:28
that "a person is justified by faith apart from the works of the law," he employs
a forensic metaphor that I find both clarifying and, in certain respects, limiting.
The forensic framework captures the declarative character of justification—God
pronounces the sinner righteous—but may understate the participatory dimension
that union with Christ supplies.

However, I should be careful not to overstate this tension. As N. T. Wright argues,
the Pauline declaration is not simply a legal fiction; it is grounded in the
representative work of Christ and the inaugurated eschatology in which the believer
already participates. This suggests that the forensic and participatory accounts are
complementary rather than competitive. Perhaps the more fruitful question is not
which metaphor is correct, but which receives undue emphasis in any given tradition.

Furthermore, the role of the Holy Spirit in sealing and applying justification
deserves careful attention. Might it be the case that the pneumatological dimension
has been systematically underweighted in Western treatments? Ephesians 1:13 and
Romans 8:15-17 seem to indicate that the Spirit's witness is constitutive of
assurance, not merely confirmatory. This is a question that Luther, to his credit,
never fully resolved—though his pastoral instincts often corrected his formal theology.

Therefore, my conclusion is provisional: the forensic account provides the logical
grammar of justification, while the participatory account supplies its ontological
depth. Neither should be collapsed into the other. The tradition that reads Paul
most carefully will hold both in productive tension.
"""

BASELINE_B = """
In the history of Christian thought, the question of how the atonement accomplishes
its effects has generated a remarkable diversity of theories. Anselm's satisfaction
model, Abelard's moral influence theory, and the penal substitution account developed
by the Reformers each emphasize different dimensions of what Christ's death achieves.
I want to suggest that this diversity is not a theological embarrassment but rather
a feature of the subject matter itself—the cross is an event of such density that
no single theory exhausts its meaning.

That said, penal substitution warrants particular attention in the context of
SBTS's confessional heritage. As the Abstract of Principles affirms, Christ "bore
our sins in his own body on the tree." This language implies a substitutionary
structure: Christ stands in the place of the guilty party and receives the
consequences of their offense. Although critics have objected that this portrays
an ethically troubling picture of divine justice, I think these objections typically
misread the trinitarian structure of the transaction. The Father does not punish an
unwilling Son; the Son freely undertakes the mission the triune God wills.

Nevertheless, I should acknowledge that penal substitution, taken alone, can
generate distorted spiritualities—a forensic obsession with guilt management at
the expense of transformative union with the risen Christ. This is why I would argue
that any adequate account of the atonement must integrate Christus Victor, moral
exemplar, and participatory dimensions alongside the penal. The atonement is not a
single transaction but a multivalent event in the economy of salvation.

Consequently, the pastoral question becomes: which atonement metaphor serves the
formation of disciples in a given context? This is a question I remain genuinely
uncertain about, and one that deserves further exploration in homiletical theology.
"""

BASELINE_C = """
The relationship between Scripture and tradition remains one of the most generative
fault lines in contemporary theology. For evangelical Protestants committed to
sola scriptura, tradition is at best a fallible guide and at worst an accumulation
of human additions that distort the apostolic deposit. Yet this account, I would
argue, misrepresents how Scripture has actually functioned in the church.

Consider the case of the canon itself. The identification of which texts belong to
the New Testament was not accomplished by Scripture alone—it required conciliar
discernment, apostolic testimony, and the Spirit's guidance through the community
of faith. Therefore, the Reformed slogan that Scripture interprets Scripture (sacra
scriptura sui ipsius interpres) is true as far as it goes, but it presupposes a
prior act of canonization that is itself a traditioned judgment.

How should we respond to this? Perhaps by recovering a more nuanced account of
tradition—one that distinguishes, as Yves Congar suggested, between Tradition
(the living transmission of the apostolic faith) and traditions (the accumulated
practices and formulations of particular communions). The former has normative
force; the latter is subject to revision in light of Scripture.

Furthermore, the hermeneutical question is not whether we interpret Scripture
within a tradition—we all do—but whether our tradition has been sufficiently formed
by Scripture to serve as a reliable guide. This is the question I find most pressing
for contemporary Baptist theology, and it is not one that sola scriptura as a formal
principle alone can answer.
"""

BASELINE_D = """
Reading Barth's doctrine of election again this semester, I am struck by how much
depends on the identification of Jesus Christ as both the electing God and the
elected man. It is a bold move—arguably the most ambitious revision in the history
of Reformed theology—and I confess I am still working out whether I find it
fully persuasive.

The problem Barth is solving is real enough. The older Calvinist scheme produced
a God who decrees reprobation from eternity with apparent indifference to the
particularity of Jesus. Barth rightly objects to this abstraction. If God is
who God is in the act of revelation in Christ, then it seems incoherent to speak
of a hidden decree behind Christ's back. The decretum absolutum must be replaced,
or at least radically reconceived.

However, I am not sure Barth's solution fully escapes the difficulties it diagnoses.
By making Jesus Christ the subject and object of election, Barth appears to
universalize the scope of grace in ways that sit uneasily with his own protests
against universalism. The trajectory of Church Dogmatics II/2 seems to push toward
apokatastasis even if Barth resists the label. One wonders whether the logic of
the position, followed consistently, demands a conclusion its author declines to draw.

That said, I want to be careful not to dismiss Barth too quickly on this point.
Perhaps the refusal to draw the universalist conclusion is itself theologically
principled—a recognition that the freedom of God cannot be enclosed within the
logic of any systematic argument, however elegant. It may be that what looks like
inconsistency is in fact an appropriate doctrinal humility.

What I find most generative in Barth, regardless of how these questions resolve,
is the insistence that election is fundamentally good news—not a threat to be
managed pastorally but the ground of every believer's confidence before God.
That emphasis seems to me irreversible, whatever revisions subsequent theologians
may need to make at the edges of the system.
"""

BASELINE_E = """
Covenant theology has long provided the organizing framework for Reformed
soteriology, but I have been asking lately whether the covenant structure can bear
all the weight we place upon it. The distinction between the covenant of works and
the covenant of grace, while elegant as a theological schema, sometimes creates
more exegetical problems than it solves.

Consider, for instance, the status of Abraham in the Pauline argument of Galatians 3.
Paul clearly deploys the Abrahamic covenant as a counter to the Mosaic law, treating
the promise to Abraham as anticipatory of the new covenant rather than as a species
of the old. This seems congenial to Reformed covenant theology. But the question of
how the Mosaic covenant itself fits into the scheme is considerably more complex—a
complexity that the Westminster Standards manage rather than resolve.

I should acknowledge that my reading of Galatians may be unduly influenced by the
New Perspective debates of the last three decades. Sanders, Dunn, and Wright have
reoriented the field in ways that make it genuinely difficult to return to a
pre-NPP reading with full naivety. Whether that influence is entirely salutary is
another question—there is something valuable in the older Protestant insistence that
Paul really was concerned with individual guilt and divine verdict, not only with
Jewish-Gentile boundary markers.

My tentative conclusion is that covenantal frameworks remain indispensable for
systematic theology but need to be held more loosely at the level of exegesis.
The biblical texts are richer and stranger than any single theological grid can
fully capture, and the task of the exegete is to let them resist as well as
confirm our systems.
"""

BASELINE_LONG = """
The question of what it means for the church to be a hermeneutical community has
occupied me throughout this course, and I want to use this final reflection to
pull together several threads that have been developing across the semester.

At the outset, I was inclined to accept a fairly individualist account of biblical
interpretation—the idea that the Spirit works primarily through the encounter
between the individual reader and the text, with the community playing a secondary
role of verification and accountability. This view has obvious appeal in a
tradition shaped by the Reformation's anti-hierarchical impulse. If the priesthood
of all believers means anything, it must mean that no ecclesiastical authority
stands between the believer and the text.

However, my reading of John Howard Yoder this semester has complicated this picture
significantly. Yoder's account of the community as the primary locus of moral
discernment—the gathered congregation weighing together what obedience requires—
translates, I think, into a corresponding account of interpretive practice. The
congregation is not simply a collection of individual interpreters who happen to
share a building; it is a traditioned community whose shared practices, disciplines,
and memories constitute the interpretive horizon within which any individual reading
takes place. The individual who reads without the community reads with an invisible
tradition nonetheless—typically the tradition of modern Western individualism.

This does not mean, of course, that the community is always right. The history of
the church is littered with examples of communal interpretive failure, from the
church's accommodation to Roman imperial ideology in the fourth century to the
theological apologetics for slavery produced by Southern Presbyterian divines in
the nineteenth. The Spirit's guidance of the community is not a guarantee of
inerrancy; it is rather an ongoing work of correction and renewal that operates
precisely through the tension between the text and the community's self-understanding.

What, then, is the relationship between Scripture and the Spirit's continuing work
in the community? I want to suggest that the Spirit functions as what we might call
an adversarial reader—one who presses the community's interpretation toward
dimensions of the text that its current self-interest or cultural location tends to
suppress. This is why reading across traditions is so important: the ecumenical
encounter brings to light the suppressions and emphases of any single tradition.
A Baptist reading Luke 14 in conversation with Catholic social teaching will attend
to things that a strictly intramural reading might miss, and vice versa.

Furthermore, I think the hermeneutical question cannot be separated from the
formation question. How we read Scripture is inseparable from the kind of people
we are becoming through its reading. The lectio divina tradition understood this
long before it became a subject of academic hermeneutical theory: the text shapes
the reader over time, not merely informing the intellect but reorienting the
affections and the will. This is one reason why the speed of contemporary
theological education worries me—there is something in the tradition of extended,
contemplative engagement with texts that cannot be adequately replicated by
coverage-driven curricula, however rigorous.

My concluding conviction is therefore somewhat paradoxical: the community is
necessary for faithful interpretation, and yet the community must remain perpetually
open to being undone by the text it reads. The church's authority in interpretation
is not the authority of a magistrate over the text but the authority of the
practiced reader who has spent long enough with the text to recognize when it is
speaking against her. This kind of authority is always at risk, always in need of
renewal, and always dependent on the gracious work of a Spirit who refuses to
become the possession of any single tradition or reading community.
"""

# ── Anomalous submission texts ───────────────────────────────────────────────
# Characteristics: no hedging, no first-person, no questions, high assertion,
# flat sentence openers, no adversative discourse markers, uniform sentence
# length, generic theological language. Deliberately resembles AI-generated prose.

ANOMALOUS_SUBMISSION = """
The doctrine of justification is foundational to Christian soteriology.
Justification involves the forensic declaration of righteousness based on
the imputed merits of Christ. The substitutionary work of Christ on the cross
provides the basis for this declaration. Penal substitution is the correct
understanding of the atonement according to Reformed theology. The Protestant
tradition has consistently maintained this position against Roman Catholic
and Eastern Orthodox alternatives.

The biblical evidence for justification by faith alone is substantial.
Numerous passages in the Pauline corpus establish the connection between
faith and justification. The Westminster Confession of Faith accurately
summarizes the biblical teaching on this subject. Confessional Protestantism
has preserved this doctrine through careful exegesis and systematic formulation.

The relationship between justification and sanctification is important.
Justification is a legal declaration while sanctification is a transformative
process. Both are grounded in union with Christ. The ordo salutis developed
by Protestant scholasticism provides a helpful framework for understanding
these distinctions. Theological precision is required when discussing these
matters to avoid antinomianism and legalism.

The contemporary theological landscape presents challenges to the traditional
understanding of justification. New Perspective scholarship has proposed
alternative readings of Paul. These proposals have generated significant debate
in evangelical circles. The traditional understanding remains the most exegetically
defensible position and should be maintained in confessional contexts.
"""

ANOMALOUS_SUBMISSION_2 = """
The concept of covenant theology provides the organizing structure for Reformed
soteriology. The covenant of works established the initial relationship between
God and Adam. The covenant of grace was inaugurated following the fall of mankind.
Jesus Christ serves as the mediator of the new covenant. The Westminster Standards
provide a comprehensive account of these covenantal distinctions.

The Abrahamic covenant demonstrates the continuity of the covenant of grace
throughout redemptive history. God's promise to Abraham constitutes the foundational
statement of the gospel. Paul's argument in Galatians affirms the priority of the
Abrahamic covenant over the Mosaic administration. The relationship between the
testaments is one of continuity and progressive revelation.

The Mosaic covenant functioned as a national administration of the covenant of
grace. Israel's election was based solely on divine grace rather than human merit.
The sacrificial system of the Mosaic law prefigured the atoning work of Christ.
The ceremonial laws found their fulfillment in the person and work of Jesus.

The new covenant surpasses the Mosaic administration in clarity and finality.
The indwelling of the Holy Spirit is the distinctive mark of new covenant membership.
The church is the continuation of the covenant community in the new covenant era.
Covenant theology provides the most coherent account of biblical theology available.
"""

# ── Authentic submission (should score LOW deviation) ───────────────────────
AUTHENTIC_SUBMISSION = """
Returning to the question of justification after completing this semester's reading,
I find that my understanding has grown in some ways and become more uncertain in others.
The forensic account I entered the course with has not exactly been dismantled, but
it has been complicated—and I think that complication is itself theologically useful.

What has most pressed on me is the relationship between justification and participation.
I used to think of these as two separable doctrines that could be discussed in sequence;
reading Gorman on Paul has persuaded me that this is a mistake. For Paul, to be
justified is to be incorporated into the cruciform pattern of Christ's own existence.
The forensic declaration is not separable from the new relational reality it inaugurates.
I still think the legal language is primary—it captures something essential about the
objective, extra nos character of grace—but I can no longer treat it as exhaustive.

Moreover, I have come to see that my earlier anxiety about the New Perspective was
somewhat misdirected. Wright's account of justification as covenant membership
declaration does not obviously contradict the Reformation account so much as it
recontextualizes it. Whether sinners are declared righteous as a verdict in a cosmic
courtroom or as an announcement of covenant inclusion may be a question of metaphorical
emphasis rather than substantive doctrinal disagreement. Both images, it seems to me,
are doing genuine theological work in Paul.

That said, I remain unpersuaded by some of the stronger NPP claims. The insistence that
Paul's critique of "works of the law" targets only ethnic boundary markers seems to me
exegetically underdetermined. Romans 4, at least, seems to be addressing individual
human merit as such—not merely Jew-Gentile social dynamics. Perhaps the two concerns
are not as separable as NPP readings tend to assume.

What I carry forward from this course is not a settled answer but a set of better
questions—about the relationship of the legal and participatory metaphors, about the
role of the Spirit in applying what Christ accomplished, and about the pastoral
implications of different emphases. I find that uncertainty more generative than
the false clarity with which I arrived.
"""


# ── Seed function ─────────────────────────────────────────────────────────────

def seed(verbose: bool = True) -> None:
    """Populate the store with synthetic student profiles."""

    students = [
        {
            "id": "whitfield_j",
            "name": "James Whitfield",
            "baselines": [
                ("Week 1 Reflection — Baseline",       "proctored", "2025-01-24", BASELINE_A),
                ("Week 3 Reflection — Baseline",       "proctored", "2025-02-07", BASELINE_B),
                ("Week 5 Reflection",                   "verified",  "2025-02-21", BASELINE_C),
                ("Barth Election Essay",                "proctored", "2025-03-07", BASELINE_D),
                ("Covenant Theology Final Reflection",  "verified",  "2025-03-14", BASELINE_LONG),
            ],
            # Clear AI signal — high deviation expected
            "submission": ("Christology Final Paper", "2025-04-01", ANOMALOUS_SUBMISSION),
        },
        {
            "id": "okonkwo_s",
            "name": "Sarah Okonkwo",
            "baselines": [
                ("Week 1 Reflection — Baseline",      "proctored", "2025-01-24", BASELINE_B),
                ("Week 3 Reflection — Baseline",      "proctored", "2025-02-07", BASELINE_A),
                ("Week 5 Reflection",                  "proctored", "2025-02-21", BASELINE_C),
                ("Hermeneutics Long Essay",            "proctored", "2025-03-07", BASELINE_LONG),
                ("Covenant Theology Reflection",       "verified",  "2025-03-14", BASELINE_E),
            ],
            # Second anomalous pattern — slightly different AI style
            "submission": ("Soteriology Research Paper", "2025-04-01", ANOMALOUS_SUBMISSION_2),
        },
        {
            "id": "osei_d",
            "name": "Daniel Osei",
            "baselines": [
                ("Week 1 Reflection — Baseline",  "proctored", "2025-01-24", BASELINE_C),
                ("Week 3 Reflection — Baseline",  "verified",  "2025-02-07", BASELINE_A),
                ("Week 5 Reflection",              "verified",  "2025-02-21", BASELINE_B),
                ("Barth Election Essay",           "proctored", "2025-03-07", BASELINE_D),
                ("Long Essay — Hermeneutics",      "verified",  "2025-03-14", BASELINE_LONG),
            ],
            # Moderately anomalous (mix of authentic + shifted rhetoric)
            "submission": (
                "Pneumatology Essay", "2025-04-01",
                BASELINE_B[:800] + "\n\n" + ANOMALOUS_SUBMISSION[:600]
            ),
        },
        {
            "id": "mercer_l",
            "name": "Lydia Mercer",
            "baselines": [
                ("Week 1 Reflection — Baseline",     "proctored", "2025-01-24", BASELINE_A),
                ("Week 3 Reflection — Baseline",     "proctored", "2025-02-07", BASELINE_C),
                ("Week 5 Reflection",                 "proctored", "2025-02-21", BASELINE_B),
                ("Covenant Theology Essay",           "verified",  "2025-03-07", BASELINE_E),
                ("Hermeneutics Final — Long Form",    "verified",  "2025-03-14", BASELINE_LONG),
            ],
            # Authentic-style submission — low deviation expected
            "submission": ("Christology Week 7 Reflection", "2025-04-01", AUTHENTIC_SUBMISSION),
        },
        {
            # Single baseline — lets professor watch confidence build live in demo
            "id": "chen_m",
            "name": "Michael Chen",
            "baselines": [
                ("Week 1 Reflection — Baseline", "proctored", "2025-01-24", BASELINE_D),
            ],
            "submission": None,  # No submission scored yet
        },
    ]

    for s in students:
        state = store.get_or_create(s["id"])
        for assignment, provenance, date, text in s["baselines"]:
            from original.constants import AUTH_WEIGHTS
            vec = feature_vector(text)
            sample = BaselineSample(
                text=text,
                vector=vec,
                provenance=provenance,
                auth_weight=AUTH_WEIGHTS[provenance],
                assignment=assignment,
                submitted_at=date,
            )
            state.add_sample(sample)

        if verbose:
            print(f"  {s['name']} ({s['id']}): {state.authenticated_count} baseline samples, "
                  f"purity={state.purity:.3f}")

    if verbose:
        print(f"Seeded {len(students)} students into store.")


if __name__ == "__main__":
    seed(verbose=True)
