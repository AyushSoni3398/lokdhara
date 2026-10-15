/**
 * A report, end to end against the real API: a contributor reports a problem with their own
 * sent item, an admin hides it, and the contributor sees that it was hidden (ROADMAP M6).
 * All text is synthetic Hindi or English.
 */
import { expect, test } from '@playwright/test'

import { newAccounts, sendTextItem, signIn } from './accounts'

test('a reported item is hidden by an admin and the contributor is told', async ({ page }) => {
  const { admin, contributor } = await newAccounts()
  const itemId = await sendTextItem(contributor, 'Report test')

  await signIn(page, contributor)
  await page.goto(`/submissions/${itemId}`)
  await page.getByRole('button', { name: 'Report a problem' }).click()
  await page.getByText(/personal information/).click()
  await page.getByLabel(/Anything an admin should know/).fill('A made-up phone number')
  await page.getByRole('button', { name: 'Send report' }).click()
  await expect(page.getByText('Thank you. An admin will look at it.')).toBeVisible()

  await signIn(page, admin)
  await page.getByRole('link', { name: /Reports/ }).click()
  const item = page.getByRole('listitem').filter({ hasText: 'Report test' })
  await expect(item.getByText('A made-up phone number')).toBeVisible()
  await item.getByLabel('Your reason').fill('Personal details are read out.')
  await item.getByRole('button', { name: 'Hide' }).click()
  await expect(page.getByText('Report test')).toHaveCount(0)

  await signIn(page, contributor)
  await page.goto(`/submissions/${itemId}`)
  await expect(
    page.getByText(/Hidden by an admin after a report: personal information/),
  ).toBeVisible()
})
