/**
 * Prepares the local API for a browser test: migrations, the test consent forms and prompts
 * (`seed-dev`), and a fresh contributor invited by a fresh admin. Every run uses new random
 * accounts, so it can repeat against the same development database.
 */
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { fileURLToPath } from 'node:url'

import { expect, request, type Page } from '@playwright/test'

const BACKEND = fileURLToPath(new URL('../../backend', import.meta.url))
const API = 'http://localhost:8000/api/v1/'

function backend(args: string[], input?: string) {
  // Output is discarded: seed-dev prints the passwords of the development accounts.
  execFileSync('uv', ['run', ...args], {
    cwd: BACKEND,
    input,
    stdio: ['pipe', 'ignore', 'inherit'],
  })
}

export interface Account {
  username: string
  password: string
}

const secret = () => randomBytes(12).toString('hex')

export async function newContributor(): Promise<Account> {
  return (await newAccounts()).contributor
}

/** Runs the jobs that are due (checks of sent items, export packages), then returns. */
export function runWorker() {
  backend(['python', '-m', 'app.worker', '--until-idle'])
}

async function signedIn(account: Account) {
  const api = await request.newContext({ baseURL: API })
  const login = await api.post('auth/login', { data: account })
  expect(login.ok()).toBe(true)
  const headers = { 'X-CSRF-Token': (await login.json()).csrf_token as string }
  return { api, headers }
}

/** A new account with `role`, invited by `admin`. */
export async function invite(admin: Account, role: string, name: string): Promise<Account> {
  const { api, headers } = await signedIn(admin)
  const invitation = await api.post('auth/invitations', { data: { role }, headers })
  expect(invitation.ok()).toBe(true)
  const token = new URL((await invitation.json()).invite_url).hash.slice(1)
  await api.dispose()

  const anonymous = await request.newContext({ baseURL: API })
  const account = { username: `e2e-${role}-${randomBytes(4).toString('hex')}`, password: secret() }
  const accepted = await anonymous.post('auth/invitations/accept', {
    data: { token, ...account, display_name: name, locale: 'hi' },
  })
  expect(accepted.ok()).toBe(true)
  await anonymous.dispose()
  return account
}

/**
 * Sends a text-only item through the API as the contributor, for their own speaker, with the
 * consent answers in `uses` (for example allow_research). Returns the item's id.
 */
export async function sendTextItem(
  contributor: Account,
  title: string,
  uses: Record<string, boolean> = {},
): Promise<string> {
  const { api, headers } = await signedIn(contributor)
  const speaker = await (await api.post('speakers', { data: { for_self: true }, headers })).json()
  const form = await (await api.get('consent-forms/current?language=hi')).json()
  const consent = await api.post(`speakers/${speaker.id}/consents`, {
    multipart: {
      consent: JSON.stringify({
        consent_form_id: form.id,
        method: 'in_app',
        allow_store_and_review: true,
        ...uses,
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
        title,
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

/** A fresh admin and a contributor they invited. */
export async function newAccounts(): Promise<{ admin: Account; contributor: Account }> {
  backend(['alembic', 'upgrade', 'head'])
  backend(['python', '-m', 'app.cli', 'seed-dev'])

  const run = randomBytes(4).toString('hex')
  const admin = { username: `e2e-admin-${run}`, password: secret() }
  backend(
    [
      'python',
      '-m',
      'app.cli',
      'create-admin',
      '--username',
      admin.username,
      '--display-name',
      'E2E Admin',
      '--password-stdin',
    ],
    `${admin.password}\n`,
  )

  const contributor = await invite(admin, 'contributor', 'Test Contributor')
  return { admin, contributor }
}

/** Signs in through the login page, in English. */
export async function signIn(page: Page, account: Account) {
  await page.context().clearCookies()
  await page.goto('/login')
  await page.getByRole('button', { name: 'English' }).click()
  await page.getByLabel('Username').fill(account.username)
  await page.getByLabel('Password').fill(account.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText(/Welcome/)).toBeVisible()
}
