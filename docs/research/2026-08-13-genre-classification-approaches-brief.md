# Genre/Register Classification for Short Prose — Research Brief (2026-08-13)

## What we asked

`resolvers.resolve_genre` is a hand-written rule chain that fails to positively discriminate genre on real prose (84% of an independent 10-author corpus falls through to the terminal `else`, `correspondence`), leaving `GENRE_INVARIANT_WEIGHTS_ENABLED` inert. What are practical, proven approaches (2020–2026) for classifying the genre/register of a 300–2000-word passage, under our constraints: dependency-light (sklearn available, sentence-transformers optional at runtime), explainable enough for an academic-integrity product, and trainable/validatable on modest public corpora?

## Approaches

### 1. Classical supervised: TF-IDF / function-word features + linear SVM or logistic regression
- **How:** Bag-of-words and/or character n-gram TF-IDF vectors (optionally plus POS/grammatical counts) into a linear one-vs-rest SVM or logistic regression.
- **Realistic accuracy:** On CORE's 26 sub-registers, a linear SVM reaches **~74.5% F1 with combined lexico-grammatical features**, ~70.8% with bag-of-words alone, and only ~59.9% with grammatical features alone (Laippala et al., PLOS ONE 2021). Easy registers (news, lyrics, encyclopedia) exceed 85% F1; fuzzy ones (advice, opinion/travel blogs) fall to ≤50%. Older Brown-corpus work is weaker: Karlgren & Cutting (1994) got ~52% fit on hand categories; Kessler et al. (1997) showed surface cues suffice for facet-based genre detection; Stamatatos et al. (2000) classified genre from common-word frequencies alone. A 6–8 class task with clean labels should be easier than 26-class CORE, but no published number exists for our exact label set — treat in-domain performance as *plausibly* 75–85% F1, to be measured, not assumed.
- **Cost/dependencies:** sklearn only — already in the stack. Training on a few hundred labeled docs per class is feasible on a laptop.
- **Explainability:** Best of all options — per-class linear coefficients name the words/features driving each call ("classified `sermon` because of second-person address + hortatory verbs"), which fits the product's pastoral/explainable positioning. This is exactly why Laippala et al. chose linear SVMs.

### 2. Fine-tuned transformers / off-the-shelf X-GENRE
- **How:** Fine-tune BERT/XLM-R on genre labels, or download the CLASSLA `xlm-roberta-base-multilingual-text-genre-classifier` (X-GENRE) trained on CORE + FTD + GINCO (9 labels incl. Prose/Lyrical, Instruction, Opinion/Argumentation, Information/Explanation).
- **Realistic accuracy:** X-GENRE reports **micro-F1 0.797 / macro-F1 0.794 in-dataset** and **0.688 micro-F1 cross-dataset** (EN-GINCO) — the cross-dataset drop is the honest number for out-of-domain text (Kuzman et al. 2023). Multi-label BERT on full CORE reaches ~68% F1; a 2024 multilingual study gets 77% micro / ~71% macro F1 over 25 classes with XLM-R-large. The ceiling on messy web registers is roughly 70–80% F1, not 95%.
- **Cost/dependencies:** torch + transformers (~1–2 GB model) — heavy for our runtime; conflicts with the dependency-light constraint unless run offline/batch.
- **Explainability:** Low; requires attribution add-ons. Also its web-register label set doesn't match ours (no `exegesis`/`sermon`), so it's a feature/prior at best, not a drop-in.

### 3. Embedding prototypes / SetFit few-shot (sentence-transformers)
- **How:** Embed the passage; classify by cosine similarity to per-genre prototype centroids built from a handful of exemplar texts, or train a SetFit-style contrastive few-shot classifier (logistic head over embeddings).
- **Realistic accuracy:** No published F1 for register tasks in this exact configuration — **unknown for our labels; must be measured**. HF's own benchmark shows SetFit zero-shot with a small embedding model is both *faster and more accurate* than BART-MNLI zero-shot, and the SetFit paper shows ~8 examples/class can rival full fine-tuning on some tasks.
- **Cost/dependencies:** sentence-transformers is already an optional dependency (Tier 10 pattern); classifier head is sklearn. Degrades to TF-IDF prototypes when unavailable — same fallback structure Tier 10 already uses.
- **Explainability:** Moderate — "nearest genre prototype, distance X" plus exemplar texts is presentable; weaker than linear coefficients.

### 4. NLI zero-shot (e.g., `bart-large-mnli`)
- **How:** Pose each genre as an entailment hypothesis ("This text is a sermon.") and score.
- **Realistic accuracy:** Not reliably documented for genre/register — **unknown**. Known failure mode: abstract labels (which genre names are) degrade zero-shot NLI performance, and small distilled variants drop sharply.
- **Cost/dependencies:** Large model, slow per-call, torch required. **Explainability:** poor. Not recommended given constraints; noted for completeness.

## Corpora available for training/validation

