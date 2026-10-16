import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, problem, SESSION, SPEAKER } from '../test/fakeServer'
import type { Withdrawal } from '../api/types'
import { renderApp } from '../test/render'

const DETAIL = {
  id: 'sub1',
  client_submission_id: 'c1',
  kind: 'text',
  content_type: 'story',
  title: 'River story',
  status: 'accepted',
  restriction_flags: [],
  mine: true,
  recording_mode: null,
  created_at: '2026-10-14T10:00:00Z',
  submitted_at: '2026-10-14T10:05:00Z',
  recordings: [],
  text_layers: [],
}

const REQUEST: Withdrawal = {
  id: 'w1',
  speaker_id: 's1',
  speaker_code: 'SPK-7Q3M9A',
  submission_id: 'sub1',
  requested_scope: 'specific_items',
  received_via: 'in_app',
  received_at: '2026-10-16T09:00:00Z',
  status: 'received',
  note: null,
  verified_at: null,
  erased_at: null,
  completed_at: null,
  actions_taken: null,
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('taking recordings back', () => {
  it('asks for one item to be taken back from its page', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: DETAIL }),
      'POST /withdrawal-requests': () => ({ status: 201, body: REQUEST }),
    })
    renderApp('/submissions/sub1')

    await userEvent.click(await screen.findByRole('button', { name: 'Ask to take this back' }))
    // Before sending, the person learns what cannot be called back.
    expect(screen.getByText(/already downloaded cannot be deleted/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Anything the admin should know/), 'Wrong person.')
    await userEvent.click(screen.getByRole('button', { name: 'Send request' }))

    expect(await screen.findByText('Request sent. An admin will check it.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Your requests' })).toHaveAttribute(
      'href',
      '/withdrawals',
    )
    const post = requests.find((r) => r.method === 'POST')
    expect(post?.body).toEqual({
      scope: 'specific_items',
      submission_id: 'sub1',
      note: 'Wrong person.',
    })
  })

  it('says when the same request is already waiting', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: DETAIL }),
      'POST /withdrawal-requests': () => problem(409, 'already_requested'),
    })
    renderApp('/submissions/sub1')

    await userEvent.click(await screen.findByRole('button', { name: 'Ask to take this back' }))
    await userEvent.click(screen.getByRole('button', { name: 'Send request' }))
    expect(
      await screen.findByText('A request for this is already waiting for an admin.'),
    ).toBeInTheDocument()
  })

  it('offers nothing to take back on a withdrawn item', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({
        body: { ...DETAIL, status: 'withdrawn' },
      }),
    })
    renderApp('/submissions/sub1')

    expect(await screen.findByRole('heading', { name: 'River story' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ask to take this back' })).toBeNull()
  })

  it('lists requests in plain words and takes back everything of a speaker', async () => {
    let mine: Withdrawal[] = [
      { ...REQUEST, status: 'verified', verified_at: '2026-10-16T10:00:00Z' },
      {
        ...REQUEST,
        id: 'w0',
        requested_scope: 'narrow',
        submission_id: null,
        status: 'rejected',
        completed_at: '2026-10-15T10:00:00Z',
      },
    ]
    const full: Withdrawal = {
      ...REQUEST,
      id: 'w2',
      requested_scope: 'full',
      submission_id: null,
    }
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /speakers\\?mine=true': () => ({ body: { items: [SPEAKER] } }),
      'GET /withdrawal-requests': () => ({ body: { items: mine } }),
      'POST /withdrawal-requests': () => {
        mine = [full, ...mine]
        return { status: 201, body: full }
      },
    })
    renderApp('/withdrawals')

    expect(await screen.findByText('Hidden, being deleted')).toBeInTheDocument()
    expect(screen.getByText('Not carried out')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /change what they may be used for/ })).toHaveAttribute(
      'href',
      '/speakers/s1/consent',
    )

    await userEvent.click(screen.getByRole('button', { name: 'Take back everything from you' }))
    await userEvent.click(screen.getByRole('button', { name: 'Send request' }))

    expect(await screen.findByText('Waiting for an admin')).toBeInTheDocument()
    expect(screen.getByText('Everything')).toBeInTheDocument()
    const post = requests.find((r) => r.method === 'POST')
    expect(post?.body).toEqual({ scope: 'full', speaker_id: 's1' })
  })
})
