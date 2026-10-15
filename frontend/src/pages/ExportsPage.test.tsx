import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, problem, SESSION } from '../test/fakeServer'
import { renderApp } from '../test/render'

const RESEARCHER = { ...SESSION, roles: [{ role: 'researcher', scope: null }] }
const ADMIN = { ...SESSION, roles: [{ role: 'admin', scope: null }] }
const REQUEST = {
  id: 'exp1',
  release_id: 'rel1',
  release_slug: 'mundari-speech-pilot',
  release_version: '0.1.0',
  requested_by_name: 'Kiran',
  mine: false,
  purpose_statement: 'A keyword-spotting baseline.',
  status: 'requested',
  decision_note: null,
  decided_at: null,
  created_at: '2026-10-15T09:00:00Z',
  ready_at: null,
  expires_at: null,
  sha256: null,
  size_bytes: null,
  download_count: 0,
}
const READY = {
  ...REQUEST,
  mine: true,
  status: 'ready',
  ready_at: '2026-10-15T10:00:00Z',
  expires_at: '2026-10-22T10:00:00Z',
  sha256: 'b'.repeat(64),
  size_bytes: 2048,
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('export requests', () => {
  it('lets an admin approve someone else’s request', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /exports': () => ({ body: { items: [REQUEST] } }),
      'POST /admin/exports/exp1/approve': () => ({ body: { ...REQUEST, status: 'approved' } }),
    })
    renderApp('/exports')

    expect(await screen.findByText('A keyword-spotting baseline.')).toBeInTheDocument()
    expect(screen.getByText(/asked by Kiran/)).toBeInTheDocument()
    // Rejecting needs a reason; approving does not.
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(await screen.findByText(/Approved, being prepared/)).toBeInTheDocument()
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({})
  })

  it('explains why an admin cannot approve their own request', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /exports': () => ({ body: { items: [REQUEST] } }),
      'POST /admin/exports/exp1/approve': () => problem(403, 'own_request'),
    })
    renderApp('/exports')
    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Another admin must decide')
  })

  it('gives the requester a download link with the checksum', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: RESEARCHER }),
      'GET /exports': () => ({ body: { items: [READY] } }),
      'POST /exports/exp1/download': () => ({
        body: {
          download_url: 'https://storage.example/exports/exp1.zip?sig=x',
          file_name: 'mundari-speech-pilot-0.1.0.zip',
          sha256: 'b'.repeat(64),
          size_bytes: 2048,
          expires_at: '2026-10-22T10:00:00Z',
        },
      }),
    })
    renderApp('/exports')

    expect(await screen.findByText(/downloaded 0 times/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Get download link' }))
    const link = await screen.findByRole('link', { name: 'Save mundari-speech-pilot-0.1.0.zip' })
    expect(link).toHaveAttribute('href', 'https://storage.example/exports/exp1.zip?sig=x')
    expect(screen.getByText('b'.repeat(64))).toBeInTheDocument()
    expect(screen.getByText(/downloaded 1 time$/)).toBeInTheDocument()
  })
})
