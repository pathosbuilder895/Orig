"""
validation/generate_modern_corpus.py — Generate modern theological validation corpus.

Creates 5 synthetic seminary student authors with distinct stylometric profiles,
AI-generated essays, and cross-author ghostwriting cases.

Run from project root:
    python -m validation.generate_modern_corpus
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "corpus"
MANIFEST_PATH = Path(__file__).parent / "manifest.json"

random.seed(42)

# ── Student stylometric profiles ──────────────────────────────────────────────
# Each profile controls essay generation style

STUDENTS = {
    "seminary_01": {
        "name": "student_01",
        "tradition": "Reformed",
        "native_english": True,
        "style": "analytical",   # short declarative sentences, heavy citation, Calvinist vocab
    },
    "seminary_02": {
        "name": "student_02",
        "tradition": "Catholic",
        "native_english": True,
        "style": "rhetorical",   # long complex sentences, Latin phrases, scholastic structure
    },
    "seminary_03": {
        "name": "student_03",
        "tradition": "Wesleyan",
        "native_english": False,
        "style": "pastoral",     # personal anecdotes, questions to reader, simpler syntax
    },
    "seminary_04": {
        "name": "student_04",
        "tradition": "Lutheran",
        "native_english": True,
        "style": "systematic",   # numbered sub-points, passive voice, academic hedging
    },
    "seminary_05": {
        "name": "student_05",
        "tradition": "Baptist",
        "native_english": False,
        "style": "narrative",    # story-driven, present tense, direct address, shorter paragraphs
    },
}

TOPICS = [
    ("justification", "The doctrine of justification by faith alone"),
    ("grace",         "The nature of divine grace and human freedom"),
    ("ecclesiology",  "The nature and mission of the Church"),
    ("prayer",        "The theology and practice of Christian prayer"),
    ("sin",           "The doctrine of original sin and its consequences"),
]

# ── Essay text templates by style ─────────────────────────────────────────────

def essay_reformed_justification(variation: int) -> str:
    intros = [
        "The doctrine of justification stands at the heart of Protestant theology.",
        "Justification by faith alone remains the article by which the church stands or falls.",
        "No doctrine deserves more careful attention than the forensic declaration of righteousness.",
    ]
    return f"""{intros[variation % len(intros)]} Luther's rediscovery of Paul's letter to the Romans shattered the medieval synthesis of merit and grace. God declares the sinner righteous; He does not make him righteous first and then declare it. This distinction is not semantic. It is the difference between a gospel that saves and a gospel that enslaves.

Calvin pressed the point further. In the Institutes, he argues that justification is the "main hinge on which religion turns." The imputation of Christ's active and passive obedience is the foundation upon which all assurance rests. The believer receives an alien righteousness—a righteousness not worked up from within, but credited from without. This is the scandalous generosity of the covenant of grace.

Critics have argued that such a forensic account strips justification of its transformative power. They claim that if righteousness is merely imputed, the moral life becomes an appendage. But this criticism misunderstands the Reformed ordo salutis. Justification and sanctification are distinguished but never separated. The same Spirit who unites the sinner to Christ for justification also dwells within for sanctification. The root produces the fruit; the fruit does not produce the root.

The New Perspective on Paul has complicated this picture. N.T. Wright and others have argued that Paul's concern was not the medieval problem of how a guilty soul finds peace with God, but rather the boundary between Jew and Gentile in the covenant community. There is insight here. Justification does have an ecclesial dimension. But Wright's account underplays the individual before the divine tribunal. Both dimensions must be held together.

For the preacher and the pastor, the doctrine of justification is not merely academic. It is the word that silences the accuser. When conscience cries out, when the devil prosecutes, when the law condemns, the justified sinner points not to his own record but to Christ's. This is the pastoral power of forensic justification. It is the only ground upon which trembling sinners can stand.

The doctrine thus demands both careful exegesis and courageous proclamation. The church that loses its nerve here loses its message. Sola fide is not a slogan from the sixteenth century to be archived. It is the living word of absolution that the gospel speaks to every generation."""


def essay_reformed_grace(variation: int) -> str:
    intros = [
        "Divine grace is sovereign. This is the Reformed confession.",
        "Grace, properly understood, cannot be resisted without ceasing to be grace.",
        "The Augustinian tradition insists that grace precedes and enables every act of faith.",
    ]
    return f"""{intros[variation % len(intros)]} The controversy between Augustine and Pelagius was not a marginal dispute. It went to the center of the Christian understanding of salvation. Pelagius taught that human beings possess the natural capacity to obey God's commands. Augustine replied that the fall had so corrupted the will that apart from divine grace, the sinner cannot choose the good. The Council of Carthage sided with Augustine.

The Reformed tradition, following Augustine through Calvin, affirms total depravity. This does not mean that unregenerate persons are as wicked as they could possibly be. It means that every faculty—intellect, will, affection—has been corrupted by sin. The natural man does not seek God; he suppresses the truth in unrighteousness. Paul's anthropology in Romans 1–3 is unsparing. There is none who seeks God; not even one.

Irresistible grace follows logically from total depravity. If the will is bound, then regeneration must precede faith. God does not offer grace and wait for the sinner to cooperate. He effectually calls, and the one who is called comes. This is not coercion. The regenerate sinner comes willingly—but the willingness is itself the gift. God changes the heart so that what was once despised becomes desired.

Arminian theology objects that this makes God the author of some people's damnation. If grace is irresistible for the elect, what of the reprobate? The Reformed answer is careful: God passes over some in righteous judgment; He does not actively cause their sin. The reprobate receive what they deserve. The elect receive mercy. Neither group receives injustice.

This doctrine, rightly preached, does not produce passivity. It produces humility. The believer who knows that his faith was itself a gift cannot boast. He stands in the grace of God with open hands. Every act of obedience is enabled by the same grace that began the work. The one who began a good work will carry it to completion. This is the pastoral comfort of sovereign grace."""


def essay_reformed_ecclesiology(variation: int) -> str:
    return """The church is not a voluntary association of like-minded believers. This view, common in evangelical culture, misunderstands the biblical ecclesiology. The church is the body of Christ, the assembly of the covenant people, the pillar and ground of the truth. Its nature is given, not constructed.

Calvin identified the marks of the true church as the right preaching of the Word and the right administration of the sacraments. Later Reformed confessions added church discipline as a third mark. These marks function diagnostically. They help the Christian identify where God's people are genuinely gathered. The presence of the marks does not make a perfect church; it makes a church at all.

The relationship between the visible and invisible church requires care. The invisible church is the totality of the elect across all times and places—known to God alone. The visible church is the community that professes faith and submits to the ordained means of grace. The two overlap but are not identical. There are tares among the wheat. The final separation belongs to the eschaton, not to the church's disciplinary process.

Ecclesiology has become contested in ecumenical dialogue. Rome claims that the fullness of the church subsists in the Roman Catholic Church. The Reformation contested this by appeal to the marks. Where the Word is truly preached and the sacraments rightly administered, there is the church of Christ—regardless of episcopal succession. The question of orders is secondary to the question of the gospel.

For seminary students entering ministry, ecclesiology shapes everything. How one understands the church determines how one preaches, counsels, and administers the sacraments. If the church is merely a platform for personal spiritual development, then the sermon becomes self-help and the Lord's Supper becomes a memorial snack. But if the church is the body of Christ, then its gathered worship participates in the ongoing ministry of the risen Lord."""


def essay_reformed_prayer(variation: int) -> str:
    return """Prayer is not a technique for accessing the divine. It is the creature's response to the Creator's address. This distinction matters enormously for how one approaches the theology and practice of Christian prayer. Reformed theology has always grounded prayer in the covenant relationship, not in human spiritual capacity.

Calvin's treatment of prayer in the Institutes remains the most thorough Protestant account. He identifies four rules. First, we must pray with reverence, recognizing to whom we speak. Second, we must pray with a genuine sense of our need and unworthiness. Third, we must abandon all confidence in ourselves and plead for pardon. Fourth, we must pray with confident hope, trusting that God hears and will answer. These rules are not regulations but descriptions of the posture that faith takes before God.

The Lord's Prayer is the paradigm. It begins not with petition but with adoration: hallowed be your name. The vertical dimension precedes the horizontal. The petition for daily bread comes after the petition for the coming of the kingdom. This ordering is significant. It trains the one who prays to reorient life around the divine priority rather than the merely creaturely priority.

Critics of the Reformed account argue that it makes prayer too cognitive and not sufficiently affective. This criticism has force if Reformed prayer is reduced to doctrinal recitation. But Calvin himself was attentive to the affections. He recognized that the heart must be engaged, not merely the intellect. The Psalms—which Calvin called the anatomy of the soul—model the full range of human emotion brought into the presence of God.

Corporate prayer is not simply the aggregation of individual prayers. The gathered church brings its collective need and praise before God. The intercessory prayer of the church participates in the intercession of Christ, the great high priest. This ecclesial dimension of prayer has been underemphasized in individualistic evangelical culture."""


def essay_reformed_sin(variation: int) -> str:
    return """The doctrine of original sin is, to modern sensibilities, among the most offensive claims of classical Christianity. It asserts that the moral corruption that characterizes human existence is not merely a social or developmental problem but a theological one—rooted in the rebellion of the first man and transmitted to his descendants. To take this doctrine seriously is to take the human condition seriously.

Augustine's formulation, developed in controversy with Pelagius and later refined against Julian of Eclanum, identified original sin as both the guilt inherited from Adam and the corruption of human nature that resulted from the fall. Protestants have generally maintained both elements. The Westminster Confession speaks of original sin as involving both the imputation of Adam's first transgression and the corruption of his whole nature.

The exegetical foundation is primarily Romans 5:12–21. Paul draws a parallel between Adam and Christ. As through one man sin entered the world and death through sin, so through one man—the second Adam—righteousness and life came to many. The parallelism is precise. Adam acted as a representative head; his act had consequences for all who were in him. The doctrine of original sin is, in this sense, inseparable from the doctrine of substitutionary atonement.

Contemporary theology has struggled with the historical Adam. If Paul's Adam was not a historical individual, what becomes of the parallel with Christ? Some have proposed that original sin can be grounded in evolutionary psychology rather than historical fall. The appeal is understandable, but the exegetical and theological costs are high. The corporate solidarity of humanity in sin requires an explanation. The Augustinian account provides one that coheres with the biblical narrative.

For ministry, the doctrine of original sin is not a stick with which to beat the congregation. It is the diagnosis that makes the cure comprehensible. Without a clear account of the human problem, the gospel loses its urgency. The good news is only good news when the bad news has been honestly faced."""


# Catholic / Rhetorical style essays

def essay_catholic_justification(variation: int) -> str:
    intros = [
        "The Council of Trent's decree on justification, promulgated in 1547, represents the most comprehensive Catholic treatment of this doctrine in history.",
        "Catholic theology has consistently maintained that justification involves not merely a forensic declaration but a genuine interior transformation of the soul.",
        "The debate over justification between Catholics and Protestants, which has persisted for five centuries, remains among the most theologically consequential disputes in Christian history.",
    ]
    return f"""{intros[variation % len(intros)]} The Protestant Reformers, and Luther most influentially among them, argued that justification consisted solely in the imputation of Christ's righteousness to the sinner, who remained, in the famous phrase, simultaneously righteous and sinful—simul iustus et peccator. The Council of Trent rejected this formulation with considerable precision, insisting that justification involved not merely an external declaration but an interior renewal of the human person through the grace of the Holy Spirit.

This distinction is not trivial; it goes to the heart of what it means to say that a sinner is made righteous before God. The Catholic tradition, drawing upon a rich Augustinian inheritance that the Reformers shared in part, affirmed that sanctifying grace genuinely transforms the soul, elevating it to participation in the divine nature as described in the Second Letter of Peter. The justified person is not simply covered by an alien righteousness; he is genuinely made holy, though in a manner that remains dependent upon and never independent of Christ's merits, which are the meritorious cause of justification.

The Joint Declaration on the Doctrine of Justification, signed by the Lutheran World Federation and the Roman Catholic Church in 1999, represented a remarkable development in ecumenical dialogue. The two communions affirmed a common basic understanding of justification, while acknowledging remaining differences in emphasis and formulation. Whether this agreement was sufficient to remove the mutual condemnations of the sixteenth century remains contested among theologians on both sides. Some Catholic theologians argued that the Declaration represented a genuine convergence; others, that it obscured remaining differences beneath diplomatic language.

For the Catholic pastor and theologian, the doctrine of justification cannot be reduced to a purely academic question. It shapes the practice of the sacraments, particularly the sacrament of penance and reconciliation, through which the justified person who has fallen into mortal sin is restored to the state of grace. The medicinal understanding of penance—not merely as a legal satisfaction but as a means of healing and restoration—expresses the Catholic conviction that grace, rather than being merely imputed, penetrates and transforms the interior life of the believer.

The Thomistic tradition has developed a sophisticated metaphysics of habitual grace to account for this transformation. Habitual grace, as an accident inhering in the soul, elevates the human person to a participation in the divine life that is genuinely supernatural and that enables meritorious acts ordered toward eternal beatitude. Critics within the Catholic tradition, most notably representatives of the nouvelle théologie such as Henri de Lubac, have questioned whether this Baroque scholastic account adequately preserves the gratuity of the supernatural and the intrinsic human orientation toward God. These are live debates within contemporary Catholic theology."""