- **CORE** (Corpus of Online Registers of English) — ~48k web texts, 8 main registers / 26+ sub-registers, distributed via TurkuNLP GitHub. The de-facto benchmark; useful for pretraining/transfer, but web registers ≠ our academic labels.
- **X-GENRE dataset / GINCO / FTD** — cross-mapped genre datasets (9-label schema) on CLARIN.SI; small (~1.7k training instances for X-GENRE) but curated.
- **Brown corpus** — 500 texts, 15 categories including *religion* and *learned* (academic prose); ships with NLTK. Dated (1961) and coarse, but free and directly includes religious/academic prose.
- **BNC core genres** — Lijffijt & Nevalainen show simple frequency models separate core BNC genres; BNC access requires registration.
- **Theological/academic genres specifically:** no labeled public corpus found. Adjacent resources: Pew's "Digital Pulpit" analyzed ~50k scraped online sermons (corpus not redistributed); "Computational Homiletics" (Heidelberg) and Palayon et al. (2025) do corpus analysis of sermons/religious groups but not genre classification. Public-domain theological texts (CCEL, Project Gutenberg — the same sources behind `validation/public_authors/`) can be self-labeled by document type (sermon collections, commentaries/exegesis, letters, treatises) to build a modest in-domain set — this appears to be the only realistic path to in-domain labels.

## Recommended direction for resolve_genre

Replace the rule chain with a TF-IDF (word 1–2-gram + char 3–4-gram, plus our existing function-word/register features) linear classifier (logistic regression or SVM, one-vs-rest, calibrated probabilities with an explicit abstain/`unknown` outcome instead of a terminal `else`), trained on a small purpose-built corpus: CORE-derived texts mapped to our labels plus self-labeled public-domain theological documents. The CORE literature suggests linear models give up little accuracy versus transformers on register tasks (~74% vs ~68–80% F1 in the published comparisons) while keeping per-class coefficient explanations, which our product needs; an embedding-prototype variant via the optional sentence-transformers dependency is a reasonable second head to A/B, with TF-IDF degradation mirroring Tier 10. Caveat: no published numbers exist for a seminary-genre label set (essay/exegesis/sermon/reflection/research paper/correspondence), so any accuracy expectation is extrapolated — hold out hand-labeled documents (e.g., the Lewis hand-labelled genres already in `validation/genre_crossgenre_2026-08/`) and require the classifier to beat the 84%-collapse baseline on them before re-running `genre_invariant_validate.py`.

## Sources

- [Laippala et al. 2021, "Exploring the role of lexis and grammar for the stable identification of register in an unrestricted corpus of web documents" (PLOS ONE / PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC8550160/) — linear SVM on CORE, F1 numbers by feature set.
- [Laippala et al., "Register identification from the unrestricted open Web using CORE" (Lang. Resources & Evaluation)](https://dl.acm.org/doi/abs/10.1007/s10579-022-09624-1) — multi-label BERT ~68% F1 on full CORE.
- [TurkuNLP CORE corpus distribution (GitHub)](https://github.com/TurkuNLP/CORE-corpus)
- [Henriksson et al. 2024, "Untangling the Unrestricted Web: Automatic Identification of Multilingual Registers" (arXiv:2406.19892)](https://arxiv.org/html/2406.19892v1) — XLM-R ~77% micro / ~71% macro F1, 25 classes.
- [Kuzman et al. 2023, "Automatic Genre Identification for Robust Enrichment of Massive Text Collections" (MAKE)](https://doi.org/10.3390/make5030059) — X-GENRE in-dataset vs cross-dataset F1.
- [CLASSLA X-GENRE classifier (Hugging Face)](https://huggingface.co/classla/xlm-roberta-base-multilingual-text-genre-classifier)
- [Kuzman & Ljubešić, "Automatic genre identification: a survey" (Lang. Resources & Evaluation, 2023)](https://link.springer.com/article/10.1007/s10579-023-09695-8)
- [X-GENRE dataset (CLARIN.SI)](https://www.clarin.si/repository/xmlui/handle/11356/1961)
- [Kessler, Nunberg & Schütze 1997, "Automatic Detection of Text Genre" (ACL)](https://aclanthology.org/P97-1005.pdf)
- [Stamatatos et al. 2000, "Text genre detection using common word frequencies" (COLING)](https://dl.acm.org/doi/10.3115/992730.992763)
- [Lijffijt & Nevalainen, "A simple model for recognizing core genres in the BNC" (VARIENG)](https://varieng.helsinki.fi/series/volumes/19/lijffijt_nevalainen/)
- [SetFit zero-shot docs (Hugging Face)](https://huggingface.co/docs/setfit/how_to/zero_shot) — SetFit vs BART-MNLI speed/accuracy tradeoff.
- [Pew Research Center 2019, "The Digital Pulpit: A Nationwide Analysis of Online Sermons"](https://www.pewresearch.org/data-labs/2019/12/16/the-digital-pulpit-a-nationwide-analysis-of-online-sermons/)
- [Fucker, "Computational Homiletics" (Heidelberg University Press)](https://books.ub.uni-heidelberg.de/heibooks/catalog/view/1748/3014/132659)
- [Palayon, Todd & Vungthong 2025, "Multifaceted approach of corpus analysis for characterizing Christian religious groups" (SAGE)](https://journals.sagepub.com/doi/10.1177/20503032251344351)
