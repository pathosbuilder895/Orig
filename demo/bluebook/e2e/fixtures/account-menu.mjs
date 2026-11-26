/**
 * fixtures/account-menu.mjs: the shared top bar's account menu (AppBar.jsx).
 *
 * Account, Instructions, Text and Sign out live behind the account button
 * (#me-btn), the same place Original's pages keep them. Open it, then click
 * the item by its name; the menu closes itself when an item is chosen.
 */

export async function clickAccountMenuItem(page, name) {
  await page.locator('#me-btn').click()
  await page.locator('#me-menu').getByRole('button', { name, exact: true }).click()
}
