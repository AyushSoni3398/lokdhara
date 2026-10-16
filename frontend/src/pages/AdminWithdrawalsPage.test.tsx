import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Withdrawal } from '../api/types'
import i18n from '../i18n'
import { fakeServer, problem, SESSION, SPEAKER } from '../test/fakeServer'
import { renderApp } from '../test/render'

const ADMIN = { ...SESSION, roles: [{ role: 'admin', scope: null }] }
const REQUEST: Withdrawal = {
  id: 'w1',
  speaker_id: 's1',
  speaker_code: 'SPK-7Q3M9A',
  submission_id: null,
  requested_scope: 'full',
  received_via: 'phone',
  received_at: '2026-10-16T09:00:00Z',
  status: 'received',
  note: 'Called the office.',
  verified_at: null,
  erased_at: null,
  completed_at: null,
  actions_taken: [],
}
const VERIFIED: Withdrawal = {
  ...REQUEST,
  status: 'verified',
  verified_at: '2026-10-16T10:00:00Z',
  actions_taken: [{ action: 'verified', at: '2026-10-16T10:00:00Z', note: 'Called back.' }],
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

describe('withdrawal requests for admins', () => {
  it('accepts a request after asking once more, with how the requester was checked', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /admin/withdrawal-requests\\?open=true': () => ({ body: { items: [REQUEST] } }),
      'POST /admin/withdrawal-requests/w1/verify': () => ({ body: VERIFIED }),
    })
    renderApp('/admin/withdrawals')

    expect(await screen.findByText('Called the office.')).toBeInTheDocument()
    expect(screen.getByText(/by phone/)).toBeInTheDocument()
    const accept = screen.getByRole('button', { name: 'Accept and carry out' })
    expect(accept).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/How you checked who asked/), 'Called back.')
    await userEvent.click(accept)

    expect(window.confirm).toHaveBeenCalled()
    expect(await screen.findByText('Hidden, being deleted')).toBeInTheDocument()
    expect(screen.getByText(/Accepted/)).toBeInTheDocument()
    // Closing waits until the files are gone.
    expect(screen.queryByRole('button', { name: 'Close request' })).toBeNull()
    const post = requests.find((r) => r.method === 'POST')
    expect(post?.body).toEqual({ note: 'Called back.' })
  })

  it('closes a request once its files are deleted', async () => {
    const erased = { ...VERIFIED, erased_at: '2026-10-16T10:01:00Z' }
    const closed = { ...erased, status: 'completed' as const, completed_at: '2026-10-16T11:00:00Z' }
    fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /admin/withdrawal-requests\\?open=true': () => ({ body: { items: [erased] } }),
      'POST /admin/withdrawal-requests/w1/complete': () => ({ body: closed }),
    })
    renderApp('/admin/withdrawals')

    expect(await screen.findByText('Hidden and deleted')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/How you told the person/), 'Told them by phone.')
    await userEvent.click(screen.getByRole('button', { name: 'Close request' }))
    expect(await screen.findByText('No requests.')).toBeInTheDocument()
  })

  it('points to the consent page for fewer uses and explains a refused accept', async () => {
    const narrow = { ...REQUEST, requested_scope: 'narrow' as const }
    fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /admin/withdrawal-requests\\?open=true': () => ({ body: { items: [narrow] } }),
      'POST /admin/withdrawal-requests/w1/verify': () => problem(409, 'consent_not_changed'),
    })
    renderApp('/admin/withdrawals')

    expect(await screen.findByRole('link', { name: 'consent page' })).toHaveAttribute(
      'href',
      '/speakers/s1/consent',
    )
    await userEvent.type(screen.getByLabelText(/How you checked who asked/), 'In person.')
    await userEvent.click(screen.getByRole('button', { name: 'Accept and carry out' }))
    // Fewer uses deletes nothing, so there is no extra question.
    expect(window.confirm).not.toHaveBeenCalled()
    expect(
      await screen.findByText("Record the speaker's new consent first, then accept the request."),
    ).toBeInTheDocument()
  })

  it('logs a request that came through a facilitator', async () => {
    const logged = { ...REQUEST, received_via: 'facilitator' as const, note: null }
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /admin/withdrawal-requests\\?open=true': () => ({ body: { items: [] } }),
      'GET /speakers\\?mine=false': () => ({
        body: {
          items: [SPEAKER, { ...SPEAKER, id: 's2', speaker_code: 'SPK-GONE', status: 'withdrawn' }],
        },
      }),
      'POST /withdrawal-requests': () => ({ status: 201, body: logged }),
    })
    renderApp('/admin/withdrawals')

    await userEvent.click(await screen.findByRole('button', { name: 'Log a request' }))
    const speaker = screen.getByLabelText('Speaker')
    await screen.findByRole('option', { name: 'SPK-7Q3M9A' })
    // Someone who already withdrew is not offered again.
    expect(screen.queryByRole('option', { name: 'SPK-GONE' })).toBeNull()
    await userEvent.selectOptions(speaker, 's1')
    await userEvent.click(screen.getByRole('button', { name: 'Log request' }))

    expect(await screen.findByText('Waiting for an admin')).toBeInTheDocument()
    const post = requests.find((r) => r.method === 'POST')
    expect(post?.body).toEqual({ scope: 'full', speaker_id: 's1', received_via: 'facilitator' })
  })

  it('is only for admins', async () => {
    fakeServer({ 'GET /auth/me': () => ({ body: SESSION }) })
    renderApp('/admin/withdrawals')
    expect(await screen.findByText('Only admins can see this page.')).toBeInTheDocument()
  })
})
