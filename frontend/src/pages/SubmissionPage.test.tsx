import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, problem, SESSION } from '../test/fakeServer'
import { renderApp } from '../test/render'

const REVISION = {
  id: 'rev1',
  revision_number: 2,
  content: 'यह एक परीक्षण वाक्य है।',
  origin: 'human_contributor',
  based_on_revision_id: 'rev0',
  source_revision_id: null,
  detected_scripts: ['Deva'],
  uncertainty_markup: false,
  verification_status: 'unverified',
  change_note: null,
  created_at: '2026-10-15T10:00:00Z',
}

const LAYER = {
  id: 'l1',
  layer_type: 'transcription',
  recording_id: 'rec1',
  source_layer_id: null,
  entry_type: null,
  language_tag: 'unr',
  script_code: 'Deva',
  current_revision: REVISION,
  source_changed: false,
  script_mismatch: false,
}

const TRANSLATION = {
  ...LAYER,
  id: 'l2',
  layer_type: 'translation',
  recording_id: null,
  source_layer_id: 'l1',
  language_tag: 'en',
  script_code: 'Latn',
  current_revision: { ...REVISION, id: 'rev2', revision_number: 1, content: 'A test sentence.' },
  source_changed: true,
}

const DETAIL = {
  id: 'sub1',
  client_submission_id: 'c1',
  speaker_id: 'sp1',
  kind: 'audio_text',
  content_type: 'story',
  title: 'River story',
  status: 'accepted',
  restriction_flags: [],
  mine: true,
  recording_mode: 'free',
  created_at: '2026-10-14T10:00:00Z',
  submitted_at: '2026-10-14T10:05:00Z',
  recordings: [
    {
      id: 'rec1',
      upload_status: 'promoted',
      size_bytes: 1000,
      duration_ms: 3000,
      quality_flags: [],
      rejection_reason: null,
      created_at: '2026-10-14T10:01:00Z',
    },
  ],
  // The translation comes first here; the page shows it after its source.
  text_layers: [TRANSLATION, LAYER],
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('one submission', () => {
  it('shows the status, the recording, and each text after the one it translates', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: DETAIL }),
      'GET /recordings/rec1/playback': () => ({
        body: { sources: [{ url: '/files/rec1.webm', content_type: 'audio/webm' }] },
      }),
    })
    const { container } = renderApp('/submissions/sub1')

    expect(await screen.findByRole('heading', { name: 'River story' })).toBeInTheDocument()
    expect(screen.getByText('Accepted')).toBeInTheDocument()
    expect(await screen.findByLabelText('Recording')).toBeInTheDocument()
    expect(container.querySelector('source')?.getAttribute('type')).toBe('audio/webm')

    const items = screen.getAllByRole('listitem').map((item) => item.textContent ?? '')
    expect(items[0]).toContain('यह एक परीक्षण वाक्य है।')
    expect(items[0]).toContain('version 2')
    expect(items[1]).toContain('Translation (English)')
    expect(items[1]).toContain('The text this translates has changed since')
    expect(screen.getAllByText('Written by the contributor, not checked by anyone')).toHaveLength(2)
  })

  it('says why a file was refused and offers to record it again', async () => {
    const recording = {
      ...DETAIL.recordings[0],
      upload_status: 'rejected_invalid',
      rejection_reason: 'decode_errors',
    }
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({
        body: { ...DETAIL, status: 'rejected_invalid', recordings: [recording], text_layers: [] },
      }),
    })
    renderApp('/submissions/sub1')
    expect(await screen.findByText(/The file is damaged/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Record again' })).toHaveAttribute(
      'href',
      '/contribute/sp1/new',
    )
  })

  it('says when the recording is not ready to play yet', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: DETAIL }),
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
    })
    renderApp('/submissions/sub1')
    expect(
      await screen.findByText('The recording is still being prepared for listening.'),
    ).toBeInTheDocument()
  })

  it('lets the owner save the recording to their phone', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: DETAIL }),
      'GET /recordings/rec1/playback': () => ({
        body: { sources: [{ url: '/files/rec1.webm', content_type: 'audio/webm' }] },
      }),
    })
    renderApp('/submissions/sub1')
    const link = await screen.findByRole('link', { name: 'Download' })
    expect(link).toHaveAttribute('href', '/api/v1/recordings/rec1/download')
    expect(link).toHaveAttribute('download')
  })

  it.each([
    ['someone else', { mine: false }],
    ['hidden by an admin', { restriction_flags: ['contains_pii'] }],
  ])('offers no download when the item is %s', async (_, change) => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: { ...DETAIL, ...change } }),
      'GET /recordings/rec1/playback': () => ({
        body: { sources: [{ url: '/files/rec1.webm', content_type: 'audio/webm' }] },
      }),
    })
    renderApp('/submissions/sub1')
    expect(await screen.findByLabelText('Recording')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Download' })).not.toBeInTheDocument()
  })

  it('saves a correction as a new version on top of the one shown', async () => {
    const corrected = {
      ...LAYER,
      current_revision: { ...REVISION, id: 'rev3', revision_number: 3, content: 'नया वाक्य' },
    }
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: DETAIL }),
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
      'POST /text-layers/l1/revisions': () => ({ status: 201, body: corrected }),
    })
    renderApp('/submissions/sub1')
    const [first] = await screen.findAllByRole('listitem')
    await userEvent.click(within(first!).getByRole('button', { name: 'Correct' }))
    const box = within(first!).getByLabelText('Text')
    await userEvent.clear(box)
    await userEvent.type(box, 'नया वाक्य')
    await userEvent.click(within(first!).getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/version 3/)).toBeInTheDocument()
    const post = requests.find((r) => r.method === 'POST')
    expect(post?.body).toEqual({ base_revision_id: 'rev1', content: 'नया वाक्य' })
  })

  it('reloads when someone saved a newer version first', async () => {
    let loads = 0
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => {
        loads += 1
        return { body: DETAIL }
      },
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
      'POST /text-layers/l1/revisions': () => problem(409, 'revision_conflict'),
    })
    renderApp('/submissions/sub1')
    const [first] = await screen.findAllByRole('listitem')
    await userEvent.click(within(first!).getByRole('button', { name: 'Correct' }))
    await userEvent.type(within(first!).getByLabelText('Text'), ' और')
    await userEvent.click(within(first!).getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Someone saved a newer version')
    expect(loads).toBe(2)
  })

  it('adds a missing translation and warns about a script that does not match', async () => {
    const mismatched = { ...LAYER, script_mismatch: true }
    const detail = { ...DETAIL, text_layers: [mismatched] }
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: detail }),
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
      'POST /submissions/sub1/text-layers': () => ({ status: 201, body: TRANSLATION }),
    })
    renderApp('/submissions/sub1')

    expect(
      await screen.findByText(/does not use the script chosen for it \(Devanagari\)/),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add English translation' }))
    await userEvent.type(screen.getByLabelText('English translation'), 'A test sentence.')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await screen.findByRole('button', { name: 'Add English translation' })
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({
      layer_type: 'translation',
      source_layer_id: 'l1',
      language_tag: 'en',
      script_code: 'Latn',
      content: 'A test sentence.',
    })
  })

  it('offers no editing while a submission is still being checked', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: { ...DETAIL, status: 'processing' } }),
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
    })
    renderApp('/submissions/sub1')
    await screen.findByText('Being checked')
    expect(screen.queryByRole('button', { name: 'Correct' })).toBeNull()
  })

  it('lists earlier versions and shows what one changed', async () => {
    const older = { ...REVISION, id: 'rev0', revision_number: 1, based_on_revision_id: null }
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: { ...DETAIL, text_layers: [LAYER] } }),
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
      'GET /text-layers/l1/revisions': () => ({ body: { items: [REVISION, older] } }),
      'GET /text-revisions/rev0/diff/rev1': () => ({
        body: {
          parts: [
            { op: 'equal', text: 'यह ' },
            { op: 'delete', text: 'पुराना' },
            { op: 'insert', text: 'नया' },
          ],
        },
      }),
    })
    const { container } = renderApp('/submissions/sub1')
    await userEvent.click(await screen.findByRole('button', { name: 'Earlier versions' }))

    const history = await screen.findByRole('list', { name: 'Earlier versions' })
    expect(within(history).getAllByRole('listitem')).toHaveLength(2)
    await userEvent.click(within(history).getByRole('button', { name: 'What changed' }))
    expect(await within(history).findByText('नया')).toBeInTheDocument()
    expect(container.querySelector('ins')?.textContent).toBe('नया')
    expect(container.querySelector('del')?.textContent).toBe('पुराना')
  })

  it('reports a problem with a reason and an optional note', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: DETAIL }),
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
      'POST /submissions/sub1/reports': () => ({ status: 201, body: {} }),
    })
    renderApp('/submissions/sub1')
    await userEvent.click(await screen.findByRole('button', { name: 'Report a problem' }))
    const send = screen.getByRole('button', { name: 'Send report' })
    expect(send).toBeDisabled()
    await userEvent.click(screen.getByLabelText(/Someone else can be heard/))
    await userEvent.type(screen.getByLabelText(/Anything an admin should know/), 'A neighbour')
    await userEvent.click(send)

    expect(await screen.findByText('Thank you. An admin will look at it.')).toBeInTheDocument()
    const post = requests.find((r) => r.path === '/submissions/sub1/reports')
    expect(post?.body).toEqual({ reason: 'third_party_voice', note: 'A neighbour' })
  })

  it('says when the item was already reported', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: DETAIL }),
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
      'POST /submissions/sub1/reports': () => problem(409, 'already_reported'),
    })
    renderApp('/submissions/sub1')
    await userEvent.click(await screen.findByRole('button', { name: 'Report a problem' }))
    await userEvent.click(screen.getByLabelText(/not Mundari/))
    await userEvent.click(screen.getByRole('button', { name: 'Send report' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already reported this')
  })

  it('tells the contributor an admin hid their item', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({
        body: { ...DETAIL, restriction_flags: ['contains_pii'] },
      }),
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
    })
    renderApp('/submissions/sub1')
    expect(
      await screen.findByText(/Hidden by an admin after a report: personal information/),
    ).toBeInTheDocument()
  })

  it("shows other people's items read-only, with a way back to the catalogue", async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /submissions/sub1': () => ({ body: { ...DETAIL, mine: false } }),
      'GET /recordings/rec1/playback': () => ({ body: { sources: [] } }),
    })
    renderApp('/submissions/sub1')
    expect(await screen.findByRole('link', { name: '← Catalogue' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Correct' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Report a problem' })).toBeInTheDocument()
  })
})
