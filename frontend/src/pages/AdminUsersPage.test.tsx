import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { fakeServer, SESSION } from '../test/fakeServer'
import { renderApp } from '../test/render'

const ADMIN = { ...SESSION, roles: [{ role: 'admin', scope: null }] }
const ASHA = {
  id: 'u2',
  username: 'asha',
  display_name: 'Asha',
  status: 'active',
  roles: [{ role: 'contributor', scope: null }],
  created_at: '2026-10-23T00:00:00Z',
  last_login_at: null,
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('people and accounts', () => {
  it('finds an account and shows its reset link once', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /admin/users\\?q=ash': () => ({ body: { items: [ASHA] } }),
      'POST /admin/users/u2/password-reset': () => ({
        status: 201,
        body: { reset_url: 'https://x/reset-password#tok', expires_at: '2026-10-24T00:00:00Z' },
      }),
    })
    renderApp('/admin/users')
    await userEvent.type(await screen.findByLabelText('Username or name'), 'ash')
    await userEvent.click(screen.getByRole('button', { name: 'Find' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Make reset link' }))
    expect(await screen.findByDisplayValue('https://x/reset-password#tok')).toBeInTheDocument()
    expect(requests.filter((r) => r.method === 'POST')).toHaveLength(1)
  })

  it('makes an invitation for a staff role', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'POST /auth/invitations': () => ({
        status: 201,
        body: { invite_url: 'https://x/invite#tok', expires_at: '2026-10-26T00:00:00Z' },
      }),
    })
    renderApp('/admin/users')
    await userEvent.selectOptions(await screen.findByLabelText('Role'), 'researcher')
    await userEvent.click(screen.getByRole('button', { name: 'Make invitation link' }))
    expect(await screen.findByDisplayValue('https://x/invite#tok')).toBeInTheDocument()
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({ role: 'researcher' })
  })

  it('is for admins only', async () => {
    fakeServer({ 'GET /auth/me': () => ({ body: SESSION }) })
    renderApp('/admin/users')
    expect(await screen.findByText(/admin/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Find' })).not.toBeInTheDocument()
  })
})
