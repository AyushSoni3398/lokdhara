/**
 * A report, end to end against the real API: a contributor reports a problem with their own
 * sent item, an admin hides it, and the contributor sees that it was hidden (ROADMAP M6).
 * All text is synthetic Hindi or English.
 */
import { expect, request, test, type Page } from '@playwright/test'

import { type Account, newAccounts } from './accounts'

const API = 'http://localhost:8000/api/v1/'

/** Sends a text-only item through the API, as the contributor, and returns its id. */
async function sendTextItem(contributor: Account): Promise<string> {
  const api = await request.newContext({ baseURL: API })
  const login = await api.post('auth/login', { data: contributor })
  const headers = { 'X-CSRF-Token': (await login.json()).csrf_token }
  const speaker = await (await api.post('speakers', { data: { for_self: true }, headers })).json()
  const form = await (await api.get('consent-forms/current?language=hi')).json()
  const consent = await api.post(`speakers/${speaker.id}/consents`, {
    multipart: {
      consent: JSON.stringify({
        consent_form_id: form.id,
        method: 'in_app',
        allow_store_and_review: true,
      }),
    },
    headers,
  })
  expect(consent.ok()).toBe(true)
  const draft = await (
    await api.post('submissions', {
      data: {
        client_submission_id: crypto.randomUUID(),
        speaker_id: speaker.id,
        kind: 'text',
        content_type: 'story',
        collection_method: 'self_recorded',
        title: 'Report test',
      },
      headers,
    })
  ).json()
  const layer = await api.post(`submissions/${draft.id}/text-layers`, {
    data: {
      layer_type: 'standalone',
      entry_type: 'sentence',
      language_tag: 'unr',
      script_code: 'Deva',
      content: 'यह एक परीक्षण वाक्य है।',
    },
    headers,
  })
  expect(layer.ok()).toBe(true)
  expect((await api.post(`submissions/${draft.id}/submit`, { headers })).ok()).toBe(true)
  await api.dispose()
  return draft.id
}

async function signIn(page: Page, account: Account) {
  await page.context().clearCookies()
  await page.goto('/login')
  await page.getByRole('button', { name: 'English' }).click()
  await page.getByLabel('Username').fill(account.username)
  await page.getByLabel('Password').fill(account.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText(/Welcome/)).toBeVisible()
}

test('a reported item is hidden by an admin and the contributor is told', async ({ page }) => {
  const { admin, contributor } = await newAccounts()
  const itemId = await sendTextItem(contributor)

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
