import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { memoryDraftStore } from '../drafts/store'
import { emptyDetails, type Draft } from '../drafts/types'
import i18n from '../i18n'
import { fakeServer, problem, SESSION } from '../test/fakeServer'
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

describe('a draft the server refused', () => {
  const stuck: Draft = {
    clientSubmissionId: 'c9',
    ownerId: SESSION.user.id,
    speakerId: 's1',
    speakerCode: 'SPK-SELF01',
    collectionMethod: 'self_recorded',
    kind: 'audio',
    recordingMode: 'free',
    audio: { blob: new Blob(['synthetic']), filename: 'long.webm', source: 'file_upload' },
    texts: [],
    details: { ...emptyDetails(), title: 'Long story' },
    uploadKey: 'k9',
    ready: true,
    progress: { submissionId: 'sub9' },
    lastError: 'too_large',
    needsChange: true,
    createdAt: '2026-10-12T00:00:00Z',
    updatedAt: '2026-10-12T00:00:00Z',
  }

  it('asks for a change, and reopens it as a new draft', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions\\?.*': () => ({ body: { items: [] } }),
      'POST /submissions/sub9/recordings': () => problem(413, 'too_large'),
    })
    const store = memoryDraftStore()
    await store.put(stuck)
    const { router } = renderApp('/submissions', store)

    expect(await screen.findByText('Needs a change')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Change' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Change' }))

    await waitFor(() => expect(router.state.location.pathname).not.toBe('/submissions'))
    const [copy] = await store.list()
    expect(copy?.clientSubmissionId).not.toBe('c9')
    expect(router.state.location.pathname).toBe(`/drafts/${copy?.clientSubmissionId}`)
    expect(copy).toMatchObject({ ready: false, progress: {}, details: { title: 'Long story' } })
    expect(copy?.uploadKey).not.toBe('k9')
    expect(copy?.audio).toBeDefined()
  })
})