def essay_catholic_grace(variation: int) -> str:
    return """The question of grace and freedom is, without exaggeration, the most controverted theological question within the Catholic tradition itself, a controversy that the Church has wisely declined to resolve definitively, permitting the dispute between Thomists and Molinists to continue within the bounds of orthodoxy. This prudence is itself instructive: the mystery of how God's sovereign grace works efficaciously in human freedom without destroying that freedom is precisely that—a mystery, one that the intellect approaches with reverence rather than mastery.

Thomas Aquinas, working within an Aristotelian framework of causality, proposed that God moves the will from within, not as an external compulsion but as the primary cause that enables and actualizes the secondary cause of the human will itself. The analogy of motion is illuminating: as the hand moves the pen, so God moves the will, but in so doing does not replace the will's own movement but rather constitutes it. Divine causality and human causality operate on different levels; they are not competing forces but analogically related modes of action.

The Molinist alternative, developed by the Spanish Jesuit Luis de Molina in the sixteenth century, proposed the concept of middle knowledge—God's knowledge of what any possible free creature would freely do in any possible set of circumstances. God, knowing how the human will would respond to various forms of grace, arranges circumstances such that the human person freely chooses what God has ordained. This solution preserves libertarian freedom in a way that Thomist efficacious grace has been accused of compromising, but its critics argue that middle knowledge renders the efficacy of grace ultimately dependent on human cooperation, thereby undermining divine sovereignty.

The pastoral implications of this dispute are not negligible. The preacher who presents grace as a proposal awaiting human acceptance risks implying that the decisive factor in salvation is ultimately human, not divine. The preacher who presents grace as irresistible risks discouraging human responsibility. The tradition of Catholic preaching has generally navigated this tension by holding both the genuine offer of grace to all and the dependence of its efficacy upon divine provision, trusting that the homiletical tension reflects a theological reality that admits of no simple resolution.

Contemporary Catholic theology has also engaged with insights from personalist philosophy, particularly as mediated through the thought of Karol Wojtyla, who became John Paul II. The personalist account of grace emphasizes the interpersonal character of the divine-human relationship—grace as God's self-communication, to use Karl Rahner's formulation, and the human response as a free self-gift in return. This language of gift and response, of invitation and acceptance, captures something that the scholastic categories of efficient and formal causality risk obscuring, even as the scholastic framework remains indispensable for precision."""


def essay_catholic_ecclesiology(variation: int) -> str:
    return """Lumen Gentium, the Dogmatic Constitution on the Church promulgated by the Second Vatican Council in 1964, represents the most authoritative and comprehensive account of Catholic ecclesiology in the modern period. Its opening declaration—that Christ is the light of the nations, and that the Council therefore ardently desires to shed his light more brightly on all people—establishes from the outset that the Church exists not for itself but in service of the divine mission entrusted to it.

The Council's most significant ecclesiological contribution was its retrieval of the biblical image of the Church as the People of God, placed, in a deliberate reversal of the schema proposed by the Preparatory Commission, before the treatment of the hierarchical structure. This ordering was theologically significant. It asserted the fundamental dignity and baptismal vocation of all the faithful before proceeding to distinguish the ordained ministry as a mode of service within, not above, the priestly people.

The Conciliar formula that the Church of Christ subsists in the Roman Catholic Church, replacing the earlier and stronger identification of the two, opened space for a more differentiated account of ecclesial communion. Elements of sanctification and truth are acknowledged to exist outside the visible boundaries of the Catholic Church. Other Christian communities possess ecclesial character, even if not in the full sense in which the Catholic Church understands ecclesiality. This teaching has been a source of ongoing ecumenical dialogue and theological development.

The hierarchical dimension of Catholic ecclesiology is grounded in the theology of apostolic succession and the sacramentality of holy orders. Episcopal ordination transmits not merely a legal jurisdiction but a sacramental grace that configures the bishop to Christ the head and shepherd. The college of bishops, with and under the Bishop of Rome, exercises the fullness of episcopal authority. The definition of papal primacy and infallibility at the First Vatican Council must be read in conjunction with the Conciliar teaching on episcopal collegiality, though the precise relationship between the two remains a matter of ongoing theological development.

For the seminary student, this ecclesiology is not merely theoretical. It shapes the concrete practice of ministry: the celebration of the sacraments, the exercise of pastoral authority, the practice of ecumenism, and the engagement of the Church with the surrounding culture. A church that understands itself as the sacrament of universal salvation—to use the Conciliar language—must engage the world as a sign of what the world is called to become, not as a fortress defending itself against modernity."""


def essay_catholic_prayer(variation: int) -> str:
    return """The Catechism of the Catholic Church defines prayer as "the raising of one's mind and heart to God or the requesting of good things from God." This classic definition, drawn from John Damascene and transmitted through centuries of Catholic devotional theology, preserves both the contemplative and petitionary dimensions of prayer without reducing either to the other. It is a definition worth dwelling upon at the beginning of any serious theological treatment of prayer.

The liturgical prayer of the Church holds primacy of place in the Catholic understanding. The Liturgy of the Hours—the official daily prayer of the Church—sanctifies the entire day through the communal recitation of psalms, canticles, scripture readings, and intercessory prayers. The reform of the Hours following the Second Vatican Council was intended to restore its character as genuinely communal prayer accessible to the whole People of God, not merely to clergy and religious. Whether this intention has been realized in practice remains a matter of pastoral observation rather than theological principle.

The Mass, as the source and summit of Christian life, is also the paradigmatic prayer. The Eucharistic Prayer, culminating in the words of institution and the anamnesis, is the Church's great act of thanksgiving and memorial participation in the once-for-all sacrifice of Christ. Here the distinction between the prayer of the Church and private devotion becomes especially significant. The individual who participates in the Mass does not merely observe a liturgical rite; he is incorporated into the self-offering of Christ to the Father through the Spirit. The mystical body prays with and through its head.

Mental prayer and contemplation have occupied a central place in Catholic spirituality since the patristic period, and the great mystical writers of the tradition—John of the Cross, Teresa of Avila, Meister Eckhart, and more recently Thomas Merton—have charted the movements of the soul toward union with God. The Carmelite tradition in particular has developed a sophisticated phenomenology of contemplative experience, distinguishing the active and passive purifications through which the soul is led, the dark night of the senses and the darker night of the spirit, toward transforming union with the divine.

The rosary, devotion to the Sacred Heart, Eucharistic adoration, and the traditions of popular piety must be understood not as alternatives to the liturgy but as extensions of the liturgical spirit into the personal and communal life of the faithful. Their evaluation must be both theologically serious and pastorally sensitive, acknowledging genuine spiritual fruit while attending to the risks of externalism and magical thinking that popular devotion always faces."""


def essay_catholic_sin(variation: int) -> str:
    return """The theology of sin in the Catholic tradition has been shaped by a long and complex history of biblical interpretation, patristic synthesis, and scholastic precision, culminating in the systematic accounts provided by Thomas Aquinas in the Summa Theologiae and subsequently refined through the controversies of the Reformation, the moral theology of the Jesuit tradition, and the more recent personalist and phenomenological approaches of the twentieth century.

The Augustinian inheritance is decisive for the Catholic understanding of original sin. Augustine's account, developed against the Pelagian assertion of natural human goodness and the sufficiency of moral example to motivate good action, affirmed a transmission of both guilt and concupiscence from Adam to his posterity through natural generation. The Council of Trent affirmed this Augustinian framework, teaching that original sin is transmitted by propagation, not merely by imitation, and that baptism remits the guilt of original sin even as concupiscence remains as material for spiritual combat.

The distinction between mortal and venial sin, systematized in the scholastic tradition and codified in the Church's penitential discipline, reflects a nuanced anthropology that takes seriously both the gravity of sin against an infinite God and the gradations of human moral failure. A mortal sin, which involves grave matter, sufficient reflection, and full consent of the will, ruptures the relationship of charity with God and renders the soul incapable of meritorious acts ordered toward salvation apart from the sacrament of penance. Venial sin weakens but does not destroy the life of grace.

Contemporary moral theology, influenced by personalist philosophy and the renewed biblical scholarship of the twentieth century, has sought to relocate the theology of sin within a more relational framework. Sin is not primarily the violation of a legal code but the refusal of love—the self-enclosed assertion of the human person against the call to communion with God and neighbor. This approach, represented by theologians such as Bernard Häring and Servais Pinckaers, does not abandon the precision of the scholastic categories but situates them within a more dynamic account of the moral life as a journey toward the good.

The Church's penitential practice reflects this anthropology. The sacrament of penance and reconciliation is not a legal proceeding but a medicinal encounter with the healing grace of Christ. The confessor acts as physician as well as judge. The penances assigned are not legal penalties satisfying divine justice in a mathematical sense but medicinal prescriptions ordered toward the healing of the wounds sin has left in the soul."""


# Wesleyan / Pastoral style essays

def essay_wesleyan_justification(variation: int) -> str:
    intros = [
        "I remember the first time I truly understood what it meant to be justified before God.",
        "Justification is not a complicated doctrine if you have ever known the weight of guilt.",
        "There is a moment in every serious Christian's life when the question of justification becomes personal, not academic.",
    ]
    return f"""{intros[variation % len(intros)]} For John Wesley, justification meant pardon—the forgiveness of sins past. This simple definition carries enormous pastoral weight. Justification does not make you sinless; it makes you forgiven. And what a difference that makes.

Wesley was careful to distinguish justification from sanctification. He wanted to protect both. Justification is God's act of declaring the sinner forgiven on the basis of Christ's atoning work. Sanctification is God's ongoing work of making the believer actually holy. Both are necessary. Both are gifts. Neither can be collapsed into the other without losing something vital.

What does Wesley add to the Protestant account? He insists that faith, which is the instrument of justification, is itself a gift. Prevenient grace goes before us. Before we turn to God, God has already been at work, drawing us, convicting us, enabling us to respond. This means that even our faith is not something we manufacture. It is awakened by grace. We respond, yes—but the capacity to respond has been given.

Critics sometimes ask whether Wesley's emphasis on human response undermines grace. I think this gets it backwards. The Wesleyan tradition does not say that our response earns justification. It says that grace creates the conditions in which genuine response becomes possible. The invitation is real. The choice is real. And grace makes both possible.

In pastoral ministry, I have found that people struggling with guilt need to hear the word of pardon clearly. They do not need more conditions. They need to know that God forgives. The Wesleyan message is: come as you are. Prevenient grace has already found you. Justifying grace will receive you. And sanctifying grace will change you. This is the whole gospel, and it is good news worth proclaiming.

What about ongoing sin after justification? Wesley was honest here. The justified believer still sins. That is why confession and ongoing reliance on grace matter. The Christian life is not a one-time legal transaction. It is a relationship of daily dependence on the One who both pardons and transforms."""


def essay_wesleyan_grace(variation: int) -> str:
    return """What does grace look like? I mean really look like, in the actual lives of people you know? I have been in ministry long enough to have a few answers to that question. Grace looks like the woman in our congregation who left an abusive marriage and rebuilt her life with the patient support of people who believed she was worth more than she had been told. Grace looks like the man who could not stop drinking for fifteen years and then, in the space of a single month, found something shift deep inside him. He said later that he could not explain it. It felt like something had been given to him. That is prevenient grace. That is Wesley's language, and it fits.

The Wesleyan tradition insists that God's grace is both universal and particular. Universal, because it goes before every human being without exception—drawing, convicting, illuminating the conscience, awakening the capacity for response. Particular, because it meets each person in the specific contours of their life and need. This is not a contradiction. It is the character of a personal God dealing with personal creatures.

The concept of prevenient grace distinguishes the Wesleyan account from both Calvinist and Pelagian alternatives. Against Calvinism, Wesleyans insist that grace is offered genuinely to all, not merely to the elect. Against Pelagianism, they insist that the human capacity to respond is itself a gift of grace, not a natural endowment. We do not cooperate with grace out of our own resources. Grace creates the cooperation.

Entire sanctification—Wesley's most distinctive and most contested doctrine—is the claim that the love of God can so fill the believer's heart that the inclination to sin is overcome. Wesley did not claim that sanctified believers became sinless in the absolute sense. He acknowledged the ongoing possibility of mistakes and involuntary failures. But he believed that the root of sin—the self-centered orientation of the will away from God—could be genuinely healed in this life by the fullness of the Holy Spirit.

I will be honest: this doctrine makes me nervous and hopeful in equal measure. Nervous, because the history of holiness movements contains enough examples of pride masquerading as sanctification to give anyone pause. Hopeful, because the claim that love can actually win—that the heart can be genuinely transformed and not merely managed—is exactly the kind of news that weary pastors and struggling believers need to hear."""


