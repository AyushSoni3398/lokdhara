import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, problem, SESSION } from '../test/fakeServer'
import { renderApp } from '../test/render'

const ADMIN = { ...SESSION, roles: [{ role: 'admin', scope: null }] }
const ITEM = {
  submission: {
    id: 'sub1',
    title: 'River story',
    kind: 'audio',
    content_type: 'story',
    status: 'accepted',
    restriction_flags: [],
    submitted_at: '2026-10-14T10:05:00Z',
  },
  reports: [
    {
      id: 'r1',
      submission_id: 'sub1',
      reason: 'third_party_voice',
      note: 'A neighbour talks at the end.',
      created_at: '2026-10-15T09:00:00Z',
    },
  ],
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('reports', () => {
  it('lets an admin hide a reported item with a reason', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /admin/reports': () => ({ body: { items: [ITEM] } }),
      'POST /admin/submissions/sub1/hide': () => ({ body: ITEM.submission }),
    })
    renderApp('/admin/reports')

    expect(await screen.findByText('River story')).toBeInTheDocument()
    expect(screen.getByText('A neighbour talks at the end.')).toBeInTheDocument()
    // The flag that matches the reason is picked already.
    expect(screen.getByLabelText('Hide because of')).toHaveValue('third_party_voice')
    const hide = screen.getByRole('button', { name: 'Hide' })
    expect(hide).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Your reason'), 'The neighbour did not agree.')
    await userEvent.click(hide)

    expect(await screen.findByText('No open reports.')).toBeInTheDocument()
    const post = requests.find((r) => r.method === 'POST')
    expect(post?.body).toEqual({
      restriction: 'third_party_voice',
      note: 'The neighbour did not agree.',
    })
  })

  it('dismisses reports and explains why an admin cannot decide on their own item', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /admin/reports': () => ({ body: { items: [ITEM] } }),
      'POST /admin/submissions/sub1/dismiss-reports': () => problem(403, 'own_submission'),
    })
    renderApp('/admin/reports')
    await userEvent.type(await screen.findByLabelText('Your reason'), 'It is fine.')
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss reports' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Another admin must decide')
    expect(screen.getByText('River story')).toBeInTheDocument()
  })

  it('is for admins only', async () => {
    fakeServer({ 'GET /auth/me': () => ({ body: SESSION }) })
    renderApp('/admin/reports')
    expect(await screen.findByText('Only admins can see this page.')).toBeInTheDocument()
  })
})
