/** Shapes of the API's JSON (docs/API_SPECIFICATION.md). Only the fields the app uses. */

export type Role = 'contributor' | 'facilitator' | 'reviewer' | 'researcher' | 'admin'

export interface Session {
  user: { id: string; username: string; display_name: string; preferred_locale: string }
  roles: { role: Role; scope: string | null }[]
  csrf_token: string
}

export interface Speaker {
  id: string
  speaker_code: string
  is_self: boolean
  status: string
  has_active_consent: boolean
  dialect_label: string | null
}

export interface ConsentForm {
  id: string
  version: string
  language: string
  body_markdown: string
  is_test_form: boolean
}

export type ConsentMethod = 'in_app' | 'oral_recorded' | 'paper_reference'
export type Attribution = 'pseudonymous' | 'name' | 'none'

export interface ConsentAnswers {
  consent_form_id: string
  method: ConsentMethod
  paper_reference?: string
  allow_store_and_review: boolean
  allow_research: boolean
  allow_public_access: boolean
  allow_ai_training: boolean
  allow_commercial_use: boolean
  attribution_preference: Attribution
  demographics_consented: boolean
}

export type PromptType = 'image' | 'situation' | 'read_sentence'
export type Script = 'Deva' | 'Latn' | 'Nagm' | 'Beng' | 'Orya' | 'Zyyy'

export interface Prompt {
  id: string
  prompt_type: PromptType
  text: string | null
  text_language_tag: string | null
  script_code: Script | null
  image_url: string | null
  audio_url: string | null
}

export type Kind = 'audio' | 'text' | 'audio_text'
export type RecordingMode = 'free' | 'prompted' | 'read'
export type ContentType =
  | 'story'
  | 'conversation'
  | 'vocabulary'
  | 'song'
  | 'sentence_list'
  | 'other'
export type CollectionMethod = 'self_recorded' | 'facilitator_field' | 'facilitator_remote'
export type LayerType = 'standalone' | 'transcription' | 'translation'
export type EntryType = 'word' | 'phrase' | 'sentence' | 'paragraph' | 'long_text'
export type Setting = 'indoor_quiet' | 'indoor_noisy' | 'outdoor' | 'unknown'
export type Equipment = 'phone_builtin_mic' | 'phone_external_mic' | 'field_recorder' | 'unknown'

export interface CollectionContext {
  setting?: Setting
  speaker_count?: number
  equipment?: Equipment
  notes?: string
}

export interface SubmissionCreate {
  client_submission_id: string
  speaker_id: string
  kind: Kind
  content_type: ContentType
  title?: string
  dialect_label?: string
  region_coarse?: string
  recorded_on?: string
  collection_method: CollectionMethod
  recording_mode?: RecordingMode
  prompt_id?: string
  collection_context: CollectionContext
}

export interface TextLayer {
  id: string
  layer_type: LayerType
  recording_id: string | null
  source_layer_id: string | null
  language_tag: string
  script_code: Script
}

/** One saved version of a text; never changed after it is saved (ADR-011). */
export interface Revision {
  id: string
  revision_number: number
  content: string
  origin: string
  based_on_revision_id: string | null
  source_revision_id: string | null
  detected_scripts: string[]
  uncertainty_markup: boolean
  verification_status: 'unverified' | 'verified' | 'disputed'
  change_note: string | null
  created_at: string
}

export interface DiffPart {
  op: 'equal' | 'delete' | 'insert'
  text: string
}

export interface TextLayerDetail extends TextLayer {
  entry_type: EntryType | null
  current_revision: Revision | null
  /** Translations: the source text has a newer version than the one translated. */
  source_changed: boolean
  /** The chosen script does not appear in the text (a warning only). */
  script_mismatch: boolean
}

export interface Recording {
  id: string
  upload_status: string
  size_bytes: number
  duration_ms: number | null
  quality_flags: string[]
  created_at: string
}

export interface Playback {
  sources: { url: string; content_type: string }[]
}

/** Set by an admin to hide an item after a report (docs/ROADMAP.md M6). */
export type Restriction =
  | 'sensitive'
  | 'third_party_voice'
  | 'contains_pii'
  | 'culturally_restricted'
  | 'minor'

export interface Submission {
  id: string
  client_submission_id: string
  kind: Kind
  content_type: ContentType
  title: string | null
  status: string
  restriction_flags: Restriction[]
  recording_mode: RecordingMode | null
  created_at: string
  submitted_at: string | null
  text_layers?: TextLayer[]
}

export interface SubmissionDetail extends Submission {
  /** Sent by the person looking; only they change it. */
  mine: boolean
  recordings: Recording[]
  text_layers: TextLayerDetail[]
}

export interface TextLayerCreate {
  layer_type: LayerType
  recording_id?: string
  source_layer_id?: string
  entry_type?: EntryType
  language_tag: string
  script_code: Script
  content: string
}

/** A background check, as admins see it (docs/API_SPECIFICATION.md §9). */
export interface Job {
  id: string
  job_type: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  attempts: number
  max_attempts: number
  target_type: string | null
  target_id: string | null
  last_error_code: string | null
  created_at: string
  finished_at: string | null
}

export interface BackupState {
  kind: 'database' | 'withdrawal_log'
  last_run_at: string | null
  last_run_succeeded: boolean | null
  last_run_detail: string | null
  last_success_at: string | null
  last_success_bytes: number | null
}