def essay_wesleyan_ecclesiology(variation: int) -> str:
    return """When I think about the church, I think first about the people in it. I know that is not the most theological way to begin, but it is the most honest. Ecclesiology, if it stays in the textbooks, is just another exercise in abstraction. If it reaches the pew, it has to answer the question: what does it mean for this group of broken, hopeful, arguing, praying people to be the body of Christ together?

Wesley himself was surprisingly unsystematic about ecclesiology. He never separated from the Church of England, though his movement created structures—class meetings, bands, circuits—that had an ecclesial character of their own. The class meeting was a small group of believers who met weekly to ask each other the question: how is it with your soul? That question is more than a pastoral nicety. It is an ecclesiological statement. The church is the community where that kind of accountability and mutual care is practiced.

The Wesleyan tradition has generally been ecumenical in spirit. Wesley famously said that his method did not impose any particular opinions upon anyone, that methodism was not a sect or party but a way of being Christian. This openness can slide into indifferentism if it is not anchored in genuine theological conviction. But at its best, it reflects the Wesleyan conviction that the Holy Spirit is not confined to any single tradition and that Christian unity matters.

What makes a church genuinely Methodist in character? Not the name on the sign, certainly. It is more about the practices. The commitment to small group accountability. The emphasis on grace for all people. The expectation that transformation is possible. The attention to the poor—Wesley's ministry was overwhelmingly directed toward the working poor of eighteenth-century England. These practices shape a community into a particular kind of people.

The church I serve is not large. We do not have impressive facilities. But people come back. They come back because someone noticed when they were absent. They come back because the preaching expects something of them and also offers something to them. They come back because, in some way they might struggle to articulate, this community is trying to be the answer to the prayer that the kingdom would come. That is the Wesleyan ecclesial vision at ground level."""


def essay_wesleyan_prayer(variation: int) -> str:
    return """Have you ever prayed and felt nothing? I mean genuinely nothing—no sense of presence, no warmth, no conviction that anyone was listening? If you have been in ministry for any length of time, you have probably sat with someone who is experiencing exactly that, and you have had to find something true to say to them. What the Wesleyan tradition offers in that moment is worth examining carefully.

Wesley was a disciplined man of prayer. He rose at four in the morning. He prayed for two hours before breakfast. He kept a journal that is remarkable for its honesty about the life of prayer—including its dryness and difficulty. The image of Wesley as a constant experiencer of warm-hearted religion is not quite accurate. He had dry seasons. He doubted. He pressed on anyway, and he pressed on precisely because he believed that faithfulness in prayer was not dependent on felt experience.

The means of grace are central to the Wesleyan understanding of prayer. Wesley inherited from the Anglican tradition a high regard for the ordered practices of the Christian life—scripture reading, prayer, fasting, the Lord's Supper, Christian conversation—as channels through which God's grace typically flows. This is a crucial practical point: we do not wait to feel like praying before we pray. We pray because God has appointed prayer as a means of grace, and we trust that the grace is given even when the feeling is absent.

Corporate prayer matters enormously in the Wesleyan tradition. The class meeting was, among other things, a prayer meeting. The practice of praying for one another by name—naming specific needs, expecting specific answers, giving thanks for specific deliverances—is a form of relational accountability that shapes the character of the community. It is harder to be indifferent to a person whose burdens you have been carrying before God.

Intercessory prayer is perhaps the form of prayer that requires the most theological attention. When we ask God to do something that God might not otherwise do, are we changing God's mind? Classical Christian theology has generally answered no: God's will does not change. But this cannot mean that intercession is useless. The tradition has developed various accounts of how intercession functions within providence. The Wesleyan account tends to emphasize the relational character of the divine-human relationship and to resist the idea that providence is a closed system indifferent to human petition."""


def essay_wesleyan_sin(variation: int) -> str:
    return """My grandfather used to say that the problem with the world is easy to diagnose: people are selfish and they know better. He was not a theologian, but he had a theologian's instinct. The doctrine of sin, for all its philosophical complexity, comes down to something that most honest people recognize in themselves: we regularly choose ourselves over others and over God, and we know, at some level, that we are doing it.

Wesley inherited a robust doctrine of original sin from the Anglican tradition and from Augustine. He was not soft on sin. He wrote a treatise on original sin in response to John Taylor, who had argued that the biblical and traditional account of total corruption was an exaggeration. Wesley disagreed vigorously. The evidence of human history—wars, oppression, cruelty, the casual indifference to suffering that characterizes ordinary social life—testifies to something more than ignorance or poor socialization. Something is wrong at a deeper level.

But Wesley's account of sin is shaped by his account of grace in a way that prevents it from becoming merely condemning. Prevenient grace means that no human being is simply the prisoner of original sin. The Spirit of God is already at work in every conscience, drawing toward the good. This is why natural moral knowledge is possible, why people who have never heard the gospel sometimes act with remarkable goodness, and why the image of God has not been utterly destroyed even in those who have not responded to the gospel.

The distinction between outer sin—specific wrong acts—and the inner disposition that Wesley called the sin of pride or self-will is important for pastoral ministry. People can stop doing certain wrong things and still be fundamentally oriented toward themselves rather than God. Behavioral modification without interior renewal is the permanent temptation of moralistic religion. Wesley was aware of this danger. That is why he insisted that sanctification involved not merely the reformation of behavior but the purification of the heart's deepest motivation.

Working with people in crisis—addiction, broken relationships, patterns of behavior that seem impossible to change—I have come to appreciate the pastoral realism of the Wesleyan doctrine of sin. It does not minimize what is wrong. It does not pretend that willpower alone is sufficient. And it does not leave the person in despair, because the same tradition that diagnoses sin clearly also proclaims grace abundantly."""


# Lutheran / Systematic style essays

def essay_lutheran_justification(variation: int) -> str:
    intros = [
        "It is generally recognized in systematic theology that the doctrine of justification constitutes what Luther termed the articulus stantis et cadentis ecclesiae.",
        "The Lutheran confessional tradition, as articulated in the Augsburg Confession of 1530, presents justification in terms that require careful systematic analysis.",
        "A systematic treatment of justification must begin with the question of the divine-human relationship as it is understood within the Lutheran theological tradition.",
    ]
    return f"""{intros[variation % len(intros)]} The Augsburg Confession, Article IV, states that persons "are freely justified for Christ's sake, through faith, when they believe that they are received into favor, and that their sins are forgiven for Christ's sake, who, by His death, has made satisfaction for our sins." Several elements of this formulation deserve systematic attention.

First, the adverb "freely" (gratis) indicates that justification involves no human meritorious contribution. This is not a claim about the absence of human activity in general—faith itself is a human act—but about the absence of any act that would render the human person deserving of justification as a matter of strict justice. The forensic character of justification as a divine declaration rather than a moral transformation is implied here, though the Confessions do not develop the distinction with the precision of later Lutheran orthodoxy.

Second, the phrase "for Christ's sake" locates the ground of justification not in the human person but in the person and work of Jesus Christ. The doctrine of justification is thus dependent upon and inseparable from Christology. The soteriological import of the two natures, the active and passive obedience of Christ, and the theology of the atonement are all implicated in this brief phrase. Luther's theology of the cross—theologia crucis as opposed to theologia gloriae—provides the broader framework within which justification by faith must be understood.

Third, the instrument of justification is specified as faith. Lutheran theology distinguishes between the material and formal causes of justification. The material cause is Christ's righteousness; the formal cause is the imputation of that righteousness to the believer; the instrumental cause is faith as the means by which the sinner appropriates the promise. This causal analysis, borrowed from scholastic philosophy, was employed by Lutheran orthodox theologians of the seventeenth century to provide systematic precision to what Luther had expressed in more existential and homiletical terms.

It should be noted, however, that the Lutheran tradition has not been without internal tensions regarding justification. The Finnish school, associated with the work of Tuomo Mannermaa, has argued that Luther's understanding of justification involves a real participation in the divine nature—an ontological union with Christ—that the purely forensic account of later orthodoxy obscures. This interpretation remains contested within Lutheran scholarship, but it has the merit of drawing attention to the union with Christ that Luther consistently emphasized as the presupposition of the forensic imputation."""


def essay_lutheran_grace(variation: int) -> str:
    return """The Lutheran theological tradition's account of grace is, it should be observed, fundamentally shaped by the dialectic between law and gospel that constitutes perhaps the most distinctive feature of Lutheran theological method. The proper distinction between law and gospel, which Luther identified as requiring the highest art in theology and which C.F.W. Walther later systematized in his celebrated theses, is not merely a hermeneutical principle; it is the organizing structure of Lutheran soteriology, including its account of grace.

Law, in the Lutheran sense, is the divine demand that the human person fulfill the righteousness that God requires. It makes no provision for human weakness; it demands perfection. The law, properly preached, produces either despair in the honest person who recognizes his inability to fulfill it, or a false confidence in the person who suppresses this recognition. The theological use of the law—the usus theologicus or usus elenchticus—is to convict of sin, to shatter false confidence, and to drive the sinner to the gospel.

Grace, then, is the divine gift of what the law demands and cannot give. It is not merely divine assistance for human effort; it is the unilateral act of God that does for the sinner what the sinner cannot do for himself. The Lutheran tradition has been particularly insistent on the passive character of the justified person's reception of grace. The human person before God is, in Luther's phrase, pure passive—not an agent contributing to his own salvation but a recipient of a salvation that has been achieved for him and given to him.

This account of grace has practical implications for Lutheran preaching and pastoral care. The sermon that does not distinguish law and gospel risks two symmetrical errors: the moralistic sermon that reduces the gospel to ethical exhortation, and the antinomian sermon that proclaims grace without the law that makes grace intelligible. The proper alternation of law and gospel—preaching the law in its full severity and then, to the convicted sinner, proclaiming the unconditional promise of the gospel—is the structural principle of Lutheran homiletics.

The relationship between grace and the means of grace is also systematically important. Lutheran theology insists that grace is ordinarily conveyed through the external word—the preached gospel and the administered sacraments. This is a safeguard against both a spiritualism that bypasses the external means and a sacramentalism that reduces grace to a quasi-physical substance. The word is the decisive element; the sacraments are visible words that promise the same grace as the audible word, sealed and certified in water, bread, and wine."""


def essay_lutheran_ecclesiology(variation: int) -> str:
    return """The Augsburg Confession's definition of the church, found in Article VII, is notable for its concision and its consequential ambiguity: the church "is the assembly of all believers among whom the Gospel is preached in its purity and the holy sacraments are administered according to the Gospel." This definition identifies the church with the gathering of believers around the means of grace, rather than with any institutional structure, episcopal succession, or juridical organization.

It is worth observing what this definition includes and what it does not include. It includes the Gospel and the sacraments as constitutive marks of the church. It does not include episcopacy, apostolic succession, or any particular form of church governance. The Apology of the Augsburg Confession, written by Philip Melanchthon in response to the Confutation, makes explicit that the Lutherans were willing to accept episcopacy provided that bishops did not require conditions for ordination that contradicted the gospel. This conditional acceptance of episcopal polity indicates that the Lutheran tradition does not regard church governance as adiaphora in the sense of being theologically irrelevant, but neither does it regard any particular polity as divinely mandated.

The distinction between the visible and invisible church, which Lutheran theology inherits from Augustine and shares with the Reformed tradition, introduces complexity into the Augustinian definition. The assembly of believers is not identical with the empirically observable gathering of those who profess faith. The true church—the communio sanctorum, the communion of saints—is known to God alone and encompasses all those in whom genuine faith is present. The visible church, the societas externa, includes both genuine believers and those who merely profess faith externally.

This distinction has significant practical implications. It means that the marks of the church—word and sacrament—do not guarantee the presence of genuine faith in every member of the visible assembly, but they do guarantee that the gospel is available. The church as institution is the means by which God ordinarily works to create and sustain faith; it is not the community of the guaranteed elect.

Contemporary Lutheran ecclesiology has engaged extensively with ecumenical dialogue, particularly with Roman Catholic and Anglican partners. The question of whether the Lutheran church retains genuine apostolicity despite the break in episcopal succession at the Reformation is a central point of ecumenical negotiation. Lutheran responses have generally argued that apostolicity is fundamentally a matter of the apostolic gospel rather than of episcopal lineage, though Lutheran churches in some contexts have moved toward full communion with episcopal bodies as a matter of ecumenical good faith."""


