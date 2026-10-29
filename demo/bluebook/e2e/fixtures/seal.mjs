// The seal asks "Ready to submit?" in the booklet's own dialog (Exam.jsx),
// not the browser's: answer it the way a student does.
export async function confirmSeal(page) {
  await page.getByRole('dialog', { name: 'Ready to submit?' })
    .getByRole('button', { name: 'Seal and submit' }).click()
}
