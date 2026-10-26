# Ready-to-send invite message (DRAFT — Andrew approves and sends)

Subject: Help test a new writing app? (adults 18+, about an hour total, whenever suits you)

Hi [FIRST NAME],

I'm inviting a small group of adults to help test **Original**, a writing app I'm developing, before it's used with real classes. This is a calibration test of the software — it checks the app, not you. There are no grades and no conclusions will be drawn about anyone's writing.

**Who can take part:** adults aged 18 or older who are happy to do the steps below.

**What I'd need from you, in order:**

1. **Consent form first** (5 minutes): [CONSENT FORM LINK]. It explains what's collected — including that standard web logs record IP address and browser type — and that your data is deleted within 14 days after you withdraw or Andrew closes your participation, whichever comes first (encrypted backups age out within about 30 days after that).
2. **Your past writing:** at least **3 past papers you wrote yourself** (300+ words in total). Once you've joined, upload them under **Share a past paper** on your Collections home page (PDF, DOCX or TXT, or paste the text). If that doesn't work for you, email them to me at arclark555@gmail.com instead. Please remove anything private (names, grades, health details) first. I review each paper before it's used, and you'll only see whether it was accepted. If you don't have 3 separate papers, **one long paper is fine** — with your permission it can be split into sections to use as reference writing (when uploading a section, tick "This is a section of a longer paper"), and those split pieces are labelled as split-derived in the test data.
3. **Two short timed writings** (25 minutes each, copy & paste blocked), done whenever suits you after I send your personal join link: one in your own voice, and one trying to write in an assigned partner's voice (they'll have agreed to share a sample, and you'll do the same for them if you agree). Your link is personal — please don't share it: **[JOIN LINK]**
4. A short feedback form afterwards.

**Optional extra — Exam C (only if you'd like to; skipping it changes nothing):** after your two writings, you can do one more short step. Take a piece of **your own** writing (for example, your first timed writing or one of your past papers), ask a writing tool of your choice to rewrite it, and paste the rewritten version into the Exam C link I'll send you. Please tell me which tool you used (just its name). Only use your own writing for this, never anyone else's. This helps me see how the app handles a rewritten version of someone's own work; like everything else here, it isn't a judgement of you and the results won't be shown to you or anyone else as one.

The two writings help me calibrate how the app compares a new piece of writing with someone's earlier writing. It's a new feature still in testing, the results won't be shown to you or anyone else as a judgement, and staff only look at grouped results after the writings are in.

\[Staff note, not part of the message: record each Exam C paper in `labels.csv` as `label=shadow`, `shadow_kind=ai_own`, `author_true`/`imitated_student_id`/`writer_true` = the volunteer, `generator_tool` = the tool they named, `paired_submission_id` = the source paper. The Exam C session must allow pasting. The batch scorer counts `ai_own` in the headline catch rate by default; run it with `--primary-shadow-kinds human_partner,ai_staff,injected_other,public_domain` to keep Exam C as its own category, out of the Exam B shadow rates. This wording needs Andrew's approval before it is sent.\]

You can stop at any time, for any reason, and ask for early deletion — contact me at **arclark555@gmail.com**.

Thank you,
Andrew
