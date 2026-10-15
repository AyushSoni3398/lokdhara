/**
 * Prepares the local API for a browser test: migrations, the test consent forms and prompts
 * (`seed-dev`), and a fresh contributor invited by a fresh admin. Every run uses new random
 * accounts, so it can repeat against the same development database.
 */
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { fileURLToPath } from 'node:url'

import { expect, request } from '@playwright/test'

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

  const api = await request.newContext({ baseURL: API })
  const login = await api.post('auth/login', { data: admin })
  expect(login.ok()).toBe(true)
  const { csrf_token } = await login.json()
  const invitation = await api.post('auth/invitations', {
    data: { role: 'contributor' },
    headers: { 'X-CSRF-Token': csrf_token },
  })
  expect(invitation.ok()).toBe(true)
  const token = new URL((await invitation.json()).invite_url).hash.slice(1)

  const contributor = { username: `e2e-contributor-${run}`, password: secret() }
  const accepted = await api.post('auth/invitations/accept', {
    data: { token, ...contributor, display_name: 'Test Contributor', locale: 'hi' },
  })
  expect(accepted.ok()).toBe(true)
  await api.dispose()
  return { admin, contributor }
}
