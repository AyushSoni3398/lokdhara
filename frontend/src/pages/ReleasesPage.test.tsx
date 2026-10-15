import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, problem, SESSION } from '../test/fakeServer'
import { renderApp } from '../test/render'

const RESEARCHER = { ...SESSION, roles: [{ role: 'researcher', scope: null }] }
const ADMIN = { ...SESSION, roles: [{ role: 'admin', scope: null }] }
const CRITERIA = {
  kinds: [],
  content_types: [],
  recording_modes: [],
  dialect_labels: [],
  needs_audio: false,
  needs_transcription: false,
}
const DRAFT = {
  id: 'rel1',
  slug: 'mundari-speech-pilot',
  version: null,
  purpose: 'internal_research',
  selection_criteria: CRITERIA,
  status: 'draft',
  licence: null,
  data_card_markdown: '',
  manifest_sha256: null,
  created_at: '2026-10-15T09:00:00Z',
  updated_at: '2026-10-15T09:00:00Z',
  frozen_at: null,
  retracted_at: null,
  retraction_note: null,
}
const FROZEN = {
  ...DRAFT,
  version: '0.1.0',
  status: 'frozen',
  manifest_sha256: 'a'.repeat(64),
  frozen_at: '2026-10-15T10:00:00Z',
  updated_at: '2026-10-15T10:00:00Z',
}
const PREVIEW = {
  item_count: 2,
  total_duration_ms: 42000,
  left_out_count: 1,
  by_content_type: { song: 1, story: 1 },
  by_dialect_label: {},
  by_kind: {},
  sample: [],
}
const CHECKS = {
  passed: true,
  checks: [
    { code: 'D1', passed: true, blocking: true, message: '2 accepted items' },
    { code: 'D9', passed: false, blocking: false, message: '1 speakers are above the share limit' },
  ],
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('dataset releases', () => {
  it('lists releases and starts a draft', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: RESEARCHER }),
      'GET /datasets': () => ({ body: { items: [FROZEN] } }),
      'POST /datasets': () => ({ status: 201, body: DRAFT }),
      'GET /datasets/rel1': () => ({ body: DRAFT }),
      'GET /datasets/rel1/preview': () => ({ body: PREVIEW }),
    })
    const { router } = renderApp('/datasets')

    expect(await screen.findByText('mundari-speech-pilot@0.1.0')).toBeInTheDocument()
    const start = screen.getByRole('button', { name: 'Start draft' })
    await userEvent.type(screen.getByLabelText(/Short name/), 'Mundari Pilot')
    expect(start).toBeDisabled() // spaces are not allowed
    await userEvent.clear(screen.getByLabelText(/Short name/))
    await userEvent.type(screen.getByLabelText(/Short name/), 'mundari-speech-pilot')
    await userEvent.click(start)

    expect(await screen.findByText('2 items · 42 seconds')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/datasets/rel1')
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({
      slug: 'mundari-speech-pilot',
      purpose: 'internal_research',
    })
    // Researchers cannot freeze.
    expect(screen.queryByRole('button', { name: 'Freeze this release' })).toBeNull()
  })

  it('saves the selection, runs the checks and lets an admin freeze', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /datasets/rel1': () => ({ body: DRAFT }),
      'GET /datasets/rel1/preview': () => ({ body: PREVIEW }),
      'PATCH /datasets/rel1': (request) => ({
        body: { ...DRAFT, ...(request.body as object), updated_at: '2026-10-15T09:30:00Z' },
      }),
      'POST /datasets/rel1/checks': () => ({ body: CHECKS }),
      'POST /datasets/rel1/freeze': () => ({ body: FROZEN }),
    })
    renderApp('/datasets/rel1')

    await userEvent.click(await screen.findByRole('checkbox', { name: 'Song' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    const patch = requests.find((r) => r.method === 'PATCH')
    expect((patch?.body as { selection_criteria: object }).selection_criteria).toEqual({
      ...CRITERIA,
      content_types: ['song'],
    })

    await userEvent.click(await screen.findByRole('button', { name: 'Run checks' }))
    expect(await screen.findByText('2 accepted items')).toBeInTheDocument()
    expect(screen.getByText('1 speakers are above the share limit')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Freeze this release' }))
    expect(await screen.findByText('mundari-speech-pilot@0.1.0')).toBeInTheDocument()
    expect(requests.find((r) => r.path.endsWith('/freeze'))?.body).toEqual({ version: '0.1.0' })
  })

  it('explains a failed freeze', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /datasets/rel1': () => ({ body: DRAFT }),
      'GET /datasets/rel1/preview': () => ({ body: { ...PREVIEW, item_count: 0 } }),
      'POST /datasets/rel1/freeze': () => problem(422, 'prefreeze_checks_failed'),
    })
    renderApp('/datasets/rel1')
    await userEvent.click(await screen.findByRole('button', { name: 'Freeze this release' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('did not pass its checks')
  })

  it('asks for an export of a frozen release, and admins retract with a note', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: ADMIN }),
      'GET /datasets/rel1': () => ({ body: FROZEN }),
      'POST /datasets/rel1/exports': () => ({ status: 201, body: {} }),
      'POST /datasets/rel1/retract': (request) => ({
        body: {
          ...FROZEN,
          status: 'retracted',
          retracted_at: '2026-10-16T08:00:00Z',
          retraction_note: (request.body as { note: string }).note,
        },
      }),
    })
    renderApp('/datasets/rel1')

    const send = await screen.findByRole('button', { name: 'Send request' })
    expect(send).toBeDisabled()
    await userEvent.type(screen.getByLabelText('What will you use it for?'), 'A thesis chapter.')
    await userEvent.click(send)
    expect(await screen.findByRole('status')).toHaveTextContent('Request sent')
    expect(requests.find((r) => r.path.endsWith('/exports'))?.body).toEqual({
      purpose_statement: 'A thesis chapter.',
    })

    await userEvent.type(screen.getByLabelText('Your reason'), 'A consent concern.')
    await userEvent.click(screen.getByRole('button', { name: 'Retract this release' }))
    expect(await screen.findByText('A consent concern.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Send request' })).toBeNull()
  })

  it('is not for contributors', async () => {
    fakeServer({ 'GET /auth/me': () => ({ body: SESSION }) })
    renderApp('/datasets')
    expect(
      await screen.findByText('Only researchers and admins can see the catalogue.'),
    ).toBeInTheDocument()
  })
})
