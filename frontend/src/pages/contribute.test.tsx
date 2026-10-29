import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { memoryDraftStore } from '../drafts/store'
import { emptyDetails, type Draft } from '../drafts/types'
import { fakeServer, SESSION, SPEAKER, type FakeRequest } from '../test/fakeServer'
import { renderApp } from '../test/render'
import { safeNext } from './ConsentPage'

const FORM = {
  id: 'f1',
  version: 'test-1',
  language: 'en',
  body_markdown: '# About the project\n\nThis is a **test** form.',
  is_test_form: true,
}

const next = (name = 'Next') => screen.getByRole('button', { name })

beforeEach(async () => {
  await i18n.changeLanguage('en')
  vi.stubGlobal(
    'URL',
    Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL() {} }),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('consent', () => {
  it('lists every use and saves them all with one I accept tick', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /speakers/s1': () => ({ body: { ...SPEAKER, has_active_consent: false } }),
      'GET /consent-forms/current.*': () => ({ body: FORM }),
      'POST /speakers/s1/consents': () => ({ status: 201, body: {} }),
      'GET /submissions.*': () => ({ body: { items: [] } }),
    })
    const { router } = renderApp('/speakers/s1/consent?next=/submissions')

    expect(await screen.findByText(/Test form/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'About the project' })).toBeInTheDocument()
    expect(screen.getByText(/Companies may use it/)).toBeInTheDocument()
    const accept = screen.getByRole('checkbox', { name: /I accept/ })
    expect(accept).not.toBeChecked()
    const save = screen.getByRole('button', { name: 'Save consent' })
    expect(save).toBeDisabled()

    await userEvent.click(accept)
    await userEvent.click(save)
    await waitFor(() => expect(router.state.location.pathname).toBe('/submissions'))

    const sent = requests.find((r) => r.method === 'POST')?.body as FormData
    expect(JSON.parse(String(sent.get('consent')))).toMatchObject({
      consent_form_id: 'f1',
      method: 'in_app',
      allow_store_and_review: true,
      allow_research: true,
      allow_public_access: true,
      allow_ai_training: true,
      allow_commercial_use: true,
      demographics_consented: true,
      attribution_preference: 'pseudonymous',
    })
  })
})

describe('consent for someone under 18', () => {
  it('does not ask for a parent or guardian', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /speakers/s1': () => ({ body: { ...SPEAKER, has_active_consent: false } }),
      'GET /consent-forms/current.*': () => ({ body: FORM }),
    })
    renderApp('/speakers/s1/consent?next=/submissions')
    await screen.findByRole('checkbox', { name: /I accept/ })
    expect(screen.queryByText(/under 18/)).not.toBeInTheDocument()
    expect(screen.queryByText(/guardian/)).not.toBeInTheDocument()
  })
})

describe('new recording', () => {
  it('makes the own speaker profile and asks for consent without asking whose voice', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /speakers\\?mine=true': () => ({ body: { items: [] } }),
      'POST /speakers': () => ({
        status: 201,
        body: { ...SPEAKER, has_active_consent: false },
      }),
      'GET /speakers/s1': () => ({ body: { ...SPEAKER, has_active_consent: false } }),
      'GET /consent-forms/current.*': () => ({ body: FORM }),
    })
    const { router } = renderApp('/contribute')

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/speakers/s1/consent'),
    )
    expect(router.state.location.search).toBe(
      `?next=${encodeURIComponent('/contribute/s1/new')}`,
    )
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({ for_self: true })
    expect(screen.queryByText(/Whose voice/)).not.toBeInTheDocument()
  })

  it('goes straight to the recording once consent is on file', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /speakers\\?mine=true': () => ({ body: { items: [SPEAKER] } }),
      'GET /speakers/s1': () => ({ body: SPEAKER }),
      'GET /submissions\\?.*': () => ({ body: { items: [] } }),
    })
    const { router } = renderApp('/contribute')
    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/contribute/s1/new'),
    )
  })
})

describe('new recording by a facilitator', () => {
  const FACILITATOR = { ...SESSION, roles: [{ role: 'facilitator', scope: null }] }

  it('asks whose voice it is, so they can record someone else', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: FACILITATOR }),
      'GET /speakers\\?mine=true': () => ({ body: { items: [SPEAKER] } }),
      'POST /speakers': () => ({
        status: 201,
        body: { ...SPEAKER, id: 's2', is_self: false, has_active_consent: false },
      }),
      'GET /speakers/s2': () => ({
        body: { ...SPEAKER, id: 's2', is_self: false, has_active_consent: false },
      }),
      'GET /consent-forms/current.*': () => ({ body: FORM }),
    })
    const { router } = renderApp('/contribute')

    await screen.findByRole('heading', { name: 'Whose voice or text is this?' })
    await userEvent.click(screen.getByRole('button', { name: /Someone else/ }))
    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/speakers/s2/consent'),
    )
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({ for_self: false })
  })

  it('can still record their own voice', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: FACILITATOR }),
      'GET /speakers\\?mine=true': () => ({ body: { items: [SPEAKER] } }),
      'GET /speakers/s1': () => ({ body: SPEAKER }),
      'GET /submissions\\?.*': () => ({ body: { items: [] } }),
    })
    const { router } = renderApp('/contribute')
    await userEvent.click(await screen.findByRole('button', { name: /Mine/ }))
    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/contribute/s1/new'),
    )
  })
})

