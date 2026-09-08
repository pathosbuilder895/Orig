# NCD authorship channel — proposed fresh-lock pre-registration

Status: **awaiting explicit human sign-off; do not run**.

The PAN 2020 locked results for `compression_ncd` have already been observed and are
therefore ineligible for confirmation. This registration freezes a new study before
any candidate reads its hold-out: the official English PAN 2023 cross-discourse-type
authorship-verification release, which is not present in this checkout. Fetching,
partitioning, or inspecting that release for this study is prohibited until the human
approves this document.

## Frozen protocol

- Reuse `validation.verify.pan_stack_compression` without changing the base signals,
  zlib implementation, 16,000-character cap, or NCD formula.
- Recover author histories only from official truth author IDs. Exclude authors that
  cannot supply three baseline and three probe documents in disjoint discourse types.
- Order eligible author IDs by SHA-256 of `pan23-ncd-v1:<raw-author-id>`. Allocate the
  first 120 to fusion development, next 20 to fusion calibration, next 20 to threshold
  calibration, and next 40 to the single locked evaluation. No author or document may
  cross partitions. If fewer than 200 authors qualify, the result is
  `uninformative`; do not shrink or reshuffle the lock.
- Fit both arms on identical development trials: `base` and `base + compression_ncd`.
  Select no additional hyperparameters. Open the locked metrics exactly once.
- Record archive DOI, archive checksum, derived-manifest hash, code commit,
  `PYTHONHASHSEED=0`, trial counts, abstention, AUC, Brier, Cllr, and transferred
  threshold rates in the result artifact.

## Gate (all three required)

1. Cllr strictly improves (`ncd < base`).
2. AUC improvement is at least +0.005.
3. Recall at the threshold calibrated for a 1% FPR does not regress, and the locked
   FPR is reported beside it (never relabel a 1.77% observation as “at 1%”).

Zero engagement or fewer than 36 genuine locked trials is `uninformative`, never a
pass. The raw self-entropy signal remains excluded. The prior PAN 2020 movement
(AUC +0.0359, Cllr −0.1207) is motivation only and must not be used as a bar or a
comparison lock.

## Decision after the one run

A pass licenses only an implementation proposal for a default-off, report-only
expert; it does not license production enablement. A fail or uninformative result is
committed unchanged and ends this registration. Any protocol alteration requires a
new corpus and a new signed registration.

Human approval: ____________________  Date: __________
