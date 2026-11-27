# ruff: noqa: E501  (long literals: abstracts and source records)
"""Fixed text for the document-parts test set: who "wrote" each paper, its
title, abstract, headings and sources.

The prose of every paper is the author's own (``validation/public_authors``);
everything here is the apparatus around it, written for this test set. The
students, teachers and institutions are invented. The cited books are real
works; the journal articles and web pages are invented, and their DOIs use
the 10.5555 example prefix so none can point at a real article.
"""

from __future__ import annotations

# Authors whose corpus has at least five ``*part_0*.txt`` files: the same nine
# as validation/diagnostics/document_parts_2026-11-18.
AUTHORS = [
    "augustine", "boethius", "chesterton", "douglass", "edwards",
    "james", "kempis", "mill", "newman",
]  # fmt: skip

# The fixed hold-out. Drawn once with
# ``sorted(random.Random(20261120).sample(sorted(AUTHORS), 3))`` and committed
# here, so the split is a list, not a re-draw.
SPLIT = {
    "dev": ["augustine", "boethius", "douglass", "edwards", "james", "newman"],
    "holdout": ["chesterton", "kempis", "mill"],
}

INSTITUTION = "Westfield College"
SEMINARY = "Northfield Theological Seminary"
CITY = "Grand Rapids, Michigan"

