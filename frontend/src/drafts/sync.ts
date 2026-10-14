/**
 * Sends a ready draft to the server, step by step, saving progress on the device after each
 * step (docs/SYSTEM_ARCHITECTURE.md §4.1). Every step is safe to repeat: the draft ID, the
 * upload's Idempotency-Key, and the server's duplicate checks make a retry after a lost
 * response land on the same records instead of creating new ones.
 *
 * The server deletes the audio of a draft left unsent for 30 days (docs/ASSUMPTIONS_AND_OPEN_
 * QUESTIONS.md Q-T7). The phone still has it, so it is uploaded again with the same key, which
 * restores the same recording, and the draft is submitted again.
 */
import { ApiError, errorCode } from '../api/client'
import * as endpoints from '../api/endpoints'
import type { SubmissionCreate, TextLayerCreate } from '../api/types'
import type { DraftStore } from './store'
import type { Draft, DraftText } from './types'

export type SyncApi = Pick<
  typeof endpoints,
  'createSubmission' | 'uploadRecording' | 'createTextLayer' | 'getSubmission' | 'submitSubmission'
>

/** The server no longer has the draft's audio. */
const AUDIO_GONE = new Set(['recording_expired', 'recording_missing'])

export function submissionBody(draft: Draft): SubmissionCreate {
  const d = draft.details
  const optional = (value: string) => (value.trim() ? value.trim() : undefined)
  return {
    client_submission_id: draft.clientSubmissionId,
    speaker_id: draft.speakerId,
    kind: draft.kind,
    content_type: d.contentType,
    title: optional(d.title),
    dialect_label: optional(d.dialectLabel),
    region_coarse: optional(d.regionCoarse),
    recorded_on: optional(d.recordedOn),
    collection_method: draft.collectionMethod,
    recording_mode: draft.recordingMode,
    prompt_id: draft.promptId,
    collection_context: {
      setting: d.setting,
      speaker_count: d.speakerCount,
      equipment: d.equipment,
      notes: optional(d.notes),
    },
  }
}

/** Sources first, so a translation can name the layer it translates. */
function inOrder(texts: DraftText[]): DraftText[] {
  return [...texts.filter((t) => !t.translatesKey), ...texts.filter((t) => t.translatesKey)]
}

function layerBody(draft: Draft, text: DraftText): TextLayerCreate {
  const body: TextLayerCreate = {
    layer_type: text.layerType,
    language_tag: text.languageTag,
    script_code: text.scriptCode,
    content: text.content,
  }
  if (text.layerType === 'standalone') body.entry_type = text.entryType
  if (text.layerType === 'transcription') body.recording_id = draft.progress.recordingId
  if (text.translatesKey) {
    body.source_layer_id = draft.texts.find((t) => t.key === text.translatesKey)?.serverLayerId
  }
  return body
}

/** After a lost response the layer exists but its ID is unknown: find it on the server. */
async function findExistingLayer(api: SyncApi, submissionId: string, body: TextLayerCreate) {
  const submission = await api.getSubmission(submissionId)
  const match = submission.text_layers?.find((layer) =>
    body.layer_type === 'transcription'
      ? layer.recording_id === body.recording_id && layer.script_code === body.script_code
      : layer.source_layer_id === body.source_layer_id && layer.language_tag === body.language_tag,
  )
  if (!match) throw new ApiError(409, 'layer_exists')
  return match
}

async function submit(api: SyncApi, submissionId: string) {
  try {
    await api.submitSubmission(submissionId)
  } catch (error) {
    // Already submitted: an earlier attempt succeeded but its answer was lost.
    if (!(error instanceof ApiError && error.code === 'submission_not_draft')) throw error
  }
}

export async function syncDraft(
  input: Draft,
  store: DraftStore,
  api: SyncApi = endpoints,
): Promise<void> {
  let draft = input
  const save = async (changes: Partial<Draft>) => {
    draft = { ...draft, ...changes, updatedAt: new Date().toISOString() }
    await store.put(draft)
  }

  try {
    let submissionId = draft.progress.submissionId
    if (!submissionId) {
      submissionId = (await api.createSubmission(submissionBody(draft))).id
      await save({ progress: { ...draft.progress, submissionId } })
    }

    const uploadAudio = async (id: string, audio: NonNullable<Draft['audio']>) => {
      const { blob, filename, source } = audio
      return api.uploadRecording(id, blob, filename, source, draft.uploadKey)
    }

    if (draft.audio && !draft.progress.recordingId) {
      const uploaded = await uploadAudio(submissionId, draft.audio)
      await save({ progress: { ...draft.progress, recordingId: uploaded.recording_id } })
    }

    for (const text of inOrder(draft.texts)) {
      if (text.serverLayerId) continue
      const body = layerBody(draft, text)
      let layerId: string
      try {
        layerId = (await api.createTextLayer(submissionId, body)).id
      } catch (error) {
        if (!(error instanceof ApiError && error.code === 'layer_exists')) throw error
        layerId = (await findExistingLayer(api, submissionId, body)).id
      }
      await save({
        texts: draft.texts.map((t) => (t.key === text.key ? { ...t, serverLayerId: layerId } : t)),
      })
    }

    try {
      await submit(api, submissionId)
    } catch (error) {
      if (!(draft.audio && error instanceof ApiError && AUDIO_GONE.has(error.code))) throw error
      await uploadAudio(submissionId, draft.audio)
      await submit(api, submissionId)
    }
    // The server has everything now; do not keep the recording on a possibly shared phone.
    await store.remove(draft.clientSubmissionId)
  } catch (error) {
    await save({ lastError: errorCode(error) })
    throw error
  }
}
