/** One function per API call the app makes. */
import { request } from './client'
import type {
  CatalogueItem,
  CatalogueQuery,
  ConsentAnswers,
  ConsentForm,
  DiffPart,
  ExportDownload,
  ExportRequest,
  Job,
  Playback,
  Prompt,
  PromptType,
  Release,
  ReleaseCheck,
  ReleaseCreate,
  ReleasePreview,
  ReleaseUpdate,
  Report,
  ReportedItem,
  ReportReason,
  Restriction,
  Revision,
  Script,
  ServiceStatus,
  Session,
  Speaker,
  Submission,
  SubmissionCreate,
  SubmissionDetail,
  TextLayer,
  TextLayerCreate,
  TextLayerDetail,
  Withdrawal,
  WithdrawalCreate,
} from './types'

export const login = (username: string, password: string) =>
  request<Session>('POST', '/auth/login', { json: { username, password } })
export const logout = () => request<void>('POST', '/auth/logout')
export const me = () => request<Session>('GET', '/auth/me')

export const listSpeakers = () =>
  request<{ items: Speaker[] }>('GET', '/speakers?mine=true').then((r) => r.items)
export const createSpeaker = (forSelf: boolean) =>
  request<Speaker>('POST', '/speakers', { json: { for_self: forSelf } })
export const getSpeaker = (id: string) => request<Speaker>('GET', `/speakers/${id}`)
/** Admins: every speaker, for logging a request someone made by phone or in person. */
export const listAllSpeakers = () =>
  request<{ items: Speaker[] }>('GET', '/speakers?mine=false').then((r) => r.items)

export const requestWithdrawal = (body: WithdrawalCreate) =>
  request<Withdrawal>('POST', '/withdrawal-requests', { json: body })
export const listMyWithdrawals = () =>
  request<{ items: Withdrawal[] }>('GET', '/withdrawal-requests').then((r) => r.items)
export const listWithdrawalQueue = (open: boolean) =>
  request<{ items: Withdrawal[] }>('GET', `/admin/withdrawal-requests?open=${open}`).then(
    (r) => r.items,
  )
export const decideWithdrawal = (
  id: string,
  decision: 'verify' | 'reject' | 'complete',
  note: string,
) => request<Withdrawal>('POST', `/admin/withdrawal-requests/${id}/${decision}`, { json: { note } })

export const currentConsentForm = (language: string) =>
  request<ConsentForm>('GET', `/consent-forms/current?language=${encodeURIComponent(language)}`)

export function recordConsent(speakerId: string, answers: ConsentAnswers, evidence?: Blob) {
  const form = new FormData()
  form.append('consent', JSON.stringify(answers))
  if (evidence) form.append('evidence', evidence, 'consent')
  return request<unknown>('POST', `/speakers/${speakerId}/consents`, { form })
}

export function nextPrompt(type: PromptType, script: Script | null, exclude: string[]) {
  const query = new URLSearchParams({ type })
  if (script) query.set('script', script)
  for (const id of exclude) query.append('exclude', id)
  return request<Prompt>('GET', `/prompts/next?${query}`)
}
export const getPrompt = (id: string) => request<Prompt>('GET', `/prompts/${id}`)

export const createSubmission = (body: SubmissionCreate) =>
  request<Submission>('POST', '/submissions', { json: body })
export const getSubmission = (id: string) => request<Submission>('GET', `/submissions/${id}`)
export const getSubmissionDetail = (id: string) =>
  request<SubmissionDetail>('GET', `/submissions/${id}`)
export const getPlayback = (recordingId: string) =>
  request<Playback>('GET', `/recordings/${recordingId}/playback`)
export const listSubmissions = () =>
  request<{ items: Submission[] }>('GET', '/submissions?mine=true&limit=100').then((r) => r.items)

export function uploadRecording(
  submissionId: string,
  audio: Blob,
  filename: string,
  source: 'browser_recorder' | 'file_upload',
  idempotencyKey: string,
) {
  const form = new FormData()
  form.append('file', audio, filename)
  form.append('source', source)
  return request<{ recording_id: string; upload_status: string }>(
    'POST',
    `/submissions/${submissionId}/recordings`,
    { form, headers: { 'Idempotency-Key': idempotencyKey } },
  )
}