def essay_lutheran_prayer(variation: int) -> str:
    return """The theology of prayer within the Lutheran tradition has been, it must be acknowledged, less systematically developed than other loci of Lutheran dogmatics. This relative neglect may be attributed to several factors: the Reformation's primary concern with the objective grounds of salvation, the polemic against the ex opere operato understanding of prayer as a meritorious act, and the practical emphasis on the preached word as the normative means of grace. Nevertheless, a coherent Lutheran theology of prayer can be reconstructed from the Catechisms, Luther's sermons, and the broader confessional tradition.

Luther's exposition of the Lord's Prayer in both the Small and Large Catechisms represents the most sustained Lutheran treatment of prayer. The Small Catechism's exposition proceeds petition by petition, providing for each a simple explanation suitable for household instruction. The Large Catechism offers a more extended treatment that rewards close reading. Luther's approach is notable for its emphasis on prayer as a commanded duty rather than an optional spiritual exercise. We pray because God commands it; the command implies the promise of a hearing; the promise grounds the confidence with which prayer is offered.

The distinction between what might be called the objective and subjective dimensions of prayer is systematically important. Objectively, prayer is addressed to God on the basis of Christ's mediation, through the promises of the word. The validity of prayer does not depend upon the intensity of feeling or the degree of certainty experienced by the one praying. Subjectively, Lutheran theology recognizes the importance of genuine address—the heart actually turned toward God, not merely words being recited—while insisting that subjective states do not constitute the ground of prayer's efficacy.

The intercession of the saints presents a significant point of theological differentiation. The Lutheran tradition, following the critique of medieval practice, rejects the invocation of saints as mediators between the believer and God. Christ alone is the mediator of the new covenant; prayer is addressed to God through Christ, not through saints who are asked to intercede. This rejection does not entail that the saints pray not, or that their prayers are of no account, but that the living believer has no warrant to address prayer to them or to rely upon their intercession.

The theology of unanswered prayer presents pastoral challenges that systematic theology must address honestly. Lutheran pastoral theology has generally resisted the notion that unanswered prayer reflects insufficient faith on the part of the petitioner. The examples of Jesus himself praying in Gethsemane and of Paul's unanswered prayer for the thorn in the flesh suggest that the relationship between prayer and divine response is more complex than simple correspondence."""


def essay_lutheran_sin(variation: int) -> str:
    return """The Lutheran confessional tradition's treatment of original sin, found in Articles I and II of the Augsburg Confession and developed at length in the Apology, represents a careful attempt to maintain the full Augustinian account of sin's corruption while avoiding the deterministic implications that critics of the Reformed tradition have sometimes attributed to Calvinist doctrines of divine sovereignty.

Augsburg Confession Article II defines original sin as follows: persons are "born with sin, that is, without the fear of God, without trust in God, and with concupiscence." Several features of this definition deserve systematic attention. First, original sin is described privatively—as the absence of fear of God and trust in God. The human person, as created, was designed for a relationship of dependence, trust, and reverence before God. Original sin is the catastrophic disruption of this designed relationship. The positive good has been lost; what remains is its absence.

Second, the positive element of concupiscence is added. Concupiscence, in the Lutheran usage, refers not merely to sexual desire but to the disordered self-love that characterizes the fallen human will—what Luther called the will curved in upon itself, incurvatus in se. This positive disorder compounds the privative loss of genuine God-orientation. The fallen person is not merely indifferent to God; he is actively oriented away from God and toward himself.

The Augsburg Confession describes the consequences of original sin as rendering persons "unable by nature to have true fear of God or true faith in God." This is a strong statement of the bondage of the will, consistent with Luther's treatise On the Bondage of the Will against Erasmus. The natural person cannot, by his own powers, orient himself genuinely toward God. This is the theological anthropology that underlies the entire Lutheran account of salvation by grace through faith.

The Lutheran tradition has engaged with the question of inherited guilt with some care. The Apology of the Augsburg Confession explicitly affirms that original sin is a true sin, not merely a penalty or a disability, and that it makes persons liable to eternal condemnation. This is directed against those who would reduce original sin to a natural weakness that does not involve genuine guilt before God. The confessional insistence on guilt as well as corruption is significant for the theology of baptism: baptism is necessary not merely because it confers moral assistance but because it addresses genuine guilt through the forgiveness of sins."""


# Baptist / Narrative style essays

def essay_baptist_justification(variation: int) -> str:
    intros = [
        "My grandmother could not read. She never finished school. But she understood justification better than most seminary students I have met.",
        "There is a story that changed my understanding of justification completely.",
        "I grew up hearing about justification at the kitchen table, before I ever heard the word in a theology class.",
    ]
    return f"""{intros[variation % len(intros)]} She used to say: God took what Jesus did and put it on my account. Simple as that. You know what? That is a better definition than most systematic theologies produce.

Justification means God declares you righteous. Not makes you righteous first. Declares it. The declaration comes before the transformation. This sequence is everything. If you get it backwards—if you think you have to become righteous before God will declare you righteous—then you are on a treadmill that never stops. You will never be good enough. You will never have prayed enough, obeyed enough, believed enough.

But if justification is a declaration based on what Jesus did—his perfect obedience, his substitutionary death, his righteousness put on your account—then the pressure is off. Not because obedience stops mattering, but because obedience becomes a response to what has already been done, not an attempt to earn what has not yet been given.

Baptists have sometimes been accused of cheap grace. And it is true that Baptist preaching at its worst can slide into a kind of decisionism where the moment of conversion is everything and the ongoing moral life is an afterthought. But at its best, Baptist theology has understood that justification liberates. It frees the believer from the anxious project of self-justification. And that freedom is the foundation of a life of genuine obedience—not performed obedience for an audience of God, but the natural outflow of a heart that has been relieved of a burden it could not bear.

Paul says in Romans 5 that we have peace with God through our Lord Jesus Christ. Peace. Not an armistice. Not a temporary ceasefire. Peace. The hostility is over. The verdict has been rendered. It came back: not guilty. Better than not guilty, actually—declared righteous, on the basis of another's record. My grandmother understood this. I hope I do too."""


def essay_baptist_grace(variation: int) -> str:
    return """I want to tell you about a man named Marcus, though that is not his real name. Marcus spent eleven years in prison. He came to our church three months after his release, brought by his cousin who had been attending for years. He sat in the back and did not say much for several weeks. One Sunday after the service he found me and said: is this place for people like me?

I told him: this place is for people exactly like you. And then I tried to explain what I meant. Grace means that God's favor does not depend on your record. Marcus had a record. He also had the sense, which honest people often have, that the record matters—that what you have done follows you and shapes what you deserve. Grace says: yes, the record matters. And then grace does something astonishing. It says that Jesus took your record and gave you his.

This is what Baptists call the free grace of God. It is free not because it costs nothing—it cost the death of the Son of God—but because it costs you nothing. You do not purchase it. You do not earn it. You receive it. You trust the One who offers it. That is all.

Now, there are debates about how grace works—whether it is resistible, whether it is offered universally, whether some people are chosen before the foundation of the world. Baptists have not been uniform on these questions. Some Baptist confessions are thoroughly Calvinist; others are thoroughly Arminian; many sit somewhere in between, more interested in the preaching of the gospel than in resolving the metaphysics. I respect the theological curiosity that wants to work these questions out. But at three in the morning, when someone is sitting in the darkness wondering whether God could possibly accept them, the debates take a back seat.

What I told Marcus is what I believe: God's grace is bigger than your history. Come and see if it is true. He stayed. And he found out that it was."""


def essay_baptist_ecclesiology(variation: int) -> str:
    return """Roger Williams founded the first Baptist church in America in Providence, Rhode Island, in 1638. He had been banished from the Massachusetts Bay Colony for insisting that the state had no authority over the soul's religious life. This origin story matters. Baptist ecclesiology is, from the beginning, an ecclesiology of conscience and voluntary commitment.

The gathered church is the Baptist distinctive. The church is not the whole community of people born in a parish. It is not the national church. It is the company of regenerate believers who have made a conscious, free commitment to follow Christ and to covenant together for worship, mutual accountability, and mission. This is why believer's baptism, administered upon personal confession of faith, is non-negotiable for Baptists. Baptism is the public sign of a personal, voluntary entry into the covenant community.

Local church autonomy is another Baptist distinctive. Each congregation is directly accountable to Christ as its head. No bishop, synod, or denominational body has authority over the local church's internal life. Baptist associations and conventions exist for cooperation in mission, not governance. This can produce a wild diversity of practice and, sometimes, an unhealthy independence that refuses any accountability beyond the local congregation. But the principle behind it is sound: the Spirit of Christ guides each gathered community, and no human institution can substitute for that direct relationship.

The separation of church and state is the political implication of this ecclesiology. Williams argued, and Baptists have consistently held, that genuine faith cannot be coerced. The sword can compel outward conformity; it cannot produce genuine belief. Therefore the state has no business trying to enforce religious observance, and the church has no business seeking state power to advance its agenda. This is not secularism. It is a theological commitment to the voluntary character of genuine faith.

The Baptist church I serve operates by congregational polity. Every member has a voice. Major decisions are made by the whole congregation, not by a board or a pastor. This is slow and sometimes frustrating. Last year it took us three months to decide on new carpet for the fellowship hall. But there is something right about it. The people who make up this community are the ones who should direct it. They are not consumers of religious services. They are the church."""


def essay_baptist_prayer(variation: int) -> str:
    return """The best prayer I ever heard was about thirty seconds long. It was offered by a man named Earl, who was dying of cancer, at our midweek prayer meeting. He said: Lord, I am scared and I am tired and I do not understand this, but I trust you. And then he sat down. There was a long silence. And then someone else started crying. And then we prayed together for a while, nobody saying very much, just being there. That meeting changed something in how I understood prayer.

Prayer, in the Baptist tradition, is direct and personal. There is no required liturgical form, no set of intermediaries, no need for priestly mediation. The believer comes to God directly, through Jesus Christ, on the basis of the promise that those who ask will receive. This directness is both the strength and the risk of free-form prayer. The strength is authenticity—the prayer that emerges from actual need and actual trust, not from the repetition of someone else's words. The risk is shallowness—the prayer that degenerates into cliché, the prayer that says all the right religious words without actually engaging with God.

Baptist prayer meetings have historically been significant. In the revivals of the eighteenth and nineteenth centuries, protracted prayer meetings were the environments in which something happened—where individuals were convicted of sin, where communities were transformed, where missionaries were called and sent. This history creates a danger of nostalgia. We are tempted to try to recreate the form of those prayer meetings without attending to the substance that made them what they were. You cannot manufacture a revival by adding more prayer meetings to the calendar.

What you can do is be honest. Earl was honest. He was scared. He said so. That honesty opened a space in which God's presence was more palpable than in ten polished pastoral prayers I have offered on Sunday mornings. The tradition of Baptist prayer at its best is the tradition of people bringing their actual lives—in all their fear and confusion and gratitude and longing—into the presence of God and trusting that what happens there is real.

The Lord's Prayer is the model that Jesus provided. Even free-church Baptists, who are suspicious of rote recitation, would do well to spend more time with this prayer—not reciting it but inhabiting it, letting its movement from adoration to petition to trust shape the structure of their own prayer life."""


def essay_baptist_sin(variation: int) -> str:
    return """I have a confession to make. When I first started ministry, I preached very little about sin. I had grown up in a church where sin was a hammer used to beat people into compliance, and I had seen what that did to people's souls. So I overcorrected. I preached grace, grace, grace. I preached hope. I preached the love of God. And I watched people sit politely and leave the same way they came.

After a few years of this, I started to understand something. Grace only makes sense against a background of need. The love of God only lands when you know what it is saving you from. You cannot preach the solution to a problem you have been too polite to name. So I started preaching about sin again—carefully, not as a weapon, but as a diagnosis.

Baptist theology holds to a strong doctrine of human sinfulness. The Second London Baptist Confession of 1689, which reflects the Calvinist commitments of many early Baptists, follows the Westminster Confession in affirming original sin, total depravity, and the bondage of the will. Not all Baptists have held these particular formulations—General Baptists in the Arminian tradition have emphasized the freedom that prevenient grace restores—but all serious Baptist theology has taken human sinfulness seriously.

What does sin actually look like in the lives of real people? In my experience, it looks like this: it looks like the man who knows his drinking is destroying his family and keeps drinking anyway. It looks like the woman who has held a grudge for twenty years and has organized her entire social life around not forgiving the person who wronged her. It looks like the student who believes that if he just gets the right grades and the right job, he will be okay—who worships achievement because he is terrified of being ordinary. These are not merely bad habits. They are postures of the heart that have turned away from God toward substitutes that do not satisfy.

Sin, in the Baptist account, is not primarily about rule-breaking. It is about the orientation of the heart. Where is your trust? Where is your treasure? To whom do you ultimately belong? When those questions are answered with anything other than God, you are in the territory of sin. And the remedy is not self-improvement. It is repentance and faith—turning from the substitute and receiving the real thing."""


# AI-generated essays (uniform, balanced, hedged style)

