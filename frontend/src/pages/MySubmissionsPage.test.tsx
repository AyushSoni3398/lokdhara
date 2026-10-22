import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, SESSION } from '../test/fakeServer'
import { renderApp } from '../test/render'

const SENT = {
  id: 'sub1',
  client_submission_id: 'c1',
  kind: 'audio',
  content_type: 'story',
  title: 'River story',
  status: 'accepted',
  restriction_flags: [],
  recording_mode: 'free',
  created_at: '2026-10-14T10:00:00Z',
  submitted_at: '2026-10-14T10:05:00Z',
}

function show(items: object[]) {
  fakeServer({
    'GET /auth/me': () => ({ body: SESSION }),
    'GET /submissions\\?.*': () => ({ body: { items } }),
  })
  renderApp('/submissions')
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('downloading everything I sent', () => {
  it('offers one zip once a recording has been accepted', async () => {
    show([SENT])
    const link = await screen.findByRole('link', { name: 'Download all my recordings' })
    expect(link).toHaveAttribute('href', '/api/v1/me/recordings.zip')
    expect(link).toHaveAttribute('download')
  })

  it.each([
    ['only text was sent', { kind: 'text' }],
    ['the recording is still being checked', { status: 'processing' }],
    ['an admin hid it', { restriction_flags: ['minor'] }],
  ])('offers nothing when %s', async (_, change) => {
    show([{ ...SENT, ...change }])
    expect(await screen.findByText('River story')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Download all my recordings' })).toBeNull()
  })
})
