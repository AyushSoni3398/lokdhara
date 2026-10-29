/**
 * A contributor's recording, end to end against the real API: sign in, consent, record with
 * the browser's fake microphone, add text, and upload, also across a lost connection.
 * All text is synthetic Hindi or English.
 */
import { expect, test, type Page } from '@playwright/test'

import { newContributor } from './accounts'

/** Signs a new contributor in and gives consent for their own voice. */
async function startAsNewContributor(page: Page) {
  const contributor = await newContributor()
  await page.goto('/')
  await page.getByRole('button', { name: 'English' }).click()
  await page.getByLabel('Username').fill(contributor.username)
  await page.getByLabel('Password').fill(contributor.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Welcome, Test Contributor')).toBeVisible()

  await page.getByRole('link', { name: /New recording/ }).click()

  // Consent before anything is recorded; every answer starts as No.
  await expect(page.getByText(/Test form/)).toBeVisible()
  const save = page.getByRole('button', { name: 'Save consent' })
  await expect(save).toBeDisabled()
  await page
    .getByRole('group', { name: /keep the recording safely/ })
    .getByText('Yes')
    .click()
  await save.click()
}

async function record(page: Page) {
  await page.getByRole('button', { name: /Start recording/ }).click()
  await expect(page.getByRole('status')).toContainText('0:02', { timeout: 10_000 })
  await page.getByRole('button', { name: 'Stop' }).click()
  await expect(page.getByText(/Recording ready/)).toBeVisible()
}

const next = (page: Page) => page.getByRole('button', { name: 'Next' }).click()

test('a contributor records, consents, and uploads', async ({ page }) => {
  await startAsNewContributor(page)
  await page.getByText('Audio and text').click()
  await next(page)
  await page.getByText('Speak freely').click()
  await next(page)
  await record(page)
  await next(page)

  await page.getByLabel('What is said').fill('यह एक परीक्षण है')
  await page.getByLabel('English translation (optional)').fill('This is a test')
  await next(page)
  await page.getByLabel('Title (optional)').fill('Browser test')
  await next(page)

  await expect(page.getByText('This is a test')).toBeVisible()
  await page.getByRole('button', { name: 'Save and upload' }).click()

  // Uploaded and handed to the checks: nothing is left waiting on the phone.
  await expect(page.getByRole('heading', { name: 'My submissions' })).toBeVisible()
  await expect(page.getByText('Being checked')).toBeVisible()
  await expect(page.getByText('Browser test')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'On this phone' })).toHaveCount(0)
})

test('a recording made offline uploads when the connection comes back', async ({
  page,
  context,
}) => {
  await startAsNewContributor(page)
  await page.getByText('Audio', { exact: true }).click()
  await next(page)
  await page.getByText('Speak freely').click()
  await next(page)
  await record(page)
  await next(page)
  await next(page) // the transcription is optional
  await page.getByLabel('Title (optional)').fill('Offline test')
  await next(page)

  await context.setOffline(true)
  await page.getByRole('button', { name: 'Save and upload' }).click()
  await expect(page.getByRole('heading', { name: 'On this phone' })).toBeVisible()
  await expect(page.getByText('Offline test')).toBeVisible()
  await expect(page.getByText(/No connection/).first()).toBeVisible()

  await context.setOffline(false)
  await expect(page.getByText('Being checked')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'On this phone' })).toHaveCount(0)
})