AI_ESSAYS = [
    ("ai_001.txt", "justification", "The Doctrine of Justification in Christian Theology",
     """The doctrine of justification occupies a central place in Christian systematic theology, particularly within the Protestant tradition. At its core, justification addresses the question of how a sinful human being can stand righteous before a holy God. The Reformation debates of the sixteenth century brought this doctrine to the forefront of theological discourse, and it continues to generate significant scholarly discussion today.

Protestant theologians have generally understood justification in forensic terms. According to this view, God declares the sinner righteous on the basis of Christ's atoning work, with faith serving as the instrument through which the sinner receives this declaration. The imputation of Christ's righteousness to the believer is a key component of this account. It is important to note that this forensic declaration is understood to be distinct from, though inseparable from, the process of sanctification.

Roman Catholic theology, while agreeing that justification involves divine grace and the merits of Christ, has historically emphasized the transformative dimension of justification. According to Catholic teaching, justification involves not merely a forensic declaration but a genuine interior transformation of the soul through sanctifying grace. The Council of Trent articulated this position in response to the Protestant Reformers.

Ecumenical dialogue has produced some notable convergences between Protestant and Catholic perspectives on justification. The Joint Declaration on the Doctrine of Justification, signed in 1999, affirmed a common basic understanding while acknowledging remaining differences. Scholars continue to debate whether this agreement represents a genuine theological convergence or a diplomatic formulation that obscures underlying disagreements.

The practical implications of the doctrine of justification for Christian preaching and pastoral care are significant. Understanding how a person is justified before God shapes the way ministers address questions of guilt, assurance, and the motivation for ethical behavior. A forensic account tends to emphasize the objective basis of assurance in Christ's accomplished work, while a more transformative account may place greater emphasis on the evidence of grace in the believer's life.

Contemporary theological discussions have also engaged with questions raised by biblical scholars regarding the first-century Jewish context of Paul's letters. The New Perspective on Paul has proposed that Paul's concerns about justification were primarily sociological rather than individual, relating to the inclusion of Gentiles within the covenant community. Responses to this proposal have varied widely among New Testament scholars and systematic theologians."""),

    ("ai_002.txt", "grace", "Understanding Divine Grace in Christian Theology",
     """Divine grace is a foundational concept in Christian theology, referring to the unmerited favor and assistance that God extends to human beings. The doctrine of grace intersects with a wide range of theological topics including salvation, human freedom, predestination, and the nature of the divine-human relationship. Different theological traditions have developed distinctive accounts of grace that reflect their broader theological commitments.

The Augustinian tradition, which has profoundly influenced both Catholic and Protestant theology, emphasizes the priority and sovereignty of divine grace in salvation. Augustine developed his doctrine of grace in controversy with Pelagius, who argued that human beings possess the natural capacity to fulfill God's commands. Augustine responded that the fall had so damaged human nature that divine grace is necessary not merely for easier performance of God's will but for any genuine movement toward God at all.

The Reformed tradition, building on Augustine through Calvin and the later confessional documents, affirmed what has been called irresistible or efficacious grace. According to this view, God's grace, when extended to the elect, effectively achieves its purpose of bringing the sinner to faith and repentance. This understanding is closely connected to the Reformed doctrines of election and predestination.

Arminian theology, which emerged in the early seventeenth century as a response to Reformed soteriology, offered a different account of grace that preserved a greater role for human response. While affirming that grace is necessary and prior to human faith, Arminian theologians insisted that this grace could be genuinely resisted. The concept of prevenient grace, which restores the human capacity for response without determining that response, is central to this account.

The Catholic tradition has maintained a nuanced position on grace and freedom, permitting debate between Thomist and Molinist accounts while affirming both the necessity of grace and the reality of human freedom. The Thomist account emphasizes that divine causality operates on a different level than human causality, enabling both to be affirmed without competition. The Molinist account employs the concept of middle knowledge to explain how God achieves his purposes through the free choices of creatures.

Contemporary theology has engaged with these questions through the lens of process theology, open theism, and various philosophical frameworks. These developments have raised new questions about the compatibility of divine sovereignty and human freedom, and about the nature of divine knowledge and action in relation to the created world."""),

    ("ai_003.txt", "ecclesiology", "The Nature and Mission of the Church",
     """Ecclesiology, the theological study of the church, addresses questions about the nature, structure, and mission of the Christian community. These questions have been central to theological debate throughout Christian history, and they continue to be significant in contemporary ecumenical dialogue and practical ministry.

The New Testament presents a variety of images of the church that have informed theological reflection throughout Christian history. The church is described as the body of Christ, the people of God, the temple of the Holy Spirit, the bride of Christ, and the community of the new covenant, among other images. Each of these images captures a different dimension of the church's identity and calling. Systematic theologians have worked to integrate these diverse images into coherent accounts of ecclesial existence.

Historical Christian traditions have developed different understandings of the essential marks or characteristics of the true church. The Nicene Creed identifies the church as one, holy, catholic, and apostolic. Different theological traditions have interpreted these marks differently, particularly with regard to their institutional and spiritual dimensions. Protestant traditions have generally emphasized the preaching of the Word and the administration of the sacraments as the primary marks of the church, while Catholic and Orthodox traditions have placed greater emphasis on apostolic succession and episcopal continuity.

The relationship between the visible and invisible church has been a significant topic in ecclesiological reflection. Protestant theology in particular has drawn a distinction between the visible community of those who profess faith and participate in the church's worship and sacramental life, and the invisible community of those who possess genuine faith and are truly united to Christ. This distinction raises complex questions about the relationship between institutional membership and genuine Christian existence.

Questions of church governance and polity have also been theologically contested. Episcopal, presbyterian, and congregational forms of church governance each reflect different theological convictions about the nature of apostolic authority and the locus of decision-making within the church community. Ecumenical dialogue has sought to identify areas of convergence among these different polities while acknowledging remaining differences.

The mission of the church encompasses both proclamation of the gospel and engagement with human needs in the world. Different theological traditions have understood the relationship between these dimensions of mission differently, with some emphasizing the priority of evangelism and others emphasizing holistic engagement with social and political realities."""),

    ("ai_004.txt", "prayer", "The Theology and Practice of Christian Prayer",
     """Christian prayer is a multifaceted practice that encompasses adoration, confession, thanksgiving, and supplication. Theological reflection on prayer addresses questions about its nature, its efficacy, its proper forms, and its relationship to the divine-human interaction. These questions have occupied Christian thinkers from the patristic period to the present day.

The biblical witness to prayer is rich and varied. The Psalms provide the primary scriptural resource for understanding and practicing prayer within the Christian tradition, offering examples of praise, lament, confession, and intercession. The Lord's Prayer, as recorded in Matthew and Luke, provides the paradigmatic form of Christian prayer taught by Jesus himself. The New Testament epistles contain numerous references to prayer and provide theological reflection on its nature and purpose.

Theological traditions have understood the relationship between prayer and divine providence in different ways. If God's purposes are fixed and certain, what role does prayer play in the ordering of events? Classical Christian theology has generally resisted the conclusion that prayer changes God's mind or influences divine decisions in a simple causal sense. At the same time, the biblical witness to prayer as genuine address to a personal God who hears and responds has led theologians to seek accounts that preserve both the sovereignty of God and the genuine efficacy of prayer.

The distinction between liturgical and spontaneous prayer reflects different understandings of how the Spirit works in the corporate and individual life of the believer. Traditions that emphasize the importance of ordered liturgy argue that structured prayer trains the believer in proper attitudes and content, and that the church's accumulated wisdom in prayer is a resource rather than a constraint. Traditions that emphasize spontaneous prayer argue that genuine address to God must arise from the immediate movement of the Spirit in the heart of the believer.

Contemplative traditions within Christianity have developed sophisticated accounts of the stages of prayer life, from discursive meditation through various forms of affective and infused contemplation. Mystical theologians such as John of the Cross and Teresa of Avila have charted the movements of the soul toward union with God through prayer. These accounts have influenced not only Catholic spirituality but also Protestant spiritual theology in various periods.

The practice of intercessory prayer raises particular theological questions. When Christians pray for others, what is the relationship between these prayers and God's provision for those persons? Different theological accounts have understood intercession differently, with some emphasizing the participation of believers in the mediatorial work of Christ and others emphasizing the relational character of prayer within a community of faith."""),

    ("ai_005.txt", "sin", "The Doctrine of Sin in Christian Theology",
     """The doctrine of sin addresses the fundamental disruption in the relationship between human beings and God that characterizes human existence as Christians understand it. This doctrine intersects with anthropology, soteriology, and ethical reflection, providing the background against which the gospel of redemption is proclaimed and understood.

The biblical narrative locates the origin of sin in the disobedience of the first human beings, as recorded in the third chapter of Genesis. Theological interpretation of this narrative has generated significant discussion about the nature of the fall, the transmission of sin to subsequent generations, and the effects of sin on human nature. Different theological traditions have developed different accounts of these questions, though there is broad agreement that human beings as they now exist are in a state that requires divine redemption.

Augustine's account of original sin has been among the most influential in the history of Christian theology. Augustine argued that the sin of Adam resulted in both the guilt and the corruption of human nature being transmitted to subsequent generations. This transmission, in Augustine's account, occurs through natural generation and is connected to the disordering of human sexuality that resulted from the fall. Subsequent theologians have modified or challenged various elements of Augustine's account while generally maintaining some form of the doctrine of original sin.

The Reformers of the sixteenth century emphasized the comprehensive character of sin's corruption of human nature. The doctrine of total depravity, as formulated in Reformed theology, does not assert that human beings are as wicked as they could possibly be, but rather that every dimension of human existence—intellect, will, emotion—has been affected by sin. This comprehensive corruption means that unaided human beings cannot genuinely orient themselves toward God or perform acts that are meritorious in relation to salvation.

Contemporary theological anthropology has engaged with questions raised by evolutionary biology and psychology regarding the nature and origin of human sin. If human beings evolved from prior species, the historical Adam of traditional Christian theology requires reinterpretation. Various proposals have been offered, ranging from a symbolic reading of the Genesis narrative to the identification of a specific point in evolutionary history at which genuine human moral agency and its corruption emerged.

The relationship between personal sin and structural or social evil has also been a significant topic in twentieth-century theology. Liberation theology in particular has emphasized the ways in which sinful human choices become embedded in social, economic, and political structures that perpetuate injustice and oppression. This emphasis on structural sin has been both affirmed and challenged by other theological traditions, with debates centering on whether it adequately maintains individual moral responsibility."""),

    ("ai_006.txt", "justification", "Justification and Moral Transformation",
     """One of the persistent questions in the theology of justification concerns its relationship to moral transformation. If justification is understood primarily in forensic terms as a divine declaration of righteousness, how does it relate to the actual moral renewal of the believer? This question has been central to Protestant theology since the Reformation and continues to generate significant discussion.

The Lutheran tradition has generally maintained a clear distinction between justification and sanctification, understanding the former as the forensic declaration of righteousness and the latter as the ongoing process of moral renewal. This distinction is considered essential to the proper proclamation of the gospel. If justification and sanctification are conflated, the result is either works-righteousness (basing acceptance before God on moral achievement) or antinomianism (treating moral effort as irrelevant to the Christian life).

Reformed theology has also maintained the distinction between justification and sanctification while emphasizing their inseparability. The Westminster Confession of Faith, for example, affirms that those who are justified are also in due time sanctified. The same grace that brings about justification also brings about progressive moral transformation. This connection is typically grounded in the doctrine of union with Christ: the believer is united to Christ who is both the ground of justification and the source of sanctifying grace.

The Catholic tradition has, as noted, understood justification itself to include an element of moral transformation. The grace of justification, infused into the soul, genuinely transforms the believer and enables meritorious acts ordered toward eternal life. This does not mean that justification is contingent on moral achievement, but rather that the grace of justification is itself transformative in character, not merely declarative.

Contemporary systematic theology has returned to the theme of union with Christ as a way of understanding the relationship between justification and sanctification. Both Lutheran and Reformed theologians have argued that union with Christ is the broader soteriological framework within which justification and sanctification are properly understood. This approach has found some resonance in ecumenical dialogue, as it provides a way of affirming both the forensic and transformative dimensions of salvation without simply collapsing one into the other.

The practical implications of these theological discussions for preaching and pastoral ministry are significant. How a minister understands justification will shape the way he or she addresses questions of assurance, motivation for ethical behavior, and the relationship between grace and human effort. A robust theology of justification that maintains its distinction from sanctification while affirming their inseparability provides a framework for pastoral care that is neither moralistic nor antinomian."""),

    ("ai_007.txt", "grace", "Prevenient Grace and Human Response",
     """The concept of prevenient grace has occupied an important place in the theological traditions that seek to maintain both the necessity of divine grace for salvation and the genuine freedom of human response. The term refers to the grace that precedes and enables human turning toward God, making genuine faith and repentance possible without predetermining the human response.

The theological context for the doctrine of prevenient grace is the problem of how human freedom and divine grace can both be affirmed. If sin has so corrupted human nature that genuine movement toward God is impossible without grace, then any account of salvation that attributes a decisive role to human response faces the challenge of explaining how that response is possible. Prevenient grace provides one answer to this challenge: God's grace acts upon the human person prior to any human initiative, restoring the capacity for genuine response.

John Wesley's development of the doctrine of prevenient grace was particularly influential within the Arminian tradition. Wesley argued that God extends prevenient grace universally to all human beings, overcoming to some degree the effects of original sin and restoring the capacity for genuine response to the gospel. This grace is understood as a gift that goes before human merit and creates the conditions for a genuine, free response to God's offer of salvation.

The Reformed tradition has generally understood what might be called prevenient grace differently. In the Reformed account, the effectual calling of the elect involves a work of the Spirit that not only enables but determines the human response. This is sometimes described as irresistible grace, though Reformed theologians typically prefer to say that efficacious grace accomplishes its purpose by renewing the will rather than overcoming it. The result is a genuine human response that is nonetheless certain in its outcome.

The practical implications of these different accounts of grace for evangelism and pastoral care deserve attention. If prevenient grace is understood as genuinely universal and not determining the response, then the evangelist can extend the gospel invitation to all persons with the confidence that God has prepared them to respond, while acknowledging that this response may or may not occur. If efficacious grace is understood as effectively determining the response of the elect, the evangelistic confidence is differently grounded but no less real.

These theological discussions also intersect with questions in philosophical theology about the nature of divine foreknowledge, middle knowledge, and the compatibility of divine sovereignty and human freedom. The metaphysical questions are often complex, and different theological traditions have generally been willing to acknowledge that the precise relationship between divine grace and human freedom involves genuine mystery that human reason cannot fully resolve."""),

    ("ai_008.txt", "ecclesiology", "Church and Mission in Contemporary Theology",
     """The relationship between the nature of the church and its mission in the world has been a central concern of twentieth and twenty-first century ecclesiology. Missiological reflection has prompted theologians to reconsider traditional accounts of the church's identity and to develop more dynamic understandings of the church's participation in the mission of God.

The concept of the missio Dei, or mission of God, has been influential in contemporary missiology and ecclesiology. According to this concept, mission is not primarily a human activity or an institutional program but the activity of God in the world, in which the church is invited to participate. This understanding shifts the focus from the church as the subject of mission to God as the subject of mission, with the church as the instrument or participant in God's missionary activity.

The relationship between the church's proclamation of the gospel and its engagement with social, economic, and political realities has been a persistent source of debate in contemporary missiology. Different theological traditions have understood this relationship differently. Some have emphasized the priority of evangelism as the proclamation of the gospel for the salvation of individual souls. Others have emphasized the inseparability of word and deed, arguing that genuine proclamation of the gospel necessarily involves engagement with the conditions that diminish human flourishing.

The growth of Christianity in the Global South has significantly shaped contemporary ecclesiological reflection. Churches in Africa, Asia, and Latin America have developed theological perspectives that draw on their own cultural contexts and that sometimes challenge assumptions embedded in Western ecclesiology. Questions about the relationship between the gospel and culture, the appropriate forms of worship and community life, and the meaning of concepts like salvation and community are being addressed in new ways by theologians from the Global South.

The emergence of new forms of church in the contemporary period, including house churches, fresh expressions, and various forms of networked and online communities, has raised questions about what is essential to genuine ecclesial existence. Theological reflection on these developments seeks to identify the elements that are constitutive of the church as such, distinguishing them from historically contingent forms that may appropriately vary across cultures and contexts.

The ecumenical movement has continued to generate theological reflection on the unity of the church and its relationship to the diversity of Christian traditions. Documents produced by ecumenical dialogues seek to identify areas of agreement and to develop theological frameworks that acknowledge remaining differences while advancing the cause of visible Christian unity."""),

    ("ai_009.txt", "prayer", "Intercessory Prayer and Divine Providence",
     """Intercessory prayer, the practice of praying on behalf of others, raises fundamental questions about the relationship between human petition and divine action. If God's knowledge and purposes are comprehensive and unchanging, what is the role of human intercession in bringing about outcomes in the world? This question has engaged Christian theologians across different traditions and continues to be a significant topic in philosophical theology and practical spiritual theology.

Classical Christian theology has generally maintained that God's purposes are not changed by human prayer, while also insisting that intercessory prayer is both commanded and efficacious. These two affirmations create a tension that theologians have sought to resolve in various ways. One approach suggests that God has ordained the prayers of his people as part of the means by which he accomplishes his purposes. In this account, prayer is not the cause of God's action in a simple sense, but it is a genuine secondary cause within the order of providence that God has established.

Open theism has offered a different account of intercessory prayer that preserves a more straightforward causal relationship between human petition and divine response. According to open theism, God's knowledge of the future is limited to what is knowable, which does not include the free choices of created agents. In this framework, genuine intercession can influence divine action in ways that are not fully compatible with the classical account of comprehensive divine foreknowledge and eternal decree.

The Thomistic tradition has developed a sophisticated account of how intercessory prayer functions within a framework that affirms comprehensive divine providence. Aquinas argued that prayer does not change the divine will but participates in the divinely ordained order by which God works through secondary causes. The intercessor does not move God to act differently than God would otherwise have acted; rather, God has ordained that certain goods be given in response to prayer. This account preserves both the comprehensive character of divine providence and the genuine efficacy of human petition.

Practical spiritual theology across different traditions has emphasized the importance of intercessory prayer for the life of the Christian community, regardless of the metaphysical questions about its precise relationship to divine providence. Prayer for one another creates bonds of solidarity and mutual care within the community. The discipline of intercession shapes the character of the one who prays, cultivating concern for others and dependence on God. The experience of answered prayer reinforces trust in God and gratitude.

Contemporary discussions of intercessory prayer have also engaged with questions raised by scientific understandings of causality and the natural world. If the natural world operates according to regular causal laws, how is it possible for prayer to influence outcomes in that world? Different theological responses range from the affirmation of miracles as genuine exceptions to natural regularities to accounts of divine action through quantum indeterminacy to models of prayer's efficacy in terms of its formation of the one who prays rather than any direct causal impact on external events."""),

    ("ai_010.txt", "sin", "Original Sin and Human Nature",
     """The doctrine of original sin addresses the fundamental condition of humanity as Christians understand it, affirming that the sinfulness that characterizes human existence is not merely a matter of bad choices or poor socialization but reflects a deep disruption in human nature itself. This doctrine has been formulated and debated across Christian history, with significant theological, anthropological, and practical implications.

Augustine's account of original sin remains the most influential in the history of Christian theology. Developed in controversy with Pelagius, who argued that human beings possess the natural capacity to fulfill God's requirements, Augustine insisted that the fall of Adam resulted in the transmission of both guilt and corruption to all subsequent human beings. This transmission, Augustine argued, occurs through natural generation and is connected to the disordering of the human will and its relationship to the body.

The Reformation brought renewed attention to the doctrine of original sin, with both Lutheran and Reformed theologians affirming a robust account of the corruption of human nature while differing in some respects from the medieval Catholic synthesis. The Formula of Concord, for example, distinguishes between human nature as God created it and original sin as an alien corruption that has infected that nature, against positions that would simply identify sin with human nature as such.

Contemporary theology has engaged with challenges to the doctrine of original sin arising from evolutionary biology and historical-critical biblical scholarship. If the Genesis narrative is not historical in a straightforward sense, and if human beings evolved from prior species, what is the status of the traditional doctrine? Various responses have been offered, ranging from a defense of a historical Adam to various forms of reinterpretation that seek to maintain the theological substance of the doctrine while accommodating scientific findings.

The relationship between original sin and social structures of evil has been a significant theme in twentieth-century theology. Reinhold Niebuhr's account of sin as pride and sensuality, developed in his Gifford Lectures on The Nature and Destiny of Man, provided resources for understanding both individual and collective forms of human sinfulness. Liberation theologians have emphasized the ways in which individual sin becomes embedded in social, economic, and political structures that perpetuate injustice.

The pastoral implications of the doctrine of original sin are significant. A clear account of the human condition provides the context within which the gospel of redemption can be properly understood and proclaimed. At the same time, pastoral wisdom requires sensitivity to the ways in which the doctrine can be misused to reinforce shame and self-condemnation in unhealthy ways. A balanced account affirms the reality of human sinfulness while pointing consistently toward the grace that addresses it."""),

    ("ai_011.txt", "grace", "Grace, Merit, and the Christian Life",
     """The relationship between grace and merit in the Christian life has been among the most contested topics in the theology of salvation. The question of whether human actions within the Christian life can be described as meritorious has significant implications for understanding the nature of divine-human cooperation, the basis of Christian hope, and the motivation for ethical action.

The Protestant Reformation was defined in significant measure by the rejection of merit as a category applicable to human actions in relation to salvation. Luther, Calvin, and other Reformers argued that the Catholic theology of merit, particularly as it applied to supererogatory works and the treasury of merit available through indulgences, had fundamentally distorted the gospel of grace by introducing a commercial framework into the divine-human relationship. The doctrine of justification by faith alone was intended to exclude any human meritorious contribution to the sinner's acceptance before God.

The Council of Trent affirmed a doctrine of merit in response to the Protestant critique, distinguishing between the merit of congruity and the merit of condignity. The Council taught that the justified person, acting in union with Christ and through the assistance of grace, can merit an increase of grace and eternal life. This merit, however, is always dependent upon and secondary to the prior and enabling grace of God. It is not, in the Catholic account, a claim to receive from God what is strictly owed, but a divinely ordained relationship in which human action within grace genuinely contributes to the movement toward eschatological fulfillment.

Reformed theology has developed the concept of reward as a way of affirming that God graciously responds to the obedience of his people without introducing the category of strict merit. The rewards that God promises to those who faithfully follow him are not owed to them as a matter of justice but are expressions of God's gracious disposition toward his covenant people. This account seeks to motivate ethical action without grounding it in a theology of merit.

The practical implications of these different accounts for Christian ethics and spiritual formation are significant. If human actions can contribute to final salvation in some meaningful sense, then the motivation for ethical behavior is different from an account in which salvation is entirely a matter of divine grace with human ethical action understood as a response to grace already received. These differences shape the practice of spiritual direction, the teaching of ethics, and the understanding of the Christian life as a whole.

Contemporary ecumenical dialogue has sought to find common ground on these questions. The agreement that all human good action is enabled by divine grace, and that grace always precedes and accompanies meritorious action, provides a basis for dialogue. Remaining differences concern whether the language of merit is theologically appropriate for describing human action within grace and what precisely is claimed when such language is used."""),

    ("ai_012.txt", "ecclesiology", "Baptism and Church Membership",
     """The theology of baptism is closely connected to questions of church membership and the nature of Christian initiation. Different theological traditions have understood baptism differently, with significant implications for the understanding of the church and the nature of saving faith.

The major fault line in Christian baptismal theology runs between those who practice infant baptism and those who practice believer's baptism. Paedobaptist traditions, which include Roman Catholic, Eastern Orthodox, Lutheran, Reformed, and Anglican churches, administer baptism to the infants of believing parents, understanding baptism as the sign and seal of covenant membership. Credobaptist traditions, including Baptists and many other free church communities, administer baptism only upon personal confession of faith, understanding it as the public sign of regeneration and personal commitment.

The theological arguments for infant baptism typically draw on the parallel between circumcision and baptism in Colossians 2, the covenant relationship between parents and children in the Old Testament and its continuation in the new covenant, and the examples of household baptisms in the Acts of the Apostles. The argument is that the children of believers are included within the covenant community and that baptism is appropriately administered to them as the sign of that inclusion, with personal faith expected as they grow.

The theological arguments for believer's baptism typically draw on the New Testament pattern of repentance, faith, and baptism as a response to the preached gospel, the understanding of baptism as the public confession of personal faith, and the believer's priesthood that makes each individual directly responsible for his or her own relationship with God. In this account, baptism administered to those who have not personally professed faith lacks the essential element that gives it its proper meaning.

The relationship between baptism and regeneration has also been contested. Some traditions understand baptism as the sacramental means through which regeneration is ordinarily effected. Others understand it as the outward sign of an inward regeneration that has already occurred. Still others understand baptism primarily in terms of public confession and entry into the covenant community, without strong causal claims about its relationship to regeneration.

These theological differences about baptism have practical implications for questions of church membership, the treatment of those baptized as infants who later make personal professions of faith, and the recognition of baptism across denominational lines in ecumenical contexts. Ecumenical dialogue on baptism has produced significant convergence, but meaningful differences remain that reflect deep convictions about the nature of faith, grace, and the church."""),

    ("ai_013.txt", "prayer", "Contemplative Prayer and Christian Mysticism",
     """Contemplative prayer and Christian mysticism represent a significant dimension of Christian spirituality that has developed across different traditions and historical periods. Theological reflection on contemplative experience raises fundamental questions about the nature of the divine-human relationship, the role of human effort in the spiritual life, and the possibility of genuine union with God in this life.

The mystical tradition within Christianity draws on a range of biblical resources, including the Psalms, the Song of Solomon, the Gospel of John, and the letters of Paul with their emphasis on union with Christ and the indwelling of the Spirit. Patristic theologians including Origen, Gregory of Nyssa, and Pseudo-Dionysius developed accounts of the soul's ascent toward God through stages of purification, illumination, and union. These early accounts established patterns of mystical theology that were developed through the medieval period.

The medieval period produced some of the most influential accounts of contemplative prayer in the Christian tradition. Figures such as Bernard of Clairvaux, Meister Eckhart, Jan van Ruysbroeck, the author of The Cloud of Unknowing, and Julian of Norwich developed sophisticated accounts of the soul's journey toward God that combined careful theological reasoning with accounts drawn from contemplative experience. The Rhineland mystics in particular developed apophatic approaches to God that emphasized the inadequacy of all conceptual representations of the divine.

The Carmelite tradition, represented by John of the Cross and Teresa of Avila in the sixteenth century, produced what many regard as the most systematic theological accounts of contemplative prayer in the Christian tradition. John's account of the dark night of the soul describes the purification through which the soul must pass in order to be prepared for union with God. Teresa's Interior Castle provides a map of the stages of prayer life from the beginning of mental prayer through the various mansions to the final goal of spiritual marriage.

Protestant theology has generally been more reserved about the mystical tradition than Catholic and Orthodox Christianity, though Protestant mysticism has existed in various forms, including the German mysticism represented by figures like Jacob Boehme and the Quaker tradition's emphasis on the inner light. The Wesleyan tradition's emphasis on entire sanctification has some structural parallels to Catholic accounts of the transforming union, though the theological frameworks differ significantly.

Contemporary interest in contemplative prayer has crossed traditional boundaries, with Christians from many different traditions drawing on the resources of the contemplative tradition. The centering prayer movement, associated with figures like Thomas Merton and Basil Pennington, has made contemplative approaches to prayer accessible to many Christians who would not identify with formal mystical theology. These developments have generated both enthusiasm and theological critique."""),

    ("ai_014.txt", "sin", "Sin, Repentance, and Restoration",
     """The theological relationship between sin, repentance, and restoration is central to the practical life of the Christian community. Understanding what sin is, how it is addressed through repentance, and how restoration to right relationship with God and the community occurs are matters of both theological significance and practical pastoral importance.

Repentance in the New Testament involves both a change of mind and a change of direction. The Greek term metanoia suggests a fundamental reorientation of the mind and will, not merely regret for past actions or a resolution to behave differently in the future. True repentance, in the Christian understanding, involves recognition of sin as sin—as an offense against God and a departure from the good for which human beings were created—and a genuine turning away from sin toward God.

Different Christian traditions have understood the relationship between repentance and forgiveness differently. In the Catholic tradition, the sacrament of penance provides the ordinary means by which the baptized person who has fallen into mortal sin is restored to the state of grace. The elements of contrition, confession, and satisfaction within the sacramental structure provide a framework for the process of reconciliation that is both personal and ecclesial. The absolution pronounced by the priest is understood to convey, ex opere operato, the forgiveness of God.

Protestant traditions have generally understood forgiveness as received through faith in the promises of the gospel, without requiring sacramental mediation in the technical sense. Confession of sin and assurance of forgiveness may occur in private prayer, in communal liturgy, or in pastoral conversation. The emphasis is on the direct accessibility of forgiveness through Christ's atoning work, appropriated by faith.

The social dimension of sin and repentance has received increased attention in contemporary theology. When sin takes corporate or structural forms, repentance and restoration cannot be understood solely in individual terms. Communities, institutions, and nations can engage in forms of corporate acknowledgment of wrongdoing and commitment to reparative action. The theology of truth and reconciliation, developed in response to situations of historical injustice, draws on Christian understandings of repentance, forgiveness, and restoration while attending to the social and political dimensions that individual models of repentance do not fully address.

The role of the Christian community in the process of repentance and restoration is also theologically significant. The community provides accountability through the practice of church discipline, encouragement through the proclamation of the gospel promise of forgiveness, and practical support for the person seeking to address the consequences of sin. This communal dimension of restoration reflects the corporate character of Christian identity and the mutual responsibility of members of the body of Christ."""),

    ("ai_015.txt", "justification", "Assurance of Salvation and the Doctrine of Justification",
     """The question of assurance of salvation has been a significant pastoral and theological concern throughout Christian history. How can the believer know that he or she is truly justified, truly a member of the community of salvation? The answer to this question is closely connected to the theological account of justification and the grounds on which assurance is appropriately based.

The Protestant Reformation brought the question of assurance to the center of theological discussion. The Reformers argued that the medieval Catholic system, with its emphasis on the ongoing cooperation of grace and human effort in the process of justification, made genuine assurance impossible. If the ultimate outcome of one's salvation depends in part on one's own perseverance and cooperation with grace, then the appropriate attitude is hope mingled with fear rather than confident assurance.

Luther's account of justification as a forensic declaration based on the imputation of Christ's righteousness provided a different basis for assurance. The believer's confidence before God is grounded not in his or her own spiritual progress but in the objective work of Christ and the divine declaration of righteousness. This objective ground makes assurance possible without making it dependent on the variable quality of one's spiritual experience or moral performance.

The Reformed tradition developed the doctrine of the perseverance of the saints as an additional ground of assurance. Those who are genuinely elect will persevere in faith to the end; genuine saving faith, as the gift of God and the work of the Spirit, cannot ultimately be lost. This doctrine provides strong grounds for assurance while raising questions about how the believer can know with confidence that his or her faith is genuine saving faith rather than a temporary or false profession.

Catholic theology has generally been more reserved about subjective certainty of one's own salvation, understanding such certainty as presumption in the absence of special revelation. The Council of Trent taught that no one can know with certainty of faith, which cannot be subject to error, that he has obtained God's grace. This does not mean that Catholics have no basis for hope or that they must live in constant anxiety, but it does mean that the grounds of assurance are differently understood than in the Protestant account.

Contemporary pastoral theology has engaged with the question of assurance in the context of widespread anxiety and spiritual insecurity among Christians. The tendency to base assurance on subjective spiritual experience creates vulnerability to fluctuating spiritual states. A theological account that grounds assurance primarily in the objective work of Christ and the promises of the gospel provides a more stable foundation, though it must also attend to the question of how the objective promise is appropriated by faith in the individual's experience."""),

    ("ai_016.txt", "ecclesiology", "Ecumenism and Christian Unity",
     """The ecumenical movement of the twentieth century represented a significant development in the history of Christian theology and practice. After centuries of division, Christian churches from different traditions began to engage in sustained theological dialogue aimed at identifying areas of convergence and developing frameworks for greater visible unity. The theological challenges and achievements of this movement continue to shape contemporary ecclesiology.

The World Council of Churches, founded in Amsterdam in 1948, provided an institutional framework for ecumenical dialogue among Protestant and Orthodox churches. The Second Vatican Council, which opened in 1962, marked a significant shift in Roman Catholic engagement with ecumenism, affirming the presence of elements of the church and means of sanctification outside the visible boundaries of the Catholic Church. The decades following the Council saw extensive bilateral and multilateral dialogues between the Catholic Church and various Protestant and Anglican partners.

Theological convergence on significant doctrinal questions has been achieved in several areas. The Lima Document on Baptism, Eucharist and Ministry, produced by the Faith and Order Commission of the World Council of Churches in 1982, represents one of the most significant multilateral ecumenical texts of the twentieth century. It articulated areas of convergence on the theology of baptism, the Eucharist, and ordained ministry, while acknowledging remaining differences that require further theological work.

The question of visible unity and what form it should take remains contested among ecumenical theologians. Some advocate for organic union of divided churches, understanding visible unity as requiring a single institutional structure. Others propose a model of conciliar fellowship in which churches maintain their distinct identities while entering into formal relationships of mutual recognition and cooperation. Still others emphasize the spiritual unity that already exists among all true believers and are skeptical of institutional expressions of unity as such.

The reception of ecumenical agreements by local churches and congregations has been uneven. Theological agreements reached in formal dialogue do not automatically translate into changed practice or changed attitudes at the congregational level. The gap between theological convergence at the level of expert dialogue and the lived reality of Christian division at the local level remains a significant challenge for the ecumenical movement.

Contemporary ecumenism faces new challenges arising from the diversification of Christianity in the Global South and the emergence of new Christian movements that do not fit neatly into the categories that shaped the ecumenical movement of the twentieth century. Pentecostal and charismatic Christianity, which represents a significant proportion of global Christianity, has engaged with the ecumenical movement in complex and sometimes ambivalent ways. New forms of Christian community that cross traditional denominational boundaries are emerging in ways that both advance and complicate the ecumenical goal."""),

    ("ai_017.txt", "prayer", "Liturgical Prayer and Corporate Worship",
     """Liturgical prayer, the structured corporate prayer of the assembled Christian community, represents a dimension of Christian worship that has been practiced in various forms across all major Christian traditions. Theological reflection on liturgical prayer addresses questions about the nature of corporate worship, the role of form and structure in prayer, and the relationship between the church's corporate prayer and the divine-human encounter.

The history of Christian liturgy reveals both remarkable continuity and significant development. The earliest Christian communities gathered for worship that included the reading and proclamation of scripture, prayers of various kinds, and celebration of the Lord's Supper. By the fourth century, as Christianity became the religion of the Roman Empire, more elaborate liturgical forms developed that were shaped by both the Jewish heritage of Christianity and the cultural forms of the Greco-Roman world.

The major Christian traditions have developed distinctive liturgical forms that reflect their theological commitments. The Byzantine liturgy of the Eastern Orthodox Church, with its elaborate ceremonial and emphasis on the heavenly liturgy in which the earthly assembly participates, reflects a theology of worship as participation in the eternal worship of heaven. The Roman Rite, as reformed by the Second Vatican Council, seeks to make the liturgy more accessible to the congregation while maintaining the continuity of the Roman tradition. Lutheran worship, in its classic forms, maintains significant continuity with the Catholic liturgical heritage while centering the service on the proclamation of the Word.

Reformed and free church traditions have generally placed greater emphasis on the simplicity of corporate prayer, understanding elaborate ceremonial as a potential distraction from the encounter with God through Word and Spirit. The regulative principle of worship, associated with the Reformed tradition, holds that corporate worship should include only those elements explicitly commanded or warranted by scripture. This principle has led to significant differences in the practice of corporate prayer between Reformed and other Protestant traditions.

The renewal of interest in liturgical worship among evangelical and free church Christians in recent decades has been significant. Many congregations that historically emphasized simplicity and spontaneity in worship have recovered elements of structured liturgy, including the use of historic collects and prayers, the recovery of the church calendar, and greater attention to the sacramental dimensions of worship. This liturgical renewal has been accompanied by theological reflection on the formative character of corporate prayer and worship.

The relationship between the liturgical prayer of the gathered congregation and the prayer life of individual Christians has been a recurring theme in spiritual theology. Corporate worship is understood in most traditions as both expressive of and formative for the faith of individual believers. The patterns, rhythms, and content of corporate prayer shape the dispositions, expectations, and practices of individual Christians in ways that purely private prayer cannot."""),

    ("ai_018.txt", "sin", "The Theology of Forgiveness",
     """Forgiveness occupies a central place in Christian theology and practice. The divine forgiveness of human sin is foundational to the gospel of salvation, while the practice of interpersonal forgiveness is a central requirement of the Christian ethical life. Theological reflection on forgiveness addresses questions about its nature, its conditions, its relationship to justice, and its psychological and social dimensions.

Divine forgiveness, as understood in Christian theology, is not a simple remission of penalty that treats sin as though it had never occurred. Christian theology has generally insisted that forgiveness is consistent with divine justice, that God does not simply overlook sin but addresses it through the atoning work of Christ. The penal substitutionary account of atonement, associated with Anselm's satisfaction theory and its Protestant developments, understands Christ's death as the means by which divine justice is satisfied so that forgiveness can be extended to sinners without compromising the divine righteousness.

Alternative accounts of the atonement, including moral influence theories, Christus Victor approaches, and various forms of participatory or ontological accounts, understand the relationship between atonement and forgiveness differently. These approaches have generally sought to avoid what they regard as the juridical and commercial character of satisfaction theories while maintaining the connection between Christ's work and the divine forgiveness of sin.

Interpersonal forgiveness is a requirement of the Christian life that the New Testament presents in strong terms. The Lord's Prayer connects the forgiveness of the one who prays with his or her practice of forgiving others. The parable of the unforgiving servant in Matthew 18 presents unforgiveness as incompatible with the receipt of divine forgiveness. Colossians 3 commands believers to forgive each other as the Lord has forgiven them.

The theology of forgiveness has been developed in dialogue with psychological accounts of forgiveness in recent decades. Psychologists have produced significant research on the nature of forgiveness, its relationship to resentment and anger, its conditions and stages, and its psychological benefits for both the person who forgives and the person forgiven. Christian theologians have engaged with this research in various ways, affirming some insights while questioning others, particularly regarding the relationship between forgiveness and reconciliation.

The social and political dimensions of forgiveness have received significant attention in the context of transitional justice following situations of historical injustice. The Truth and Reconciliation Commission in South Africa drew explicitly on Christian theological resources in developing its approach to addressing the injustices of the apartheid era. Theological reflection on these experiences has both drawn on and contributed to the broader theology of forgiveness, attending to the distinctive challenges that arise when forgiveness is sought in political and social contexts."""),

    ("ai_019.txt", "grace", "Grace and Human Dignity",
     """The relationship between the doctrine of divine grace and Christian understandings of human dignity is a significant topic in theological anthropology and ethics. How the Christian tradition understands grace—its necessity, its scope, its effects—shapes the understanding of what it means to be human and what claims human beings can properly make on one another.

The imago Dei, the doctrine that human beings are created in the image and likeness of God, provides the foundational basis for Christian affirmations of human dignity. Theological traditions have understood the content of this image differently, with some emphasizing structural characteristics such as rationality and will, others emphasizing relational characteristics such as the capacity for relationship with God and with other persons, and still others emphasizing the vocation of stewardship and dominion. Despite these differences, the doctrine consistently grounds human dignity in the divine creative act rather than in human achievement or social recognition.

The fall and original sin complicate the account of human dignity without eliminating it. Christian theology has generally maintained that the image of God in human beings has been damaged but not destroyed by sin. This means that human dignity remains even in the most degraded human circumstances, and that the obligation to respect the dignity of other persons does not depend on their moral performance or social status.

Divine grace, understood as the unmerited favor of God extended to sinful human beings, provides a distinctive theological grounding for human dignity. The assertion that God loves human beings while they are yet sinners, and that the Son of God became incarnate, suffered, and died for their redemption, communicates an estimate of human worth that is not dependent on human merit. The dignity of the human being is seen, in this account, in the value that God places on human beings as evidenced by the cost of their redemption.

The doctrine of prevenient grace, particularly in its Wesleyan formulation, has implications for Christian engagement with all human beings. If God's grace is genuinely universal, working in every human conscience and drawing all persons toward the good, then every human being is the object of divine concern and care. This has implications for how Christians relate to those outside the visible community of the church, including people of other faiths and no faith.

The relationship between grace and human dignity has practical implications for Christian ethics, particularly in relation to the care of the vulnerable—the poor, the sick, the prisoner, the immigrant, the person with disability. A theology of grace that affirms the unmerited character of divine favor provides resources for extending care and respect beyond the boundaries of merit, achievement, and social utility. The practices of Christian community life that express this theology of grace can form persons who extend to others the unconditional regard that they themselves have received from God."""),

    ("ai_020.txt", "ecclesiology", "The Church as Community of Practice",
     """The understanding of the church as a community of practice has received significant attention in contemporary ecclesiology, drawing on sociological and philosophical accounts of how communities form persons through shared practices and how practices embody and transmit the convictions and commitments of a community. This perspective offers resources for understanding how the church shapes the character and identity of its members and how it sustains its distinctive way of life across time.

The concept of practice, as developed by philosophers such as Alasdair MacIntyre, refers to coherent, cooperative activities through which goods internal to the practice are realized and the virtues necessary to participate in it are developed. The church's constitutive practices—proclamation of the Word, celebration of the sacraments, prayer, care for the poor, and mutual accountability—are practices in this sense. Participating in them forms persons in distinctive ways, cultivating dispositions, habits, and skills that shape how those persons understand and engage with the world.

Baptism and the Eucharist are understood in most Christian traditions as constitutive practices of the church that both enact and form Christian identity. Baptism initiates the person into the community with its distinctive way of life, marking the transition from one identity to another through a performative act that is simultaneously personal and social. The regular celebration of the Eucharist forms the community through the repeated enactment of its central narrative of redemption and its practice of sharing, mutual recognition, and thanksgiving.

The practice of preaching and the reading of scripture functions formatively within the church community. The regular encounter with the biblical narrative, interpreted within the community's hermeneutical tradition, shapes the way community members understand themselves, their world, and their obligations. Communities that engage regularly with the whole biblical narrative develop a distinctive imaginative framework that mediates their encounter with other cultural narratives and claims.

The practice of care for the poor and the vulnerable has been understood across Christian traditions as an essential expression of Christian identity. The corporal works of mercy in the Catholic tradition, the diaconal ministry of Lutheran and Reformed churches, and the emphasis on social holiness in the Wesleyan tradition all reflect the conviction that care for those in need is not an optional addition to Christian community life but an essential practice through which the community expresses and forms its distinctive identity.

Contemporary ecclesiology has also attended to the practices of mutual accountability and discipline that have historically been part of Christian community life. The class meeting in the Wesleyan tradition, the practice of fraternal admonition in the Mennonite tradition, and various forms of small group accountability in contemporary evangelical communities represent attempts to maintain practices of mutual care and accountability that shape character and sustain commitment within the community."""),
]

