/**
 * A withdrawal, end to end against the real API: a contributor asks to take back one sent item,
 * an admin accepts, the worker deletes its text, and the request is closed (ROADMAP M7).
 * All text is synthetic Hindi or English.
 */
import { randomBytes } from 'node:crypto'

import { expect, test } from '@playwright/test'

import { newAccounts, runWorker, sendTextItem, signIn } from './accounts'

test('a contributor takes an item back and an admin carries it out', async ({ page }) => {
  const { admin, contributor } = await newAccounts()
  const itemId = await sendTextItem(contributor, 'Withdrawal test')
  // The queue is shared with earlier runs, so this request is found by its own note.
  const note = `Please remove it (${randomBytes(4).toString('hex')})`

  await signIn(page, contributor)
  await page.goto(`/submissions/${itemId}`)
  await page.getByRole('button', { name: 'Ask to take this back' }).click()
  await page.getByLabel(/Anything the admin should know/).fill(note)
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByText('Request sent. An admin will check it.')).toBeVisible()

  await signIn(page, admin)
  await page.getByRole('link', { name: /Withdrawal requests/ }).click()
  const request = page.getByRole('listitem').filter({ hasText: note })
  await request.getByLabel(/How you checked who asked/).fill('The contributor asked in the app.')
  page.once('dialog', (dialog) => void dialog.accept())
  await request.getByRole('button', { name: 'Accept and carry out' }).click()
  await expect(request.getByText('Hidden, being deleted')).toBeVisible()

  runWorker()
  await page.reload()
  await expect(request.getByText('Hidden and deleted')).toBeVisible()
  await request.getByLabel(/How you told the person/).fill('Shown as done in the app.')
  await request.getByRole('button', { name: 'Close request' }).click()
  await expect(page.getByText(note)).toHaveCount(0)

  await signIn(page, contributor)
  await page.goto(`/submissions/${itemId}`)
  // Only admins still see that a withdrawn item existed; its title and text are deleted.
  await expect(page.getByText(/This item could not be found/)).toBeVisible()
  await expect(page.getByText('यह एक परीक्षण वाक्य है।')).toHaveCount(0)
  await page.goto('/withdrawals')
  await expect(page.getByText('Done', { exact: true })).toBeVisible()
})
