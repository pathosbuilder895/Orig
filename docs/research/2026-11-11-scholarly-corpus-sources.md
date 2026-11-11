# Sources for a large same-author scholarly corpus: access, licences, author identity

| | |
|---|---|
| **Tool** | Claude Code with live HTTP checks from the build sandbox (curl and `urllib`); every status code, header and quoted term below was read on the date given. Nothing here is from memory. |
| **Date** | 2026-11-11 (all "checked" dates are this day) |
| **Question** | Which public sources let us fetch full text programmatically, under a licence that permits local research use, for at least 1,000 authors who each have at least 6 usable single-author English papers (4 past plus 2 held-out), and which of them let us count an author's usable papers from metadata alone, before any download? Candidates: arXiv, PhilArchive / PhilPapers, OpenAlex, Semantic Scholar, CORE, PubMed Central open-access subset, any open theology or religious-studies repository. |
| **Decision it informs** | Where `validation/scholarly/` screens and fetches from (`validation/scholarly/README.md`, `validation/scholarly/policy.py`, `screen.py`, `fetch.py`); the licence policy in `policy.PERMITTED_LICENCES`; whether the 1,000-author target is reachable at all. Context: `docs/research/2026-11-10-genre-robust-stylometric-features.md` and the 2026-11-10 opportunity-mask study (13 authors is too few to resolve false-flag rates). |
| **Proposed repo path** | `docs/research/2026-11-11-scholarly-corpus-sources.md` |

## Verdict in one paragraph

