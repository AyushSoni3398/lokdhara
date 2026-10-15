/**
 * A dataset release, end to end against the real API and worker: a researcher drafts a release,
 * an admin freezes it, the researcher asks for a package, the admin approves, the worker builds
 * it and the researcher downloads it (ROADMAP M7). All text is synthetic.
 */
import { randomBytes } from 'node:crypto'

import { expect, test } from '@playwright/test'

import { invite, newAccounts, runWorker, sendTextItem, signIn } from './accounts'

test('a release is drafted, frozen, exported and downloaded', async ({ page }) => {
  const { admin, contributor } = await newAccounts()
  const researcher = await invite(admin, 'researcher', 'Test Researcher')
  await sendTextItem(contributor, 'Release test', { allow_research: true })
  runWorker() // the item's checks; it is accepted
  const slug = `e2e-release-${randomBytes(4).toString('hex')}`

  await signIn(page, researcher)
  await page.getByRole('link', { name: /Datasets/ }).click()
  await page.getByLabel(/Short name/).fill(slug)
  await page.getByRole('button', { name: 'Start draft' }).click()
  await expect(page.getByRole('heading', { name: slug })).toBeVisible()
  await expect(page.getByText(/\d+ items? ·/)).toBeVisible()
  await page.getByRole('button', { name: 'Run checks' }).click()
  await expect(page.getByText('D1', { exact: true })).toBeVisible()
  const releaseUrl = page.url()

  await signIn(page, admin)
  await page.goto(releaseUrl)
  await page.getByRole('button', { name: 'Freeze this release' }).click()
  await expect(page.getByRole('heading', { name: `${slug}@0.1.0` })).toBeVisible()

  await signIn(page, researcher)
  await page.goto(releaseUrl)
  await page.getByLabel('What will you use it for?').fill('A test of the export flow.')
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByRole('status')).toContainText('Request sent')

  await signIn(page, admin)
  await page.goto('/exports')
  const request = page.getByRole('listitem').filter({ hasText: `${slug}@0.1.0` })
  await request.getByRole('button', { name: 'Approve' }).click()
  await expect(request.getByText(/Approved, being prepared/)).toBeVisible()
  runWorker() // builds the package

  await signIn(page, researcher)
  await page.goto('/exports')
  const ready = page.getByRole('listitem').filter({ hasText: `${slug}@0.1.0` })
  await expect(ready.getByText(/Ready to download/)).toBeVisible()
  await ready.getByRole('button', { name: 'Get download link' }).click()
  const link = ready.getByRole('link', { name: `Save ${slug}-0.1.0.zip` })
  const zip = await page.request.get((await link.getAttribute('href')) ?? '')
  expect(zip.ok()).toBe(true)
  expect((await zip.body()).subarray(0, 2).toString()).toBe('PK')
})