describe('profile details', () => {
  it('fill in dialect and area for a new recording', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /speakers/s1': () => ({
        body: { ...SPEAKER, dialect_label: 'Hasada', region_coarse: 'Khunti' },
      }),
      'GET /submissions\\?.*': () => ({ body: { items: [] } }),
    })
    renderApp('/contribute/s1/new')
    await userEvent.click(await screen.findByRole('radio', { name: 'Text' }))
    await userEvent.click(next())
    await userEvent.type(screen.getByLabelText('Mundari text'), 'यह परीक्षण है')
    await userEvent.click(next())
    expect(screen.getByLabelText(/Dialect/)).toHaveValue('Hasada')
    expect(screen.getByLabelText(/^Area/)).toHaveValue('Khunti')
  })
})

describe('safeNext', () => {
  it('only returns to pages of this site', () => {
    expect(safeNext('/contribute/s1/new')).toBe('/contribute/s1/new')
    expect(safeNext('//evil.example/x')).toBe('/')
    expect(safeNext('https://evil.example')).toBe('/')
    expect(safeNext(null)).toBe('/')
  })
})

describe('contributing', () => {
  function server(extra: Record<string, (r: FakeRequest) => object> = {}) {
    return fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /speakers/s1': () => ({ body: SPEAKER }),
      'GET /submissions\\?.*': () => ({ body: { items: [] } }),
      ...extra,
    })
  }

  it('keeps an unfinished text on the phone without uploading it', async () => {
    const { requests } = server()
    const { store } = renderApp('/contribute/s1/new')

    await userEvent.click(await screen.findByRole('radio', { name: 'Text' }))
    await userEvent.click(next())
    expect(next()).toBeDisabled() // the text itself is required
    await userEvent.type(screen.getByLabelText('Mundari text'), 'यह परीक्षण है')
    await userEvent.type(screen.getByLabelText('English translation (optional)'), 'A test')
    await userEvent.click(next())
    await userEvent.type(screen.getByLabelText('Title (optional)'), 'Practice')
    await userEvent.click(next())
    expect(screen.getByText('A test')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save for later' }))

    expect(await screen.findByRole('heading', { name: 'My submissions' })).toBeInTheDocument()
    expect(screen.getByText('Practice')).toBeInTheDocument()
    expect(screen.getByText('Not finished')).toBeInTheDocument()
    const [saved] = await store.list()
    expect(saved).toMatchObject({ kind: 'text', ready: false, ownerId: 'u1' })
    expect(saved?.texts.map((text) => text.key)).toEqual(['main', 'translation-en'])
    expect(requests.some((r) => r.method === 'POST')).toBe(false)
  })

  it('uploads a recording from a file and lists it as sent', async () => {
    const sent = { id: 'sub1', kind: 'audio', status: 'processing', title: null }
    let submitted = false
    const { requests } = server({
      'POST /submissions': () => ({ status: 201, body: { id: 'sub1' } }),
      'POST /submissions/sub1/recordings': () => ({
        status: 202,
        body: { recording_id: 'rec1', upload_status: 'quarantined' },
      }),
      'POST /submissions/sub1/submit': () => {
        submitted = true
        return { body: sent }
      },
      'GET /submissions\\?.*': () => ({
        body: { items: submitted ? [{ ...sent, created_at: '2026-10-12T00:00:00Z' }] : [] },
      }),
    })
    const { store } = renderApp('/contribute/s1/new')

    await userEvent.click(await screen.findByRole('radio', { name: 'Audio' }))
    await userEvent.click(next())
    await userEvent.click(screen.getByRole('radio', { name: /Speak freely/ }))
    await userEvent.click(next())
    const file = new File(['synthetic'], 'test.webm', { type: 'audio/webm' })
    await userEvent.upload(screen.getByLabelText(/Choose an audio file/), file)
    expect(screen.getByText(/Recording ready/)).toBeInTheDocument()
    await userEvent.click(next()) // the transcription is optional
    await userEvent.click(next())
    await userEvent.click(next())
    // One more listen before sending.
    expect(screen.getByLabelText('Listen to the recording')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save and upload' }))

    expect(await screen.findByText('Being checked')).toBeInTheDocument()
    const upload = requests.find((r) => r.path.endsWith('/recordings'))
    expect(upload?.headers.get('Idempotency-Key')).toBeTruthy()
    expect((upload?.body as FormData).get('source')).toBe('file_upload')
    expect(await store.list()).toEqual([]) // nothing left on the phone once the server has it
  })

  it("does not show or upload another person's drafts on a shared phone", async () => {
    const { requests } = server()
    const store = memoryDraftStore()
    const theirs: Draft = {
      clientSubmissionId: 'c2',
      ownerId: 'someone-else',
      speakerId: 's9',
      speakerCode: 'SPK-OTHER1',
      collectionMethod: 'self_recorded',
      kind: 'text',
      texts: [
        {
          key: 'main',
          layerType: 'standalone',
          entryType: 'word',
          languageTag: 'unr',
          scriptCode: 'Deva',
          content: 'क',
        },
      ],
      details: { ...emptyDetails(), title: 'Not yours' },
      uploadKey: 'k2',
      ready: true,
      progress: {},
      createdAt: '2026-10-12T00:00:00Z',
      updatedAt: '2026-10-12T00:00:00Z',
    }
    await store.put(theirs)
    renderApp('/submissions', store)

    expect(await screen.findByText('Nothing sent yet.')).toBeInTheDocument()
    expect(screen.queryByText('Not yours')).not.toBeInTheDocument()
    expect(requests.some((r) => r.method === 'POST')).toBe(false)
  })
})
