# Prompts and pieces for the alpha

## Current since 2026-11: four past papers, no exam, no prompt

Volunteers are given **no prompt and no exam**. Each shares four past papers they wrote themselves under **Share a past paper**; that is the whole volunteer task. Students see the same steps in the app under **Instructions** (`demo/bluebook/instructions.jsx`, `ALPHA_STEPS`). No volunteer is ever asked to use an AI tool.

The pieces scored for calibration are made on Andrew's side (`setup_runbook.md` §6):
- **Held-out paper** (`natural`): one of the four, left *Waiting for approval* and read with **Read this paper**. Its own topic is its `prompt_id` (for example `own-<student folder>-heldout`).
- **Andrew's imitation** (`shadow`, `shadow_kind=ai_staff`): one piece Andrew writes in the volunteer's voice with an AI writing tool, using one or more of the three approved papers as the only style source (never the held-out paper). Staff instruction, for Andrew only:

> Using only [the approved paper(s) you choose] by [VOLUNTEER] as the style source, ask [GENERATOR TOOL] to write about 300–400 words in that person's voice, on a topic of your choosing (the held-out paper's topic gives a same-topic pair). Don't paste in the held-out paper or anyone else's writing. Record `writer_true` = Andrew, `generator_tool`, `shadow_source_paper_id` (the paper(s) used), the volunteer as `author_true`/`imitated_student_id`, and, if it is on the held-out paper's topic, the held-out paper as `paired_submission_id`.

Only for volunteers whose consent covers a staff-made imitation (the current consent Q10, or Yes to Q12 on a form answered before 2026-11; see `consent_form_questions.md`). How to label both is in `scoring_plan.md`.

---

# Superseded 2026-11: the two-question alpha exam (2026-10-30 to 2026-11, kept for submissions already made)

One collection, two questions, one submission per student, titled `Alpha test: your piece and an AI piece`. Question 1 held the volunteer's own piece; question 2 held an AI-written piece on the same topic. It is no longer created or sent, and its volunteer-facing question text has been retired (see this file's git history before 2026-11 if an old submission needs to be read against it). Labels for submissions already sealed: question 1 is `natural`, question 2 is `shadow`, `shadow_kind=ai_own`, same topic. The batch scorer splits them into `<submission_id>-q1` and `-q2`; how to label each is in `scoring_plan.md`. Give both halves one `prompt_id` per volunteer (for example `own-<student folder>`).

---

# Superseded 2026-10-30: two timed writings per volunteer (kept for submissions already made)

Exams A and B below were the design until 2026-10-30. They are no longer created or sent; this section stays so any submission already labelled with these `prompt_id`s can still be read against its prompt.

Both exams: 25 minutes, **Block copy & paste: ON**, "No AI assistants" ON, no hard word limit, spell check allowed. Writing consistency: OFF (see the runbook). Each exam allows one submission per student. Async: each volunteer does Exam A and Exam B when they can; once a timed writing is started, its own timer runs. Do A before B.

## Exam A: natural paper (write as yourself)
**Prompt 1 (prompt_id `night-market`): The Night Market.** A city has a market that opens only between midnight and dawn and sells things that can't be bought anywhere else. Describe one stall, its keeper and one customer. What is being bought, and what does it cost?

Label: `natural`. `author_true` = the writer.

## Exam B: shadow paper, current course-ready version (write as your partner)
Before writing, every volunteer is paired with an assigned partner who has **agreed** to let them read 1–2 of their uploaded past papers and imitate their style. Andrew shares those excerpts privately. The pairs swap, and the person being imitated must have ticked the consent box.

**Prompt 2 (prompt_id `letter-2076`): The Letter from 2076, written in your partner's voice.** You receive a letter from a stranger living fifty years in the future who says they found your name in an old library. Write the reply **as your partner would write it**: their sentence length, their word choices, their habits. Don't copy their sentences.

Label: `shadow`, `shadow_kind=human_partner`. `author_true`/`imitated_student_id` = the partner being imitated; `writer_true` = the volunteer actually writing. Note: A and B use **different prompts**, so record `prompt_id` for both and do not describe A/B as a same-prompt pair in calibration.

## Spare prompt (if someone must redo one)
**Prompt 3 (prompt_id `island-rulebook`): The Island Rulebook.** Twenty strangers are stranded on a small island with enough food for a month. Write the first five rules and argue for each one, then name one rule you decided against and why.

## Proposed paired-shadow wording — NEEDS ANDREW'S APPROVAL before use
Current A/B changes the prompt and the writer at the same time, so prompt differences can look like style differences. The cleaner calibration design is: genuine and shadow answer the **same prompt**. If Andrew approves, replace Exam B's prompt with this exact wording (the volunteer-facing text):

> **Write in [ASSIGNED PARTNER]'s voice, on the same prompt they answered.** You have been shown **one** sample paper by [ASSIGNED PARTNER] (and no other writing by them). Answer this prompt: "A city has a market that opens only between midnight and dawn and sells things that can't be bought anywhere else. Describe one stall, its keeper and one customer. What is being bought, and what does it cost?" Write as [ASSIGNED PARTNER] would write it — their sentence length, word choices and habits — without copying their sentences. Aim for **300–400 words** in the 25 minutes. You must not write your own shadow: the person being imitated never writes or generates the shadow of themselves.

Staff/AI shadow variant (also needs Andrew's approval; generated by staff/Andrew, **not** by a volunteer pasting their own or a partner's work into a tool):

> Staff instruction: using **one** sample paper by [TARGET STUDENT] as the only style source, ask [GENERATOR TOOL] to answer prompt `night-market` (exact text above) in that student's voice, 300–400 words. Record `shadow_kind=ai_staff`, `generator_tool`, `shadow_source_paper_id`, the target as `author_true`/`imitated_student_id`, the staff operator as `writer_true`, and the target's genuine `night-market` submission as `paired_submission_id`. The target student is not involved in generating it.

These proposals were not adopted before the design changed on 2026-10-30. The 2026-10-30 exam's question 2 then gave a same-topic pair by construction; since 2026-11 Andrew's imitation on the held-out paper's topic does.
