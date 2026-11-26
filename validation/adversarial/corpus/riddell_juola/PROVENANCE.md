# Provenance — Riddell-Juola adversarial-stylometry corpus

## Source

- **Paper:** Wang, Juola & Riddell, "Reproduction and Replication of an
  Adversarial Stylometry Experiment."
- **Zenodo record:** https://zenodo.org/records/18729526 (title:
  "Reproducibility package for..." the above paper)
- **DOI:** `10.5281/zenodo.18729526`
- **Bundle file:** `rr_bundle.zip`, 2427488 bytes
- **Download URL used:**
  `https://zenodo.org/api/records/18729526/files/rr_bundle.zip/content`
- **MD5 verified at retrieval:** `3b4dbe6edde117d80a0f5e764f594d53` — matched
  exactly; see `validation/adversarial/fetch_riddell_juola.py:verify_integrity`,
  which refuses to extract on a mismatch.

## License

CC0 1.0 Universal. Per the bundle's own `DATA_LICENSE` file: "Riddell–Juola
corpus, metadata.csv, and MTurk study materials in this archive are released
under CC0 1.0 Universal."

## Retrieval

- **Retrieved:** 2026-09-21
- **Retrieved by:** `validation/adversarial/fetch_riddell_juola.py`
  (`main()` — download, MD5-verify, extract)

## What was extracted

Three human-written "attack condition" splits, one `.txt` file per
participant, flattened out of the bundle's
`rr_bundle/resource/defending-against-authorship-attribution-corpus/corpus/`
directory (the `attacks_<condition>/` nesting was dropped — filenames are
the original `<6-char-hex-id>.txt` participant ids, unchanged):

| Split         | Bundle folder         | Files extracted |
|---------------|------------------------|-----------------|
| `control`     | `attacks_control/`     | 21              |
| `obfuscation` | `attacks_obfuscation/` | 27              |
| `imitation`   | `attacks_imitation/`   | 18              |

`control` is the no-instruction condition ("describe your neighborhood," no
adversarial instruction). `obfuscation` and `imitation` are the two
adversarial-stylometry attack conditions studied in the paper.

File counts were verified against the live bundle at retrieval time and
matched the brief's expected 21/27/18 exactly — no drift from the bundle
described in the task brief.

## Participant baselines (added 2026-10-21)

The bundle also contains, at
`rr_bundle/resource/defending-against-authorship-attribution-corpus/corpus/<hex_id>/`,
each participant's PRE-EXISTING writing from before the study, in chunks
(e.g. `corpus/58473c/58473c_02.txt` ... `58473c_13.txt`). The original study
built its stylometric models from these. Task 16 left them out; the SP1
harness needs them to score an attack essay as verification, against the
participant's own earlier writing, so they were extracted on 2026-10-21 with
the owner's approval.

- **Where:** `baselines/<hex_id>/<hex_id>_NN.txt`, filenames unchanged from
  the bundle.
- **Who:** only participants in one of the three committed splits: 65 of
  the 66. `cfeec8` (imitation split) has no prior-writing directory in the
  bundle.
- **How much:** 856 chunks, 2,621,580 bytes; 5 to 25 chunks per participant
  (median 13), 86 to 889 words per chunk (median 525).
- **Retrieved:** 2026-10-21 by `fetch_riddell_juola.py`
  (`extract_participant_baselines`), from the same download URL; size
  2427488 bytes and MD5 `3b4dbe6edde117d80a0f5e764f594d53` verified again
  before extraction. Re-extracting the three splits in the same run
  reproduced the committed files byte for byte.
- **License:** CC0 1.0, as above (the bundle's `DATA_LICENSE` covers the
  whole Riddell-Juola corpus).

## Not extracted

`metadata.csv` (per-participant demographics: `id,gender,age,duration,date,
plagiarism_detected,notes`, no condition column — condition is determined
purely by which `attacks_*` folder a participant's file is in) was also not
copied alongside the extracted text. It isn't needed to satisfy this task's
loader requirement (three text splits only) and demographic data has no use
in this repo's offline stylometry harness; it can be pulled from the
original bundle again if a future task needs it.

## Loader

`load_riddell_juola_split(name)` and `load_riddell_juola_split_by_id(name)`
in `validation/adversarial/fetch_riddell_juola.py` read the committed splits
back off disk, and `load_riddell_juola_baselines()` the participant
baselines (see that module's docstring for why the loaders live there rather
than in a separate module). Tested by `tests/adversarial/test_riddell_juola.py`
and `tests/adversarial/test_report.py`.
