import type {
  CollectionMethod,
  ContentType,
  EntryType,
  Equipment,
  Kind,
  LayerType,
  RecordingMode,
  Script,
  Setting,
} from '../api/types'

/** Text typed on the device; `serverLayerId` is set once the server has it. */
export interface DraftText {
  key: string
  layerType: LayerType
  entryType?: EntryType
  languageTag: string
  scriptCode: Script
  content: string
  /** For translations: the `key` of the text it translates. */
  translatesKey?: string
  serverLayerId?: string
}

export interface DraftAudio {
  blob: Blob
  filename: string
  source: 'browser_recorder' | 'file_upload'
}

export interface DraftDetails {
  contentType: ContentType
  title: string
  dialectLabel: string
  regionCoarse: string
  recordedOn: string
  setting?: Setting
  speakerCount?: number
  equipment?: Equipment
  notes: string
}

/**
 * A contribution kept on the device (IndexedDB) until the server has all of it
 * (docs/USER_FLOWS.md F1, FR-S6). `ready` drafts upload; the others are still being edited.
 */
export interface Draft {
  clientSubmissionId: string
  /** The signed-in user who made it: a shared phone never uploads one person's draft as another's. */
  ownerId: string
  speakerId: string
  speakerCode: string
  collectionMethod: CollectionMethod
  kind: Kind
  recordingMode?: RecordingMode
  promptId?: string
  promptText?: string
  audio?: DraftAudio
  texts: DraftText[]
  details: DraftDetails
  /** The Idempotency-Key for this draft's audio upload, the same on every retry. */
  uploadKey: string
  ready: boolean
  progress: { submissionId?: string; recordingId?: string }
  lastError?: string
  /** The last upload failed for a reason that sending it again unchanged will not fix. */
  needsChange?: boolean
  createdAt: string
  updatedAt: string
}

export function emptyDetails(): DraftDetails {
  return {
    contentType: 'story',
    title: '',
    dialectLabel: '',
    regionCoarse: '',
    recordedOn: '',
    notes: '',
  }
}