META = {
    "augustine": {
        "student": ("Maya", "Okafor"),
        "teacher": ("Dr.", "Ruth", "Calloway"),
        "course": "THEO 215: Christian Spirituality",
        "department": "Department of Theology",
        "name": "Augustine",
        "title": "The Senses and the Soul: Temptation and Attention in Ordinary Life",
        "short": "THE SENSES AND THE SOUL",
        "headings": [
            "The Ear and the Psalms",
            "The Lust of the Eyes",
            "Curiosity and Daily Distraction",
        ],
        "keywords": ["Augustine", "temptation", "the senses", "curiosity", "attention"],
        "abstract": (
            "This paper examines how ordinary sensory pleasures become occasions of temptation for a "
            "soul that is trying to attend to God. It begins with the use of music in public worship, "
            "weighing the danger that the beauty of a melody will be loved for itself against the "
            "benefit that sung psalms bring to weaker believers who are moved to devotion by them. It "
            "then turns to the eyes, which delight in form, colour, and light, and asks how a person can "
            "enjoy created beauty without allowing it to occupy the place that belongs to its Maker. A "
            "further section distinguishes pleasure from curiosity, the restless desire to see and know "
            "things for the sake of the experience alone, and shows that curiosity draws people even "
            "toward sights that disgust them. The paper argues that these temptations are not defeated "
            "once and for all but must be watched daily, because small distractions in conversation, "
            "reading, and even prayer continually pull the attention away. It concludes that honest "
            "self-examination, rather than a confident claim of victory, is the appropriate response "
            "to such temptations."
        ),
        "sources": [
            {
                "type": "book",
                "authors": [("Augustine", "")],
                "title": "Confessions",
                "translator": "Henry Chadwick",
                "publisher": "Oxford University Press",
                "city": "Oxford",
                "year": 1991,
                "short": "Confessions",
            },
            {
                "type": "book",
                "authors": [("Brown", "Peter")],
                "title": "Augustine of Hippo: A Biography",
                "edition": "Rev. ed.",
                "publisher": "University of California Press",
                "city": "Berkeley",
                "year": 2000,
                "short": "Augustine of Hippo",
            },
            {
                "type": "book",
                "authors": [("O'Donnell", "James J.")],
                "title": "Augustine: A New Biography",
                "publisher": "Ecco",
                "city": "New York",
                "year": 2005,
                "short": "Augustine",
            },
            {
                "type": "book",
                "authors": [("Harrison", "Carol")],
                "title": "Augustine: Christian Truth and Fractured Humanity",
                "publisher": "Oxford University Press",
                "city": "Oxford",
                "year": 2000,
                "short": "Christian Truth",
            },
        ],
    },
    "boethius": {
        "student": ("Daniel", "Whitcombe"),
        "teacher": ("Professor", "Alan", "Merriweather"),
        "course": "PHIL 230: Medieval Philosophy",
        "department": "Department of Philosophy",
        "name": "Boethius",
        "title": "Fortune, Virtue, and the Problem of Chance",
        "short": "FORTUNE, VIRTUE, AND CHANCE",
        "headings": ["Adversity as Opportunity", "Defining Chance", "The Meeting of Causes"],
        "keywords": ["Boethius", "fortune", "providence", "chance", "virtue"],
        "abstract": (
            "This paper considers two related questions about human life under providence: how a wise "
            "person should regard misfortune, and whether anything in the world happens by chance. The "
            "first part argues that adversity is not an evil to be resented but a test that gives virtue "
            "its opportunity, in the same way that a battle gives a soldier the occasion for courage. "
            "The labours of Hercules are read as an example of strength that wins its reward through "
            "hardship rather than in spite of it. The second part takes up the definition of chance. If "
            "chance means an event produced by random motion with no cause at all, the paper maintains "
            "that there is no such thing, since nothing comes from nothing and every event falls within "
            "an ordered whole. What people call chance is better described as the unforeseen meeting of "
            "causes that each act for their own ends, as when a farmer digging his field finds buried "
            "gold. The paper concludes that chance, rightly understood, is compatible with order and "
            "does not threaten the government of the world."
        ),
        "sources": [
            {
                "type": "book",
                "authors": [("Boethius", "")],
                "title": "The Consolation of Philosophy",
                "translator": "Victor Watts",
                "edition": "Rev. ed.",
                "publisher": "Penguin",
                "city": "London",
                "year": 1999,
                "short": "Consolation",
            },
            {
                "type": "book",
                "authors": [("Chadwick", "Henry")],
                "title": "Boethius: The Consolations of Music, Logic, Theology, and Philosophy",
                "publisher": "Clarendon Press",
                "city": "Oxford",
                "year": 1981,
                "short": "Boethius",
            },
            {
                "type": "book",
                "authors": [("Marenbon", "John")],
                "title": "Boethius",
                "publisher": "Oxford University Press",
                "city": "New York",
                "year": 2003,
                "short": "Boethius",
            },
            {
                "type": "book",
                "authors": [("Relihan", "Joel C.")],
                "title": "The Prisoner's Philosophy: Life and Death in Boethius's Consolation",
                "publisher": "University of Notre Dame Press",
                "city": "Notre Dame, IN",
                "year": 2007,
                "short": "Prisoner's Philosophy",
            },
        ],
    },
    "chesterton": {
        "student": ("Grace", "Lindqvist"),
        "teacher": ("Dr.", "Samuel", "Achebe"),
        "course": "REL 240: Religion and Modern Thought",
        "department": "Department of Religion",
        "name": "Chesterton",
        "title": "Personality and Love: Why Christian Art Looks Outward",
        "short": "PERSONALITY AND LOVE",
        "headings": [
            "Two Images of the Saint",
            "The Doctrine of the Universal Self",
            "Separation and Liberty",
        ],
        "keywords": ["Chesterton", "personality", "religious art", "pantheism", "liberty"],
        "abstract": (
            "This paper asks why Christian and Buddhist religious art present such different ideals of "
            "holiness, and argues that the difference reflects opposing views of personality. The Gothic "
            "saint is shown with open, astonished eyes, while the Buddhist sage is shown with eyes closed "
            "in inward repose. Starting from this contrast, the paper examines the claim, popular among "
            "some modern writers, that all religions teach one doctrine of a universal self in which the "
            "boundaries between persons disappear. It argues that such a doctrine cannot ground love of "
            "neighbour, because love requires someone other than oneself to love. Christianity, on this "
            "reading, rejoices that the world has been divided into distinct living persons, and that "
            "division is the condition of both charity and liberty. The paper then follows the political "
            "consequences of the two positions, suggesting that a theology which distinguishes God from "
            "the world also distinguishes good rulers from bad ones, and so supplies a reason to resist "
            "tyranny. It concludes that the outward gaze of the Christian saint expresses a philosophy "
            "of separation that makes wonder, love, and freedom possible."
        ),
        "sources": [
            {
                "type": "book",
                "authors": [("Chesterton", "G. K.")],
                "title": "Orthodoxy",
                "publisher": "Ignatius Press",
                "city": "San Francisco",
                "year": 1995,
                "short": "Orthodoxy",
            },
            {
                "type": "book",
                "authors": [("Ker", "Ian")],
                "title": "G. K. Chesterton: A Biography",
                "publisher": "Oxford University Press",
                "city": "Oxford",
                "year": 2011,
                "short": "Chesterton",
            },
            {
                "type": "book",
                "authors": [("Nichols", "Aidan")],
                "title": "G. K. Chesterton, Theologian",
                "publisher": "Sophia Institute Press",
                "city": "Manchester, NH",
                "year": 2009,
                "short": "Chesterton, Theologian",
            },
            {
                "type": "book",
                "authors": [("Besant", "Annie")],
                "title": "Esoteric Christianity",
                "publisher": "Theosophical Publishing Society",
                "city": "London",
                "year": 1901,
                "short": "Esoteric Christianity",
            },
        ],
    },
    "douglass": {
        "student": ("Marcus", "Bell"),
        "teacher": ("Professor", "Joan", "Whitfield"),
        "course": "HIST 318: Slavery and Freedom in America",
        "department": "Department of History",
        "name": "Douglass",
        "title": "Power Without Pity: The Slaveholder's Character Under Slavery",
        "short": "POWER WITHOUT PITY",
        "headings": [
            "First Impressions of the Master",
            "The Refusal to Intervene",
            "The System and the Self",
        ],
        "keywords": ["Douglass", "slavery", "slaveholders", "narrative", "moral character"],
        "abstract": (
            "This paper examines the character of a slaveholder as it appears to an enslaved child and "
            "argues that the cruelty of slavery cannot be explained by the personal temperament of "
            "individual masters alone. It begins with the narrator's early impressions of his old master, "
            "a man who at first seemed mild and who later appeared troubled, restless, and given to fits "
            "of anger. The central episode is the master's refusal to protect a young woman who had been "
            "brutally beaten by an overseer, a refusal that first opened the narrator's eyes to the moral "
            "condition of the plantation. The paper considers several possible explanations for this "
            "indifference and concludes that it followed from the logic of the system itself, which "
            "required the master to uphold the overseer's authority whatever the cost to the enslaved. "
            "It further argues that slaveholding gradually hardened those who practised it, so that "
            "ordinary feelings of compassion were suppressed in order to preserve control. The paper "
            "closes by suggesting that the narrative's attention to the master's inner unhappiness "
            "strengthens rather than softens its indictment of slavery."
        ),
        "sources": [
            {
                "type": "book",
                "authors": [("Douglass", "Frederick")],
                "title": "My Bondage and My Freedom",
                "editor": "John David Smith",
                "publisher": "Penguin",
                "city": "New York",
                "year": 2003,
                "short": "My Bondage",
            },
            {
                "type": "book",
                "authors": [("Blight", "David W.")],
                "title": "Frederick Douglass: Prophet of Freedom",
                "publisher": "Simon & Schuster",
                "city": "New York",
                "year": 2018,
                "short": "Prophet of Freedom",
            },
            {
                "type": "book",
                "authors": [("McFeely", "William S.")],
                "title": "Frederick Douglass",
                "publisher": "W. W. Norton",
                "city": "New York",
                "year": 1991,
                "short": "Douglass",
            },
            {
                "type": "book",
                "authors": [("Preston", "Dickson J.")],
                "title": "Young Frederick Douglass: The Maryland Years",
                "publisher": "Johns Hopkins University Press",
                "city": "Baltimore",
                "year": 1980,
                "short": "Young Frederick Douglass",
            },
        ],
    },
    "edwards": {
        "student": ("Hannah", "Price"),
        "teacher": ("Dr.", "Peter", "Vance"),
        "course": "HOMI 520: Preaching and Public Life",
        "department": "Department of Homiletics",
        "name": "Edwards",
        "title": "A Strong Rod Broken: Rulers, Providence, and Public Grief",
        "short": "A STRONG ROD BROKEN",
        "headings": [
            "Qualities of a Strong Rod",
            "The Loss of Rulers as Judgment",
            "Government and the Common Good",
        ],
        "keywords": [
            "Jonathan Edwards",
            "funeral sermon",
            "civil rulers",
            "providence",
            "public life",
        ],
        "abstract": (
            "This paper studies a funeral sermon on the death of a civil ruler and the account of public "
            "authority it develops. The sermon describes the qualities that make a ruler a strong rod: "
            "strong reason and discernment, a generous public spirit, firm integrity in the exercise of "
            "justice, and circumstances such as education and reputation that give a ruler advantage to "
            "act for the common good. It then argues that when such a ruler is removed by death, the loss "
            "is a judgment of God on the people and a proper occasion for mourning. The paper traces the "
            "reasons the sermon gives for this claim, including the dependence of a community's "
            "prosperity on its rulers, the example of the reign of Solomon, and the role of government "
            "in defending a society from both outward enemies and inward discord. Special attention is "
            "given to the analogy between the family and the commonwealth, which the sermon uses to show "
            "that order and authority are natural to human life. The paper concludes that the sermon "
            "joins a theology of providence to a practical political argument for honouring able public "
            "servants."
        ),
        "sources": [
            {
                "type": "chapter",
                "authors": [("Edwards", "Jonathan")],
                "title": "A Strong Rod Broken and Withered",
                "book": "Sermons and Discourses, 1743-1758",
                "editor": "Wilson H. Kimnach",
                "pages": "312-336",
                "publisher": "Yale University Press",
                "city": "New Haven",
                "year": 2003,
                "short": "Strong Rod",
            },
            {
                "type": "book",
                "authors": [("Marsden", "George M.")],
                "title": "Jonathan Edwards: A Life",
                "publisher": "Yale University Press",
                "city": "New Haven",
                "year": 2003,
                "short": "Jonathan Edwards",
            },
            {
                "type": "book",
                "authors": [("McDermott", "Gerald R.")],
                "title": "One Holy and Happy Society: The Public Theology of Jonathan Edwards",
                "publisher": "Pennsylvania State University Press",
                "city": "University Park, PA",
                "year": 1992,
                "short": "One Holy and Happy Society",
            },
            {
                "type": "book",
                "authors": [("Stout", "Harry S.")],
                "title": "The New England Soul: Preaching and Religious Culture in Colonial New England",
                "publisher": "Oxford University Press",
                "city": "New York",
                "year": 1986,
                "short": "New England Soul",
            },
        ],
    },
    "james": {
        "student": ("Theo", "Ramirez"),
        "teacher": ("Dr.", "Ingrid", "Solberg"),
        "course": "PSYC 342: Psychology of Religion",
        "department": "Department of Psychology",
        "name": "James",
        "title": "Light, Automatism, and Joy in the Conversion Crisis",
        "short": "THE CONVERSION CRISIS",
        "headings": ["Automatisms at Revivals", "Photisms", "The Ecstasy of Happiness"],
        "keywords": [
            "William James",
            "conversion",
            "automatism",
            "religious experience",
            "revivals",
        ],
        "abstract": (
            "This paper examines several features of sudden religious conversion as they are described "
            "in first-person testimony and interpreted by a psychological observer. It first considers "
            "motor automatisms, the involuntary falling, trembling, and crying out that accompanied "
            "revival meetings and were once taken as proofs of supernatural power. It then turns to "
            "sensory automatisms, especially the luminous visions or photisms that many converts report, "
            "ranging from a vague brightness to an overwhelming light that seems to fill the room. A "
            "third section discusses the sense of release and the ecstasy of happiness that frequently "
            "follows the crisis, drawing on several detailed accounts. Throughout, the paper argues that "
            "these phenomena are best understood as expressions of a mental condition in which emotion "
            "that has been long resisted suddenly takes control, and that their psychological "
            "explanation does not by itself settle the question of their value. The paper concludes "
            "that the significance of conversion should be judged by its fruits in the later life of "
            "the convert rather than by the strangeness of its accompanying experiences."
        ),
        "sources": [
            {
                "type": "book",
                "authors": [("James", "William")],
                "title": "The Varieties of Religious Experience: A Study in Human Nature",
                "publisher": "Penguin",
                "city": "New York",
                "year": 1982,
                "short": "Varieties",
            },
            {
                "type": "book",
                "authors": [("Taves", "Ann")],
                "title": "Fits, Trances, and Visions: Experiencing Religion and Explaining Experience from Wesley to James",
                "publisher": "Princeton University Press",
                "city": "Princeton",
                "year": 1999,
                "short": "Fits, Trances, and Visions",
            },
            {
                "type": "book",
                "authors": [("Taylor", "Charles")],
                "title": "Varieties of Religion Today: William James Revisited",
                "publisher": "Harvard University Press",
                "city": "Cambridge, MA",
                "year": 2002,
                "short": "Varieties of Religion Today",
            },
            {
                "type": "book",
                "authors": [("Leuba", "James H.")],
                "title": "The Psychology of Religious Mysticism",
                "publisher": "Kegan Paul",
                "city": "London",
                "year": 1925,
                "short": "Religious Mysticism",
            },
        ],
    },
    "kempis": {
        "student": ("Clare", "Donnelly"),
        "teacher": ("Rev. Dr.", "Martin", "Hale"),
        "course": "SPIR 501: Classics of Christian Devotion",
        "department": "Department of Spiritual Theology",
        "name": "Thomas a Kempis",
        "title": "Unworthy Guests: Humility and Trust Before the Sacrament",
        "short": "UNWORTHY GUESTS",
        "headings": ["The Lowly Gate", "Trust in God Alone", "The Invitation to the Sacrament"],
        "keywords": ["Thomas a Kempis", "humility", "devotion", "Eucharist", "trust"],
        "abstract": (
            "This paper explores a sequence of devotional reflections on humility, trust in God, and "
            "preparation for Holy Communion. It begins with the warning that those who argue about who is "
            "greatest in heaven may not be worthy to be counted among the least, and with the claim that "
            "the low gate of the kingdom admits only those who humble themselves like children. The paper "
            "then considers a prayer in which every earthly comfort, including friends, counsellors, and "
            "books, is judged weak and unstable apart from God, who alone is the end of all good. The "
            "final and longest section examines the invitation to the sacrament, in which the believer "
            "hears the words of Christ calling the weary to be refreshed and responds with a sense of "
            "deep unworthiness. Comparisons with Noah building the ark and Moses preparing the ark of the "
            "covenant sharpen this contrast between the care of holy men and the carelessness of the "
            "ordinary believer. The paper argues that the text holds confidence and fear together, "
            "encouraging approach to the sacrament precisely by insisting that no one is worthy of it."
        ),
        "sources": [
            {
                "type": "book",
                "authors": [("Thomas a Kempis", "")],
                "title": "The Imitation of Christ",
                "translator": "William C. Creasy",
                "publisher": "Ave Maria Press",
                "city": "Notre Dame, IN",
                "year": 1989,
                "short": "Imitation",
            },
            {
                "type": "book",
                "authors": [("Van Engen", "John")],
                "title": "Sisters and Brothers of the Common Life: The Devotio Moderna and the World of the Later Middle Ages",
                "publisher": "University of Pennsylvania Press",
                "city": "Philadelphia",
                "year": 2008,
                "short": "Sisters and Brothers",
            },
            {
                "type": "book",
                "authors": [("Post", "R. R.")],
                "title": "The Modern Devotion: Confrontation with Reformation and Humanism",
                "publisher": "Brill",
                "city": "Leiden",
                "year": 1968,
                "short": "Modern Devotion",
            },
            {
                "type": "book",
                "authors": [("von Habsburg", "Maximilian")],
                "title": "Catholic and Protestant Translations of the Imitatio Christi, 1425-1650",
                "publisher": "Ashgate",
                "city": "Farnham",
                "year": 2011,
                "short": "Translations",
            },
        ],
    },
    "mill": {
        "student": ("Jordan", "Reyes"),
        "teacher": ("Professor", "Ellen", "Hartley"),
        "course": "PHIL 210: Moral and Political Philosophy",
        "department": "Department of Philosophy",
        "name": "Mill",
        "title": "Harm, Trade, and Prevention: Applying the Liberty Principle",
        "short": "APPLYING THE LIBERTY PRINCIPLE",
        "headings": [
            "The Limits of the Harm Principle",
            "Trade as a Social Act",
            "Poisons and Prevention",
        ],
        "keywords": ["Mill", "liberty", "harm principle", "free trade", "prevention"],
        "abstract": (
            "This paper applies the principle that society may interfere with individual conduct only to "
            "prevent harm to others to several practical questions of policy. It begins by restating the "
            "two maxims of the principle and then argues that harm to others, while necessary to justify "
            "interference, is not always sufficient, since competition in trade, examinations, and "
            "employment regularly disappoints some people without wronging them. The paper next "
            "considers trade as a social act and defends free trade on grounds of efficiency rather than "
            "individual liberty, noting that restrictions on trade raise questions of liberty only where "
            "they limit what buyers may obtain. The central section examines the sale of poisons as a "
            "test case for the preventive functions of government. It distinguishes legitimate "
            "precautions, such as labelling and the recording of sales, from prohibitions that would "
            "burden the many in order to obstruct the few. The paper concludes that the liberty "
            "principle does not decide every case mechanically but provides a reliable guide for "
            "weighing public safety against individual choice."
        ),
        "sources": [
            {
                "type": "book",
                "authors": [("Mill", "John Stuart")],
                "title": "On Liberty",
                "editor": "Elizabeth Rapaport",
                "publisher": "Hackett",
                "city": "Indianapolis",
                "year": 1978,
                "short": "On Liberty",
            },
            {
                "type": "book",
                "authors": [("Gray", "John")],
                "title": "Mill on Liberty: A Defence",
                "edition": "2nd ed.",
                "publisher": "Routledge",
                "city": "London",
                "year": 1996,
                "short": "Mill on Liberty",
            },
            {
                "type": "book",
                "authors": [("Riley", "Jonathan")],
                "title": "Routledge Philosophy Guidebook to Mill on Liberty",
                "publisher": "Routledge",
                "city": "London",
                "year": 1998,
                "short": "Guidebook",
            },
            {
                "type": "book",
                "authors": [("Berlin", "Isaiah")],
                "title": "Four Essays on Liberty",
                "publisher": "Oxford University Press",
                "city": "Oxford",
                "year": 1969,
                "short": "Four Essays",
            },
        ],
    },
    "newman": {
        "student": ("Samuel", "Osei"),
        "teacher": ("Dr.", "Laura", "Brennan"),
        "course": "EDUC 410: Philosophy of Higher Education",
        "department": "Department of Education",
        "name": "Newman",
        "title": "Knowledge as Its Own End: The Circle of the Sciences",
        "short": "KNOWLEDGE AS ITS OWN END",
        "headings": ["The Circle of the Sciences", "The Question of Use", "Liberal Knowledge"],
        "keywords": ["Newman", "university", "liberal education", "knowledge", "curriculum"],
        "abstract": (
            "This paper considers the claim that a university should teach the whole circle of "
            "knowledge, and examines what students gain from studying in such a place even when they "
            "pursue only a few subjects themselves. It argues that because all branches of knowledge are "
            "connected, each science has its meaning altered by its relation to the others, much as a "
            "colour changes its shade according to the colours placed beside it. A student who lives "
            "among teachers of many disciplines therefore acquires a sense of proportion and a habit of "
            "mind that no single subject could provide. The paper then turns to the practical objection "
            "that such learning is of no use. In reply, it defends the view that liberal knowledge is an "
            "end sufficient in itself, desirable for its own sake and not merely as a means to "
            "professional skill or material gain. It concludes that the cultivation of the intellect is "
            "a real and tangible good, and that the value of a university education should be measured "
            "by the formation of the mind it produces rather than by its immediate applications."
        ),
        "sources": [
            {
                "type": "book",
                "authors": [("Newman", "John Henry")],
                "title": "The Idea of a University",
                "editor": "Frank M. Turner",
                "publisher": "Yale University Press",
                "city": "New Haven",
                "year": 1996,
                "short": "Idea of a University",
            },
            {
                "type": "book",
                "authors": [("Ker", "Ian")],
                "title": "John Henry Newman: A Biography",
                "publisher": "Oxford University Press",
                "city": "Oxford",
                "year": 1988,
                "short": "Newman",
            },
            {
                "type": "book",
                "authors": [("MacIntyre", "Alasdair")],
                "title": "God, Philosophy, Universities: A Selective History of the Catholic Philosophical Tradition",
                "publisher": "Rowman & Littlefield",
                "city": "Lanham, MD",
                "year": 2009,
                "short": "God, Philosophy, Universities",
            },
            {
                "type": "book",
                "authors": [("Pelikan", "Jaroslav")],
                "title": "The Idea of the University: A Reexamination",
                "publisher": "Yale University Press",
                "city": "New Haven",
                "year": 1992,
                "short": "Idea of the University",
            },
        ],
    },
}