export const createTextLayer = (submissionId: string, body: TextLayerCreate) =>
  request<TextLayer>('POST', `/submissions/${submissionId}/text-layers`, { json: body })

export const addRevision = (
  layerId: string,
  body: { base_revision_id: string; content: string; change_note?: string },
) => request<TextLayerDetail>('POST', `/text-layers/${layerId}/revisions`, { json: body })

export const listRevisions = (layerId: string) =>
  request<{ items: Revision[] }>('GET', `/text-layers/${layerId}/revisions`)

export const diffRevisions = (fromId: string, toId: string) =>
  request<{ parts: DiffPart[] }>('GET', `/text-revisions/${fromId}/diff/${toId}`)

export const reportSubmission = (id: string, reason: ReportReason, note?: string) =>
  request<Report>('POST', `/submissions/${id}/reports`, { json: { reason, note } })

export const submitSubmission = (id: string) =>
  request<Submission>('POST', `/submissions/${id}/submit`)

export const listFailedJobs = () =>
  request<{ items: Job[] }>('GET', '/admin/jobs?status=failed').then((r) => r.items)
export const retryJob = (id: string) => request<Job>('POST', `/admin/jobs/${id}/retry`)

export const getServiceStatus = () => request<ServiceStatus>('GET', '/admin/status')

export const listOpenReports = () =>
  request<{ items: ReportedItem[] }>('GET', '/admin/reports').then((r) => r.items)
export const hideSubmission = (id: string, restriction: Restriction, note: string) =>
  request<ReportedItem['submission']>('POST', `/admin/submissions/${id}/hide`, {
    json: { restriction, note },
  })
export const unhideSubmission = (id: string, restriction: Restriction, note: string) =>
  request<ReportedItem['submission']>('POST', `/admin/submissions/${id}/unhide`, {
    json: { restriction, note },
  })
export const dismissReports = (id: string, note: string) =>
  request<ReportedItem['submission']>('POST', `/admin/submissions/${id}/dismiss-reports`, {
    json: { note },
  })

export function searchCatalogue(query: CatalogueQuery) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) if (value) params.set(key, value)
  const search = params.toString()
  return request<{ items: CatalogueItem[]; next_cursor: string | null }>(
    'GET',
    search ? `/catalogue?${search}` : '/catalogue',
  )
}

export const listReleases = () =>
  request<{ items: Release[] }>('GET', '/datasets').then((r) => r.items)
export const createRelease = (body: ReleaseCreate) =>
  request<Release>('POST', '/datasets', { json: body })
export const getRelease = (id: string) => request<Release>('GET', `/datasets/${id}`)
export const updateRelease = (id: string, changes: ReleaseUpdate) =>
  request<Release>('PATCH', `/datasets/${id}`, { json: changes })
export const previewRelease = (id: string) =>
  request<ReleasePreview>('GET', `/datasets/${id}/preview`)
export const checkRelease = (id: string) =>
  request<{ passed: boolean; checks: ReleaseCheck[] }>('POST', `/datasets/${id}/checks`)
export const freezeRelease = (id: string, version: string) =>
  request<Release>('POST', `/datasets/${id}/freeze`, { json: { version } })
export const retractRelease = (id: string, note: string) =>
  request<Release>('POST', `/datasets/${id}/retract`, { json: { note } })
export const startPatchRelease = (id: string) => request<Release>('POST', `/datasets/${id}/patch`)

export const requestExport = (releaseId: string, purposeStatement: string) =>
  request<ExportRequest>('POST', `/datasets/${releaseId}/exports`, {
    json: { purpose_statement: purposeStatement },
  })
export const listExports = () =>
  request<{ items: ExportRequest[] }>('GET', '/exports').then((r) => r.items)
export const approveExport = (id: string, note?: string) =>
  request<ExportRequest>('POST', `/admin/exports/${id}/approve`, { json: { note } })
export const rejectExport = (id: string, note: string) =>
  request<ExportRequest>('POST', `/admin/exports/${id}/reject`, { json: { note } })
export const downloadExport = (id: string) =>
  request<ExportDownload>('POST', `/exports/${id}/download`)