# ── Cross-author ghostwriting cases ───────────────────────────────────────────
# Essay text is from a different author's style than the baseline author
# The baseline author is the accused author; the actual author is different

GHOSTWRITING_CASES = [
    {
        "filename": "ghost_001.txt",
        "baseline_author": "seminary_01",   # Reformed student's baseline used
        "actual_style": "catholic",         # but text is in Catholic style
        "topic": "justification",
        "text": essay_catholic_justification(0),
    },
    {
        "filename": "ghost_002.txt",
        "baseline_author": "seminary_02",
        "actual_style": "reformed",
        "topic": "grace",
        "text": essay_reformed_grace(0),
    },
    {
        "filename": "ghost_003.txt",
        "baseline_author": "seminary_03",
        "actual_style": "lutheran",
        "topic": "ecclesiology",
        "text": essay_lutheran_ecclesiology(0),
    },
    {
        "filename": "ghost_004.txt",
        "baseline_author": "seminary_04",
        "actual_style": "baptist",
        "topic": "prayer",
        "text": essay_baptist_prayer(0),
    },
    {
        "filename": "ghost_005.txt",
        "baseline_author": "seminary_05",
        "actual_style": "wesleyan",
        "topic": "sin",
        "text": essay_wesleyan_sin(0),
    },
]

