"""Strip Gutenberg boilerplate/HTML from the downloaded raw corpus and chunk into
~700-word submission-sized samples, tagged by author/work/genre bucket.
Research script only -- not part of the Original codebase.
"""
import html
import json
import re
from pathlib import Path

RAW = Path(__file__).parent / "raw"
CLEAN = Path(__file__).parent / "clean"
CLEAN.mkdir(exist_ok=True)

# (raw filename, author, work title, genre bucket)
MANIFEST = [
    ("lewis_lion_witch_wardrobe.html", "lewis", "The Lion, the Witch and the Wardrobe", "narnia"),
    ("lewis_prince_caspian.html", "lewis", "Prince Caspian", "narnia"),
    ("lewis_voyage_dawn_treader.html", "lewis", "The Voyage of the Dawn Treader", "narnia"),
    ("lewis_out_of_silent_planet.html", "lewis", "Out of the Silent Planet", "space_trilogy"),
    ("lewis_perelandra.html", "lewis", "Perelandra", "space_trilogy"),
    ("lewis_hideous_strength.html", "lewis", "That Hideous Strength", "space_trilogy"),
    ("lewis_problem_of_pain.html", "lewis", "The Problem of Pain", "theology"),
    ("lewis_letters_to_malcolm.html", "lewis", "Letters to Malcolm", "theology"),
    ("lewis_grief_observed.html", "lewis", "A Grief Observed", "memoir"),
    ("lewis_surprised_by_joy.html", "lewis", "Surprised by Joy", "memoir"),
    ("lewis_on_stories.html", "lewis", "On Stories", "essays"),
    ("lewis_transposition.html", "lewis", "Transposition and Other Addresses", "essays"),
    ("lewis_screwtape_letters.html", "lewis", "The Screwtape Letters", "satire"),
    ("chesterton_orthodoxy.txt", "chesterton", "Orthodoxy", "impostor_theology"),
    ("chesterton_heretics.txt", "chesterton", "Heretics", "impostor_essays"),
    ("chesterton_all_things_considered.txt", "chesterton", "All Things Considered", "impostor_essays"),
    ("chesterton_wisdom_father_brown.txt", "chesterton", "The Wisdom of Father Brown", "impostor_fiction"),
]

GUTENBERG_CA_START_MARKER = re.compile(r"Project Gutenberg Canada ebook #\s*\d+", re.I)
BRACKET_NOTE = re.compile(r"\[(Transcriber|Producer)[^\]]*\]", re.I)
GUTENBERG_CA_END_MARKER = re.compile(r"\[End of .*?\]", re.I | re.S)
CHAPTER_HEADING = re.compile(r"\b(CHAPTER|LETTER)\s+[IVXLC0-9]+\b")

GUTENBERG_ORG_START = re.compile(r"\*\*\*\s*START OF THE PROJECT GUTENBERG EBOOK.*?\*\*\*", re.I | re.S)
GUTENBERG_ORG_END = re.compile(r"\*\*\*\s*END OF THE PROJECT GUTENBERG EBOOK", re.I)


def strip_html(raw_text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_text, flags=re.S | re.I)
    # keep paragraph boundaries before stripping tags
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return text


def clean_gutenberg_ca_html(raw_text: str) -> str:
    text = strip_html(raw_text)
    m = GUTENBERG_CA_START_MARKER.search(text)
    if m:
        text = text[m.end():]
    text = BRACKET_NOTE.sub(" ", text)
    # skip past any leading CONTENTS listing straight to the first chapter/letter heading
    m = CHAPTER_HEADING.search(text)
    if m and m.start() < 6000:
        text = text[m.start():]
    m = GUTENBERG_CA_END_MARKER.search(text)
    if m:
        text = text[: m.start()]
    return text


def clean_gutenberg_org_txt(raw_text: str) -> str:
    text = raw_text
    m = GUTENBERG_ORG_START.search(text)
    if m:
        text = text[m.end():]
    m = GUTENBERG_ORG_END.search(text)
    if m:
        text = text[: m.start()]
    return text


def normalize_paragraphs(text: str) -> list[str]:
    # collapse intra-paragraph whitespace but keep paragraph breaks
    paras = re.split(r"\n\s*\n", text)
    out = []
    for p in paras:
        p = re.sub(r"\s+", " ", p).strip()
        if len(p.split()) >= 15:  # drop headings/short fragments
            out.append(p)
    return out


def chunk_paragraphs(paras: list[str], target_words: int = 700) -> list[str]:
    chunks = []
    cur: list[str] = []
    cur_words = 0
    for p in paras:
        n = len(p.split())
        if cur_words + n > target_words and cur:
            chunks.append(" ".join(cur))
            cur, cur_words = [], 0
        cur.append(p)
        cur_words += n
    if cur and cur_words >= target_words * 0.4:
        chunks.append(" ".join(cur))
    elif cur and chunks:
        chunks[-1] = chunks[-1] + " " + " ".join(cur)
    return chunks


def main():
    records = []
    for fname, author, work, genre in MANIFEST:
        path = RAW / fname
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        if fname.endswith(".html"):
            text = clean_gutenberg_ca_html(raw_text)
        else:
            text = clean_gutenberg_org_txt(raw_text)
        paras = normalize_paragraphs(text)
        chunks = chunk_paragraphs(paras)
        # front matter (producer notes, table of contents, book-list ads) reliably
        # leaks into the first chunk regardless of format -- drop it rather than
        # hand-tune a parser per front-matter style
        if len(chunks) > 1:
            chunks = chunks[1:]
        slug = fname.rsplit(".", 1)[0]
        (CLEAN / f"{slug}.txt").write_text("\n\n".join(chunks), encoding="utf-8")
        for i, ch in enumerate(chunks):
            records.append({
                "author": author,
                "work": work,
                "genre": genre,
                "chunk_id": f"{slug}_{i:03d}",
                "word_count": len(ch.split()),
                "text": ch,
            })
        print(f"{fname:45s} -> {len(chunks):3d} chunks, {len(text.split()):6d} words total")

    out_path = Path(__file__).parent / "chunks.json"
    out_path.write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"\nWrote {len(records)} chunks to {out_path}")


if __name__ == "__main__":
    main()