export interface ServiceStatus {
  checked_at: string
  alerts: string[]
  jobs_queued: number
  jobs_running: number
  oldest_due_job_since: string | null
  jobs_failed_last_day: number
  jobs_failed_waiting: number
  backups: BackupState[]
  submissions_last_day: number
  accepted_last_day: number
  rejected_last_day: number
  login_failures_last_day: number
  open_reports: number
  open_withdrawals: number
  exports_awaiting_approval: number
  database_bytes: number
  disk_used_share: number | null
}

export type ReportReason =
  | 'personal_information'
  | 'third_party_voice'
  | 'culturally_restricted'
  | 'wrong_content'

export interface Report {
  id: string
  submission_id: string
  reason: ReportReason
  note: string | null
  created_at: string
}

/** An item with open reports, as admins see it (docs/API_SPECIFICATION.md §7). */
export interface ReportedItem {
  submission: {
    id: string
    title: string | null
    kind: Kind
    content_type: ContentType
    status: string
    restriction_flags: Restriction[]
    submitted_at: string | null
  }
  reports: Report[]
}

/** One item in the researcher catalogue (docs/API_SPECIFICATION.md §8). */
export interface CatalogueItem {
  id: string
  title: string | null
  kind: Kind
  content_type: ContentType
  recording_mode: RecordingMode | null
  language_tag: string
  dialect_label: string | null
  region_coarse: string | null
  submitted_at: string | null
  restriction_flags: Restriction[]
  duration_ms: number | null
  quality_flags: string[]
  text_preview: string | null
  text_script: Script | null
  text_status: 'unverified'
}

export interface CatalogueQuery {
  q?: string
  kind?: Kind
  content_type?: ContentType
  cursor?: string
}

/** What a dataset release may be used for; each needs its own consent answer. */
export type ReleasePurpose = 'internal_research' | 'external_research' | 'public' | 'ai_training'
export type ReleaseStatus = 'draft' | 'frozen' | 'retracted'

/** Which accepted items a draft release takes (docs/DATASET_VERSIONING.md). Empty means any. */
export interface SelectionCriteria {
  kinds: Kind[]
  content_types: ContentType[]
  recording_modes: RecordingMode[]
  dialect_labels: string[]
  needs_audio: boolean
  needs_transcription: boolean
}

export interface Release {
  id: string
  slug: string
  version: string | null
  purpose: ReleasePurpose
  selection_criteria: SelectionCriteria
  status: ReleaseStatus
  licence: string | null
  data_card_markdown: string
  manifest_sha256: string | null
  created_at: string
  updated_at: string
  frozen_at: string | null
  retracted_at: string | null
  retraction_note: string | null
  replaces_id: string | null
  next_version: string | null
  withdrawn_item_count: number
}

export interface ReleaseCreate {
  slug: string
  purpose: ReleasePurpose
}

export type ReleaseUpdate = Partial<
  Pick<Release, 'purpose' | 'selection_criteria' | 'licence' | 'data_card_markdown'>
>

export interface ReleasePreview {
  item_count: number
  total_duration_ms: number
  left_out_count: number
  by_content_type: Record<string, number>
  by_dialect_label: Record<string, number>
  by_kind: Record<string, number>
  sample: {
    id: string
    title: string | null
    content_type: ContentType
    duration_ms: number | null
  }[]
}

/** One pre-freeze check, D1 to D9 (docs/DATA_QUALITY_AND_VALIDATION.md §4). */
export interface ReleaseCheck {
  code: string
  passed: boolean
  blocking: boolean
  message: string
}

export type ExportStatus =
  | 'requested'
  | 'approved'
  | 'building'
  | 'ready'
  | 'expired'
  | 'rejected'
  | 'failed'

export interface ExportRequest {
  id: string
  release_id: string
  release_slug: string
  release_version: string | null
  requested_by_name: string
  mine: boolean
  purpose_statement: string
  status: ExportStatus
  decision_note: string | null
  decided_at: string | null
  created_at: string
  ready_at: string | null
  expires_at: string | null
  sha256: string | null
  size_bytes: number | null
  download_count: number
}

/** A short-lived link to a ready package. */
export interface ExportDownload {
  download_url: string
  file_name: string
  sha256: string
  size_bytes: number
  expires_at: string
}

export type WithdrawalScope = 'full' | 'narrow' | 'specific_items'
export type ReceivedVia = 'in_app' | 'facilitator' | 'phone' | 'in_person' | 'email'
export type WithdrawalStatus = 'received' | 'verified' | 'in_progress' | 'completed' | 'rejected'

export interface WithdrawalCreate {
  scope: WithdrawalScope
  speaker_id?: string
  submission_id?: string
  received_via?: ReceivedVia
  note?: string
}

export interface Withdrawal {
  id: string
  speaker_id: string
  speaker_code: string
  submission_id: string | null
  requested_scope: WithdrawalScope
  received_via: ReceivedVia
  received_at: string
  status: WithdrawalStatus
  note: string | null
  verified_at: string | null
  erased_at: string | null
  completed_at: string | null
  /** Only admins get the record of what was done. */
  actions_taken: { action: string; at: string; note?: string }[] | null
}