# Shared sources, drawn from deterministically per paper. Articles carry DOIs
# (10.5555 example prefix); web pages carry URLs and no date ("n.d.").
POOL = [
    {
        "type": "book",
        "authors": [("Booth", "Wayne C."), ("Colomb", "Gregory G."), ("Williams", "Joseph M.")],
        "title": "The Craft of Research",
        "edition": "4th ed.",
        "publisher": "University of Chicago Press",
        "city": "Chicago",
        "year": 2016,
        "short": "Craft of Research",
    },
    {
        "type": "article",
        "authors": [("Hollis", "Margaret A.")],
        "title": "Reading Historical Sources in the Undergraduate Classroom",
        "journal": "Journal of Humanities Pedagogy",
        "volume": 14,
        "issue": 2,
        "pages": "115-132",
        "year": 2019,
        "doi": "10.5555/jhp.2019.0142",
        "short": "Reading Historical Sources",
    },
    {
        "type": "web",
        "title": "Guide to Reading Primary Sources",
        "site": "Center for Historical Reading",
        "url": "https://www.example.org/guides/primary-sources",
        "short": "Guide to Reading Primary Sources",
    },
    {
        "type": "book",
        "authors": [("MacIntyre", "Alasdair")],
        "title": "After Virtue: A Study in Moral Theory",
        "edition": "3rd ed.",
        "publisher": "University of Notre Dame Press",
        "city": "Notre Dame, IN",
        "year": 2007,
        "short": "After Virtue",
    },
    {
        "type": "article",
        "authors": [("Adeyemi", "Tunde"), ("Moss", "Sarah K.")],
        "title": "Primary Texts and Student Argument",
        "journal": "Teaching Philosophy Today",
        "volume": 8,
        "issue": 1,
        "pages": "44-61",
        "year": 2021,
        "doi": "10.5555/tpt.2021.0081",
        "short": "Primary Texts",
    },
    {
        "type": "book",
        "authors": [("Taylor", "Charles")],
        "title": "A Secular Age",
        "publisher": "Belknap Press of Harvard University Press",
        "city": "Cambridge, MA",
        "year": 2007,
        "short": "Secular Age",
    },
    {
        "type": "web",
        "title": "Citing Classical and Medieval Texts",
        "site": "Northfield Seminary Library",
        "url": "https://library.example.edu/guides/classical-texts",
        "short": "Citing Classical and Medieval Texts",
    },
    {
        "type": "book",
        "authors": [("Hadot", "Pierre")],
        "title": "Philosophy as a Way of Life",
        "translator": "Michael Chase",
        "publisher": "Blackwell",
        "city": "Oxford",
        "year": 1995,
        "short": "Philosophy as a Way of Life",
    },
    {
        "type": "article",
        "authors": [("Whitaker", "Lena")],
        "title": "Devotion and Argument in Early Modern Prose",
        "journal": "Studies in Religious Rhetoric",
        "volume": 22,
        "issue": 4,
        "pages": "301-320",
        "year": 2017,
        "doi": "10.5555/srr.2017.0224",
        "short": "Devotion and Argument",
    },
    {
        "type": "book",
        "authors": [("Williams", "Bernard")],
        "title": "Ethics and the Limits of Philosophy",
        "publisher": "Harvard University Press",
        "city": "Cambridge, MA",
        "year": 1985,
        "short": "Ethics and the Limits",
    },
    {
        "type": "web",
        "title": "Writing About Historical Texts",
        "site": "The Writing Center, Westfield College",
        "url": "https://writing.example.edu/handouts/historical-texts",
        "short": "Writing About Historical Texts",
    },
    {
        "type": "article",
        "authors": [("Novak", "Peter J.")],
        "title": "Moral Psychology and the History of Ideas",
        "journal": "Review of Ethics and Culture",
        "volume": 31,
        "issue": 1,
        "pages": "77-98",
        "year": 2020,
        "doi": "10.5555/rec.2020.0311",
        "short": "Moral Psychology",
    },
    {
        "type": "book",
        "authors": [("Murdoch", "Iris")],
        "title": "The Sovereignty of Good",
        "publisher": "Routledge",
        "city": "London",
        "year": 1970,
        "short": "Sovereignty of Good",
    },
    {
        "type": "book",
        "authors": [("Pelikan", "Jaroslav")],
        "title": "The Emergence of the Catholic Tradition (100-600)",
        "publisher": "University of Chicago Press",
        "city": "Chicago",
        "year": 1971,
        "short": "Emergence",
    },
    {
        "type": "article",
        "authors": [("Castellano", "Rosa")],
        "title": "Translation and Authority in Classroom Editions",
        "journal": "Journal of Textual Studies",
        "volume": 9,
        "issue": 3,
        "pages": "210-228",
        "year": 2018,
        "doi": "10.5555/jts.2018.0093",
        "short": "Translation and Authority",
    },
    {
        "type": "book",
        "authors": [("Turabian", "Kate L.")],
        "title": "A Manual for Writers of Research Papers, Theses, and Dissertations",
        "edition": "9th ed.",
        "publisher": "University of Chicago Press",
        "city": "Chicago",
        "year": 2018,
        "short": "Manual for Writers",
    },
    {
        "type": "article",
        "authors": [("Ferreira", "Ana"), ("Lund", "Erik")],
        "title": "Close Reading and the Long Quotation",
        "journal": "College Composition Quarterly",
        "volume": 12,
        "issue": 2,
        "pages": "88-104",
        "year": 2022,
        "doi": "10.5555/ccq.2022.0122",
        "short": "Close Reading",
    },
    {
        "type": "book",
        "authors": [("Jacobs", "Alan")],
        "title": "A Theology of Reading: The Hermeneutics of Love",
        "publisher": "Westview Press",
        "city": "Boulder, CO",
        "year": 2001,
        "short": "Theology of Reading",
    },
]

# Negative controls: student writing that uses the words the rules look for.
ABSTRACT_PROSE = (
    "Abstract as this distinction may sound, everything that follows depends on it. The abstract "
    "nature of the question should not hide how concrete its consequences are for a reader, who is "
    "asked not only to follow an argument but to change the way he lives. It is easy to admire such "
    "reasoning at a distance and much harder to accept what it requires of us."
)
REFERENCES_PROSE = (
    "References to {name} in this paper follow the edition listed at the end, and quotations keep its "
    "spelling and punctuation. References alone do not make an argument, however, and the passages "
    "discussed so far have to be read in the light of the whole work rather than as proof texts."
)
PRAYER_LINES = [
    "Let us pray.",
    "Almighty God, from whom every good gift comes,",
    "teach us to receive what you give with thankful hearts,",
    "to bear what you send with patience,",
    "and to love you above all things.",
    "Through Jesus Christ our Lord.",
    "Amen.",
]
LETTER_OPEN = "Dear Thomas,"
LETTER_CLOSE = ["With affection,", "{first}"]