Local research use is allowed, and the science pool is large enough for the 1,000-author target (fetching it is limited by arXiv's rate rule); the humanities pool is **not** large enough. The workable route is OpenAlex for screening (CC0 metadata, persistent ORCID-anchored author ids, per-paper licence and PDF link) plus PDF fetches from the hosting site, restricted to papers with a CC or public-domain licence, or hosted on arXiv, whose API terms explicitly allow storing and using content "for research purposes". Counted from metadata only, 6,828 science authors and 1,031 humanities authors have at least 8 candidate papers. Humanities is the binding constraint: 1,031 screened authors is barely above the 1,000-usable target before any fetch loss, and fetch loss is large (see the PR description for the measured funnel). PhilArchive / PhilPapers and Semantic Scholar could not be used from this network, so the humanities pool could not be widened from them; papers without a stated licence are excluded by policy, which removes most author-posted repository copies.

## What the corpus needs from a source

1. **Count before download.** Per-paper metadata that says: single author, English, open access with a *PDF* link, a licence, and a page count or type, so an author's candidates can be counted without fetching anything.
2. **A persistent author id**, because an author is the unit of independence and a wrong-author merge silently poisons a "same author" label.
3. **A licence that permits local research use.** The repository stores only a list of papers and a fetch script, never text, so what matters is the right to fetch, store locally and analyse.
4. **Programmatic full text** at a rate a single machine can sustain without being blocked.

## Source by source

| Source | Programmatic full text | Rate limit observed or stated | Licence for local research use | Author identifier | Single-author count without download | Used? |
|---|---|---|---|---|---|---|
| **OpenAlex** | Metadata only; gives `pdf_url` per location, which we fetch from the host | Anonymous budget is shared per IP and was already exhausted here (HTTP 429, "$0 remaining", reset at midnight UTC). Free key: 10,000 credits per day ($1), 1 credit per list request, `search` costs 10x; cursor paging needs a key; a new key is capped at about $0.10 per 5 minutes until $1 is spent | Metadata is CC0. Full-text licence is per paper, per location (`locations[].license`) | OpenAlex author id (algorithmic), with ORCID when known and `observed_orcids` exposing merges | Yes: `authors_count`, `authorships`, `locations[].license` / `pdf_url` / `version`, `biblio.first_page` / `last_page`, `type`, `language`, `primary_topic` | **Yes, for all screening** |
| **arXiv** | Yes: `arxiv.org/pdf/<id>`, LaTeX at `arxiv.org/e-print/<id>`; bulk PDF and source on a requester-pays S3 bucket (about 9.2 TB) | One request per 3 seconds, one connection at a time, across all machines under your control | ToU: "Retrieve, store, and use the content of arXiv e-prints for your own personal use, or for research purposes." Redistribution needs the copyright holder's permission. Most papers are `nonexclusive-distrib`, so we record the class `arxiv-tou-research`, not a CC licence | None. `authors_parsed` is a name string. ORCID is optional and not in the bulk metadata | Partly, by name only (see below) | **Yes, as a full-text host** for arXiv-located works found through OpenAlex |
| **PhilArchive / PhilPapers** | Could not be tested: every request, including the home page, returned a Cloudflare challenge (HTTP 403, "Attention Required") from this network | Not testable | Not verifiable here. Author-posted papers usually carry no licence statement, which our policy excludes | PhilPapers has author profiles; not verifiable here | Not testable | **No** |
| **Semantic Scholar** | Needs an API key and acceptance of the "Semantic Scholar API License Agreement" (last updated 2023-05-17). Anonymous requests got HTTP 429 from the shared IP | Shared-IP throttle; keyed limits not tested | Governed by that agreement; not assessed further | Semantic Scholar author ids, not tested | Not tested | **No** |
| **CORE** | v3 API returns full text inside works records | Unauthenticated: header `x-ratelimit-limit: 10`; after 10 requests, HTTP 429 with a 10-minute `x-ratelimit-retry-after` | Per record and uneven; not assessed in depth | Author names only | No licence-by-paper count tested | **No** |
| **PMC open-access subset / Europe PMC** | The PMC page says "The PMC Cloud Service, PMC OAI-PMH Service, E-Utilities and BioC API are the only services that may be used for automated retrieval of PMC content. Systematic retrieval (or bulk retrieval) of articles through any other automated process is prohibited." Europe PMC's REST API was reachable | Not tested | "License terms vary", per article | Europe PMC lists ORCID in `authorIdList` for some authors | Europe PMC has `LICENSE` and `OPEN_ACCESS` fields | **No**: biomedical papers are overwhelmingly multi-author, so single-author yield is very small, and PMC's retrieval rules constrain a crawl |
| **Open theology / religious studies** | Reached through OpenAlex, not a separate repository: AOSIS journals (HTS Teologiese Studies, Verbum et Ecclesia, In die Skriflig) publish CC BY PDFs; counts below | Per host | Per paper, CC BY mostly | Via OpenAlex | Yes, via OpenAlex | **Yes, via OpenAlex** |

Also reachable and not needed: Crossref REST (no key, licence URLs per work, ORCID sparse), Unpaywall, DOAJ, ORCID public API, Zenodo.

## OpenAlex in detail (the screening source)

* **Why not `group_by`.** `group_by=authorships.author.id` returns at most the first 200 groups ("Group-by is limited to page 1 with up to 200 results"). Screening therefore cursor-pages every matching work (200 per request) and groups locally. This needs the free key.
* **Filters used** (all checked to work): `authors_count:1`, `language:en`, `has_orcid:true`, `type:article`, `primary_location.source.type:journal`, `best_oa_location.license:<cc list>`, `primary_topic.field.id`, `is_paratext:false`, `is_retracted:false`, `publication_year`.
* **Metadata fields that let us count without downloading:** author id and ORCIDs, licence, PDF link and version per location, first and last page (pages known for most journal articles), `type`, title (to drop reviews, editorials, errata), field and subfield (to test an author's papers for coherence).
* **Reliability of the author id.** OpenAlex ids are algorithmic. The first page we fetched already contained a merge: one author id carried two distinct ORCIDs in `observed_orcids` (two different people, or one person with two records). The screen therefore keeps an author only if exactly one ORCID is observed across all their candidates, the papers span at most 40 years, and a dominant subfield holds at least half of them. This is strong, not proof.
* **Volume** (counts read 2026-11-11, single-author English articles with an ORCID): humanities (field 12, CC-licensed journal articles) 319,809 works scanned, 198,000 or so passing the per-paper rules, 120,582 distinct authors with at least one candidate, 1,164 with at least 8 (1,031 after the evidence-based host and title exclusions in `policy.py`; 87 rejected for unrelated fields and 59 for more than one ORCID before those exclusions); science (15 natural and formal science fields, CC-licensed journal articles plus arXiv-located works) 946,808 works scanned, 270,748 authors with at least one candidate, 7,983 with at least 8 (6,828 after the science exclusions; 1,328 rejected for unrelated fields and 374 for more than one ORCID). Screening cost 1,712 and 4,814 OpenAlex requests respectively, about 25 minutes of wall time each at the new-key rate cap.

## arXiv: why it is a host and not a screening source

The arXiv metadata snapshot (CC0, mirrored weekly on Hugging Face as `librarian-bots/arxiv-metadata-snapshot`, last modified 2026-10-27, 2.6 GB of parquet) holds 3,224,635 records, of which 580,676 have one author. Counting by author name, 13,824 name strings have at least 8 single-author papers. That number is **not** an author count: names are not identifiers (the same string can be several people, and one person can use several spellings), which is exactly the wrong-author-merge risk the task asks us to avoid. arXiv licences among the single-author papers: `nonexclusive-distrib` 333,816; none stated 134,350; CC BY 4.0 81,480; CC BY-NC-ND 10,568; CC BY-NC-SA 7,699; CC BY-SA 4,426; CC0 4,093. We therefore take arXiv papers only through OpenAlex (which attaches an author id and, via `has_orcid`, a disambiguation anchor) and fetch the PDF from arXiv under its research-use terms and rate limit.

## Licence policy adopted

Permitted: CC BY, BY-SA, BY-NC, BY-NC-SA, BY-ND, BY-NC-ND, CC0 and public domain (these allow reading and analysis; none of our use redistributes anything), plus arXiv papers under arXiv's research-use clause. **Excluded:** papers with no stated licence (most author-posted repository copies, including most PhilArchive-style postings), which costs yield on purpose. Only derived plain text is cached locally, in a git-ignored directory; manifests carry ids, hashes and word counts, not text.

## Limits of this check

* Terms were read from the live pages on 2026-11-11 and can change; re-check before a re-screen. Quotations above are verbatim.
* OpenAlex language tags are algorithmic: some non-English papers are tagged `en` (Afrikaans theology papers with English abstracts were seen). The fetch stage rejects them by a stopword test; the screen cannot.
* OpenAlex's `license` describes the located copy, not necessarily the publisher's terms for every use.
* PhilArchive / PhilPapers and Semantic Scholar were not usable from this network (Cloudflare challenge; shared-IP throttle), so their terms are unverified, not "found unsuitable".
* Not assessed: HathiTrust, JSTOR Open Content, Project MUSE open collections, institutional repositories outside OpenAlex's coverage.