# Map of student → essay generator functions per topic
ESSAY_FUNCS = {
    "seminary_01": {
        "justification": essay_reformed_justification,
        "grace":         essay_reformed_grace,
        "ecclesiology":  essay_reformed_ecclesiology,
        "prayer":        essay_reformed_prayer,
        "sin":           essay_reformed_sin,
    },
    "seminary_02": {
        "justification": essay_catholic_justification,
        "grace":         essay_catholic_grace,
        "ecclesiology":  essay_catholic_ecclesiology,
        "prayer":        essay_catholic_prayer,
        "sin":           essay_catholic_sin,
    },
    "seminary_03": {
        "justification": essay_wesleyan_justification,
        "grace":         essay_wesleyan_grace,
        "ecclesiology":  essay_wesleyan_ecclesiology,
        "prayer":        essay_wesleyan_prayer,
        "sin":           essay_wesleyan_sin,
    },
    "seminary_04": {
        "justification": essay_lutheran_justification,
        "grace":         essay_lutheran_grace,
        "ecclesiology":  essay_lutheran_ecclesiology,
        "prayer":        essay_lutheran_prayer,
        "sin":           essay_lutheran_sin,
    },
    "seminary_05": {
        "justification": essay_baptist_justification,
        "grace":         essay_baptist_grace,
        "ecclesiology":  essay_baptist_ecclesiology,
        "prayer":        essay_baptist_prayer,
        "sin":           essay_baptist_sin,
    },
}


