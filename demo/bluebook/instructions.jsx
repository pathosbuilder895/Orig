import React, { useId, useRef } from 'react';
import { BB_API } from './components.jsx';
import { REFERENCE_WRITING_LINE } from './Exam.jsx';
import './instructions.css';

// The short instructions, one guide for teachers and one for students. The
// "Instructions" button sits in each navigation bar, so the guide can be
// reopened from any screen at any time. Each step names the button or page
// it refers to exactly as the app labels it.

export const TEACHER_STEPS = [
  ['Make a course', 'Go to Courses and create one for each class you teach.'],
  ['Add your students', 'Open the course and add their email addresses, or turn on its sign-up link and share it. Each student then sets a password.'],
  ['Set a collection', 'Go to Collections and choose + New collection. Write the question, choose the course, then Publish Collection. Students find it under My exams.'],
  ['Watch it live', 'Optional. Proctor shows who has started, the minutes left and who has submitted.'],
  ['Read, mark and release', 'Open the collection to read each sealed booklet and add a mark and feedback. Choose Release results when students may see them. Export CSV keeps a copy.'],
];

export const TEACHER_NOTES = [
  'Drafts save on the student’s device as they write. A booklet reaches you once they seal it.',
  'Collections keeps the text and a few session facts: time spent, word count, paste attempts and times the window lost focus. Never the screen, camera or keystrokes. The facts are context, not evidence.',
];

// NORTH_STAR rule 10: wherever Original is on, it is labelled as in testing.
export const TEACHER_ORIGINAL_NOTE = 'Original is in its testing phase and is not validated on real student writing. Only booklets you approve become reference writing, and you can undo that.';

export const STUDENT_STEPS = [
  ['Find your exam', 'It appears under My exams once your teacher opens it.'],
  ['Begin', 'Read the briefing, then choose Begin Examination. The clock starts then and keeps running, even if you close the page.'],
  ['Write', 'Your work saves itself on this device as you write. If the page closes, open the exam again on the same device and choose Resume Examination.'],
  ['Seal & Submit', 'Choose Seal & Submit when you are done. A sealed booklet cannot be changed.'],
  ['See your results', 'Your mark and feedback appear under My exams once your teacher releases them.'],
];

export const STUDENT_NOTES = [
  'Collections keeps your writing and a few facts about the session: time spent, word count, paste attempts and times you left the window. Never your screen, camera or keystrokes.',
];

// During the alpha pilot every student is an alpha tester, so students get
// the alpha test's steps instead of the guide above. The alpha exam has two
// questions and leaves copy and paste on. Only where the workspace holds
// Original, as the alpha workspace does: elsewhere there is no Share a past
// paper section for step 1 to point to. Set this to false when the alpha
// closes.
export const SHOW_ALPHA_GUIDE = true;

export const ALPHA_STEPS = [
  ['Share three past papers', 'On your home page, under Share a past paper, send three papers you wrote yourself, one at a time: a PDF, Word or text file, or pasted text.'],
  ['Get two pieces ready', 'Choose another piece of your own writing, not one of those three. Then ask an AI tool, such as ChatGPT or Claude, to write about the same topic. Give it the topic only, not your writing.'],
  ['Open the exam', 'Under Examinations, choose Open, then Begin Examination.'],
  ['Paste them in', 'Paste your own piece into question 1 (Q1) and the AI’s piece into question 2 (Q2).'],
  ['Seal & Submit', 'Choose Seal & Submit when both answers are in. A sealed booklet cannot be changed.'],
];

export const ALPHA_NOTES = [
  'Note which AI tool you used. The feedback form asks for its name.',
  'Remove anything private, such as names, grades or health details, before you share or paste.',
  'You will not see a score or any reading of your writing. This tests the software, not you.',
];

export function instructionsFor(who, hasOriginal, alpha = SHOW_ALPHA_GUIDE) {
  if (who === 'student' && alpha && hasOriginal) {
    return { title: 'Alpha test: what to do', steps: ALPHA_STEPS, notes: ALPHA_NOTES };
  }
  if (who === 'student') {
    return {
      title: 'Taking an exam',
      steps: STUDENT_STEPS,
      notes: hasOriginal ? [...STUDENT_NOTES, REFERENCE_WRITING_LINE] : STUDENT_NOTES,
    };
  }
  return {
    title: 'Using Collections',
    steps: TEACHER_STEPS,
    notes: hasOriginal ? [...TEACHER_NOTES, TEACHER_ORIGINAL_NOTE] : TEACHER_NOTES,
  };
}

// The nav button and the guide it opens. A native modal <dialog>: Escape
// closes it, focus stays inside while it is open, and a click on the dimmed
// backdrop (the dialog element itself, outside .bb-howto-card) closes it too.
export function InstructionsButton({ who = 'teacher', className }) {
  const dialog = useRef(null);
  const titleId = useId();
  const guide = instructionsFor(who, BB_API.hasOriginal());
  const open = () => {
    const d = dialog.current;
    if (d && !d.open) d.showModal();
  };
  const close = () => { if (dialog.current) dialog.current.close(); };
  return <>
    <button type="button" className={className} aria-haspopup="dialog" onClick={open}>Instructions</button>
    <dialog ref={dialog} className="bb-howto" aria-labelledby={titleId} onClick={e => { if (e.target === e.currentTarget) close(); }}>
      <div className="bb-howto-card">
        <div className="bb-howto-head">
          <h2 id={titleId}>{guide.title}</h2>
          <button type="button" className="bb-howto-close" onClick={close}>Close</button>
        </div>
        <ol className="bb-howto-steps">
          {guide.steps.map(([step, text]) => <li key={step}><strong>{step}.</strong> {text}</li>)}
        </ol>
        <h3>Good to know</h3>
        <ul className="bb-howto-notes">
          {guide.notes.map(note => <li key={note}>{note}</li>)}
        </ul>
        <p className="bb-howto-foot">Reopen these any time from Instructions at the top of the page.</p>
      </div>
    </dialog>
  </>;
}
