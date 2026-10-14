import { describe, expect, it, vi } from 'vitest'

import { ApiError, NetworkError } from '../api/client'
import { memoryDraftStore } from './store'
import { submissionBody, syncDraft, type SyncApi } from './sync'
import { emptyDetails, type Draft } from './types'

function draft(overrides: Partial<Draft> = {}): Draft {
  return {
    clientSubmissionId: 'c1',
    ownerId: 'u1',
    speakerId: 's1',
    speakerCode: 'SPK-7Q3M9A',
    collectionMethod: 'self_recorded',
    kind: 'audio_text',
    recordingMode: 'free',
    audio: { blob: new Blob(['synthetic']), filename: 'rec.webm', source: 'browser_recorder' },
    texts: [
      {
        key: 'en',
        layerType: 'translation',
        languageTag: 'en',
        scriptCode: 'Latn',
        content: 'A test.',
        translatesKey: 'main',
      },
      {
        key: 'main',
        layerType: 'transcription',
        languageTag: 'unr',
        scriptCode: 'Deva',
        content: 'परीक्षण',
      },
    ],
    details: emptyDetails(),
    uploadKey: 'k1',
    ready: true,
    progress: {},
    createdAt: '2026-10-12T00:00:00Z',
    updatedAt: '2026-10-12T00:00:00Z',
    ...overrides,
  }
}

function fakeApi(): SyncApi & { [K in keyof SyncApi]: ReturnType<typeof vi.fn> } {
  let layer = 0
  return {
    createSubmission: vi.fn(async () => ({ id: 'sub1' })),
    uploadRecording: vi.fn(async () => ({ recording_id: 'rec1', upload_status: 'quarantined' })),
    createTextLayer: vi.fn(async () => ({ id: `layer${++layer}` })),
    getSubmission: vi.fn(async () => ({ id: 'sub1', text_layers: [] })),
    submitSubmission: vi.fn(async () => ({ id: 'sub1', status: 'processing' })),
  } as never
}

describe('syncDraft', () => {
  it('sends the draft in order and then forgets it', async () => {
    const store = memoryDraftStore()
    const api = fakeApi()
    await store.put(draft())

    await syncDraft(draft(), store, api)

    expect(api.uploadRecording).toHaveBeenCalledWith(
      'sub1',
      expect.any(Blob),
      'rec.webm',
      'browser_recorder',
      'k1',
    )
    const [first, second] = api.createTextLayer.mock.calls.map((call) => call[1])
    expect(first).toMatchObject({ layer_type: 'transcription', recording_id: 'rec1' })
    expect(second).toMatchObject({ layer_type: 'translation', source_layer_id: 'layer1' })
    expect(api.submitSubmission).toHaveBeenCalledWith('sub1')
    expect(await store.list()).toEqual([])
  })

  it('keeps progress when the connection drops, and resumes from there', async () => {
    const store = memoryDraftStore()
    const api = fakeApi()
    api.createTextLayer.mockRejectedValueOnce(new NetworkError())

    await expect(syncDraft(draft(), store, api)).rejects.toBeInstanceOf(NetworkError)
    const saved = await store.get('c1')
    expect(saved?.progress).toEqual({ submissionId: 'sub1', recordingId: 'rec1' })
    expect(saved?.lastError).toBe('network_error')
    expect(saved?.audio).toBeDefined() // never thrown away because an upload failed

    await syncDraft(saved!, store, api)
    expect(api.createSubmission).toHaveBeenCalledTimes(1)
    expect(api.uploadRecording).toHaveBeenCalledTimes(1)
    expect(await store.get('c1')).toBeUndefined()
  })

  it('finds a text the server already has after a lost answer', async () => {
    const store = memoryDraftStore()
    const api = fakeApi()
    api.createTextLayer.mockRejectedValueOnce(new ApiError(409, 'layer_exists'))
    api.getSubmission.mockResolvedValueOnce({
      id: 'sub1',
      text_layers: [
        { id: 'existing', layer_type: 'transcription', recording_id: 'rec1', script_code: 'Deva' },
      ],
    })

    await syncDraft(draft(), store, api)
    expect(api.createTextLayer.mock.calls[1]![1]).toMatchObject({ source_layer_id: 'existing' })
  })

  it('treats an already submitted draft as done', async () => {
    const store = memoryDraftStore()
    const api = fakeApi()
    api.submitSubmission.mockRejectedValueOnce(new ApiError(409, 'submission_not_draft'))
    await store.put(draft())

    await syncDraft(draft(), store, api)
    expect(await store.list()).toEqual([])
  })

  it('uploads the audio again when the server deleted it, then submits', async () => {
    const store = memoryDraftStore()
    const api = fakeApi()
    api.submitSubmission.mockRejectedValueOnce(new ApiError(409, 'recording_expired'))
    const sent = draft({ progress: { submissionId: 'sub1', recordingId: 'rec1' } })
    sent.texts = sent.texts.map((t) => ({ ...t, serverLayerId: `layer-${t.key}` }))
    await store.put(sent)

    await syncDraft(sent, store, api)

    expect(api.uploadRecording).toHaveBeenCalledOnce()
    expect(api.uploadRecording.mock.calls[0]?.[4]).toBe('k1') // same key restores the recording
    expect(api.submitSubmission).toHaveBeenCalledTimes(2)
    expect(await store.list()).toEqual([])
  })

  it('keeps the draft and the reason when the server refuses it', async () => {
    const store = memoryDraftStore()
    const api = fakeApi()
    api.submitSubmission.mockRejectedValueOnce(new ApiError(422, 'consent_required'))

    await expect(syncDraft(draft(), store, api)).rejects.toBeInstanceOf(ApiError)
    expect((await store.get('c1'))?.lastError).toBe('consent_required')
  })
})

describe('submissionBody', () => {
  it('leaves out empty answers and keeps what was filled in', () => {
    const body = submissionBody(
      draft({
        kind: 'text',
        recordingMode: undefined,
        details: { ...emptyDetails(), title: '  Story  ', speakerCount: 2 },
      }),
    )
    expect(body).toMatchObject({
      kind: 'text',
      title: 'Story',
      collection_context: { speaker_count: 2 },
    })
    expect(body.recording_mode).toBeUndefined()
    expect(body.dialect_label).toBeUndefined()
    expect(body.collection_context?.notes).toBeUndefined()
    expect(JSON.parse(JSON.stringify(body))).not.toHaveProperty('recorded_on')
  })
})