def _word_count(text: str) -> int:
    return len(text.split())


def generate_corpus() -> None:
    """Generate all corpus files and update manifest.json."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing manifest
    with open(MANIFEST_PATH) as f:
        existing_manifest = json.load(f)

    new_entries = []

    # ── Generate student essays ──────────────────────────────────────────────
    for author_id, profile in STUDENTS.items():
        print(f"\nGenerating essays for {author_id} ({profile['tradition']})...")
        topic_list = list(TOPICS)

        for i, (topic_key, topic_prompt) in enumerate(topic_list):
            fn = f"{author_id}_{topic_key}.txt"
            is_baseline = i < 3   # first 3 topics are baseline
            variation = 0 if is_baseline else (i - 3)

            text = ESSAY_FUNCS[author_id][topic_key](variation)
            wc = _word_count(text)

            fpath = CORPUS_DIR / fn
            fpath.write_text(text, encoding="utf-8")
            print(f"  {'[baseline]' if is_baseline else '[scoring]'} {fn} ({wc} words)")

            new_entries.append({
                "filename": fn,
                "author_id": author_id,
                "label": "authentic",
                "prompt": topic_prompt,
                "word_count": wc,
                "is_baseline": is_baseline,
                "ai_provider": "none",
                "theological_tradition": profile["tradition"],
                "native_english": profile["native_english"],
                "notes": f"Synthetic {profile['style']}-style essay, variation {variation}",
            })

    # ── Generate AI essays ───────────────────────────────────────────────────
    print("\nGenerating AI-authored essays...")
    for fn, topic_key, prompt_text, text in AI_ESSAYS:
        wc = _word_count(text)
        fpath = CORPUS_DIR / fn
        fpath.write_text(text, encoding="utf-8")
        print(f"  [ai] {fn} ({wc} words)")

        new_entries.append({
            "filename": fn,
            "author_id": "ai_author",
            "label": "ai_generated",
            "prompt": prompt_text,
            "word_count": wc,
            "is_baseline": False,
            "ai_provider": "claude",
            "theological_tradition": None,
            "native_english": None,
            "notes": "AI-generated theological essay for validation corpus",
        })

    # ── Generate ghostwriting cases ──────────────────────────────────────────
    print("\nGenerating ghostwriting cases...")
    for case in GHOSTWRITING_CASES:
        fn = case["filename"]
        wc = _word_count(case["text"])
        fpath = CORPUS_DIR / fn
        fpath.write_text(case["text"], encoding="utf-8")
        print(f"  [ghostwritten] {fn} ({wc} words) — baseline: {case['baseline_author']}")

        new_entries.append({
            "filename": fn,
            "author_id": case["baseline_author"],   # attributed to baseline author
            "label": "ghostwritten",
            "prompt": f"The doctrine of {case['topic']} in Christian theology",
            "word_count": wc,
            "is_baseline": False,
            "ai_provider": "none",
            "theological_tradition": None,
            "native_english": None,
            "notes": f"Ghostwritten: actual style is {case['actual_style']}, submitted under {case['baseline_author']} baseline",
        })

    # ── Update manifest.json ─────────────────────────────────────────────────
    # Add new authors metadata
    existing_manifest.setdefault("authors", {})
    for author_id, profile in STUDENTS.items():
        existing_manifest["authors"][author_id] = {
            "theological_tradition": profile["tradition"],
            "native_english": profile["native_english"],
            "style": profile["style"],
        }
    existing_manifest["authors"]["ai_author"] = {
        "theological_tradition": None,
        "native_english": None,
        "style": "ai_generated",
    }

    # Append new entries
    existing_manifest["entries"].extend(new_entries)
    existing_manifest["description"] = (
        "Original authorship verification validation corpus — "
        "historical prose (Federalist Papers, Burke, Lincoln, Douglass) "
        "plus modern synthetic seminary essays"
    )

    with open(MANIFEST_PATH, "w") as f:
        json.dump(existing_manifest, f, indent=2)

    # Summary
    authentic = sum(1 for e in new_entries if e["label"] == "authentic")
    ai_gen    = sum(1 for e in new_entries if e["label"] == "ai_generated")
    ghosted   = sum(1 for e in new_entries if e["label"] == "ghostwritten")
    baseline  = sum(1 for e in new_entries if e.get("is_baseline"))
    scoring   = sum(1 for e in new_entries if not e.get("is_baseline") and e["label"] == "authentic")

    print(f"\n{'='*60}")
    print(f"CORPUS GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"Authentic essays:    {authentic} ({baseline} baseline, {scoring} scoring)")
    print(f"AI-generated essays: {ai_gen}")
    print(f"Ghostwritten essays: {ghosted}")
    print(f"Total new entries:   {len(new_entries)}")
    print(f"Manifest updated:    {MANIFEST_PATH}")


if __name__ == "__main__":
    generate_corpus()
