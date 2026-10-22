import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import * as api from '../api/endpoints'
import type { Playback, Recording, SubmissionDetail, TextLayerDetail } from '../api/types'
import { hasRole, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'
import { AdminUnhide } from './submission/AdminUnhide'
import { ReportProblem } from './submission/ReportProblem'
import { AddText, EditText, TRANSLATIONS } from './submission/TextEditor'
import { TextHistory } from './submission/TextHistory'
import { WithdrawItem } from './submission/WithdrawItem'

// With no reviewer the contributor keeps correcting and translating after acceptance (ADR-021).
const TEXT_EDITABLE = ['accepted']

/**
 * One sent submission: its status, its recording to listen to, and its texts (ROADMAP M5).
 * Researchers open catalogue items here too, read-only; anyone can report a problem (M6).
 */
export function SubmissionPage() {
  const { t, i18n } = useTranslation()
  const { submissionId = '' } = useParams()
  const session = useSession()
  const [submission, setSubmission] = useState<SubmissionDetail | null>(null)
  const [error, setError] = useState<unknown>(null)

  const [adding, setAdding] = useState(false)

  const reload = useCallback(
    () => api.getSubmissionDetail(submissionId).then(setSubmission, setError),
    [submissionId],
  )
  useEffect(() => {
    void reload()
  }, [reload])

  if (!submission) return <ErrorMessage error={error} />

  const date = (iso: string) => new Date(iso).toLocaleDateString(i18n.resolvedLanguage)
  const editable = submission.mine && TEXT_EDITABLE.includes(submission.status)
  const replace = (saved: TextLayerDetail) =>
    setSubmission({
      ...submission,
      text_layers: submission.text_layers.map((layer) => (layer.id === saved.id ? saved : layer)),
    })
  // A recording without a transcription yet: offer to write down what is said.
  const untranscribed = submission.recordings.find(
    (recording) =>
      recording.upload_status === 'promoted' &&
      !submission.text_layers.some((layer) => layer.recording_id === recording.id),
  )
  // Each text, with the translations of it right after it.
  const sources = submission.text_layers.filter((layer) => !layer.source_layer_id)
  const ordered = sources.flatMap((source) => [
    source,
    ...submission.text_layers.filter((layer) => layer.source_layer_id === source.id),
  ])

  return (
    <section>
      <p>
        {submission.mine ? (
          <Link to="/submissions">{t('submission.back')}</Link>
        ) : (
          <Link to="/catalogue">{t('catalogue.back')}</Link>
        )}
      </p>
      <h1>{submission.title || t(`kinds.${submission.kind}`)}</h1>
      <span className={`status status-${submission.status}`}>
        {t(`statuses.${submission.status}`, { defaultValue: submission.status })}
      </span>
      <p className="note">
        {t('submission.sentOn', { date: date(submission.submitted_at ?? submission.created_at) })}
      </p>
      {submission.restriction_flags.length > 0 && (
        <p className="status waiting">
          {t('submission.hidden', {
            reasons: submission.restriction_flags
              .map((flag) => t(`restrictions.${flag}`))
              .join(', '),
          })}
        </p>
      )}
      {hasRole(session, 'admin') && !submission.mine && submission.restriction_flags.length > 0 && (
        <AdminUnhide
          submissionId={submission.id}
          flags={submission.restriction_flags}
          onChanged={() => void reload()}
        />
      )}
      <ErrorMessage error={error} />

      {submission.recordings.map((recording) => (
        <RecordingPlayer
          key={recording.id}
          recording={recording}
          // Your own, unless an admin has hidden it after a report (ADR-026).
          downloadable={submission.mine && submission.restriction_flags.length === 0}
        />
      ))}

      <h2>{t('submission.texts')}</h2>
      {ordered.length === 0 && <p className="note">{t('submission.noText')}</p>}
      <ul className="list">
        {ordered.map((layer) => (
          <TextLayerItem
            key={layer.id}
            layer={layer}
            submission={submission}
            editable={editable}
            onSaved={replace}
            onChanged={() => void reload()}
          />
        ))}
      </ul>
      {editable &&
        untranscribed &&
        (adding ? (
          <AddText
            submissionId={submission.id}
            base={{
              layer_type: 'transcription',
              recording_id: untranscribed.id,
              language_tag: 'unr',
            }}
            label={t('text.transcription')}
            chooseScript
            onAdded={() => {
              setAdding(false)
              void reload()
            }}
            onCancel={() => setAdding(false)}
          />
        ) : (
          <button type="button" className="small-action" onClick={() => setAdding(true)}>
            {t('submission.addTranscription')}
          </button>
        ))}

      <h2>{t('report.title')}</h2>
      <ReportProblem submissionId={submission.id} />

      {submission.mine && submission.status !== 'withdrawn' && (
        <>
          <h2>{t('withdrawal.itemTitle')}</h2>
          <WithdrawItem submissionId={submission.id} />
        </>
      )}
    </section>
  )
}

function RecordingPlayer({
  recording,
  downloadable,
}: {
  recording: Recording
  downloadable: boolean
}) {
  const { t } = useTranslation()
  const [playback, setPlayback] = useState<Playback | null>(null)
  const usable = recording.upload_status === 'promoted'

  useEffect(() => {
    if (usable) api.getPlayback(recording.id).then(setPlayback, () => setPlayback(null))
  }, [recording.id, usable])

  return (
    <>
      <h2>{t('submission.recording')}</h2>
      {playback && playback.sources.length > 0 ? (
        <>
          <audio controls preload="none" aria-label={t('submission.recording')}>
            {playback.sources.map((source) => (
              <source key={source.url} src={source.url} type={source.content_type} />
            ))}
          </audio>
          {downloadable && (
            <div className="row">
              <a className="small-action" href={api.recordingDownloadUrl(recording.id)} download>
                {t('submission.download')}
              </a>
            </div>
          )}
        </>
      ) : (
        <p className="note">
          {usable ? t('submission.notReadyToPlay') : t('submission.notPlayable')}
        </p>
      )}
    </>
  )
}

function TextLayerItem({
  layer,
  submission,
  editable,
  onSaved,
  onChanged,
}: {
  layer: TextLayerDetail
  submission: SubmissionDetail
  editable: boolean
  onSaved: (layer: TextLayerDetail) => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<'view' | 'edit' | string>('view')
  const revision = layer.current_revision
  // Hindi and English translations this text does not have yet.
  const missing = layer.source_layer_id
    ? []
    : TRANSLATIONS.filter(
        ({ languageTag }) =>
          languageTag !== layer.language_tag &&
          !submission.text_layers.some(
            (other) => other.source_layer_id === layer.id && other.language_tag === languageTag,
          ),
      )
  return (
    <li className="list-item">
      <strong>
        {t(`review.text.${layer.layer_type}`, {
          language: t(`submission.languages.${layer.language_tag}`, {
            defaultValue: layer.language_tag,
          }),
        })}
      </strong>
      <span className="note">
        {t(`scripts.${layer.script_code}`, { defaultValue: layer.script_code })}
        {revision && ` · ${t('submission.version', { number: revision.revision_number })}`}
      </span>
      {revision && (
        <p className="user-text" lang={layer.language_tag}>
          {revision.content}
        </p>
      )}
      {revision?.verification_status !== 'verified' && (
        <span className="badge">{t('submission.unverified')}</span>
      )}
      {layer.script_mismatch && (
        <span className="status waiting">
          {t('submission.scriptMismatch', { script: t(`scripts.${layer.script_code}`) })}
        </span>
      )}
      {layer.source_changed && (
        <span className="status waiting">{t('submission.sourceChanged')}</span>
      )}
      {mode === 'edit' && (
        <EditText
          layer={layer}
          onSaved={(saved) => {
            setMode('view')
            onSaved(saved)
          }}
          onCancel={() => setMode('view')}
          onConflict={onChanged}
        />
      )}
      {TRANSLATIONS.filter(({ languageTag }) => mode === languageTag).map(
        ({ languageTag, scriptCode }) => (
          <AddText
            key={languageTag}
            submissionId={submission.id}
            base={{
              layer_type: 'translation',
              source_layer_id: layer.id,
              language_tag: languageTag,
              script_code: scriptCode,
            }}
            label={t(`submission.translationOf.${languageTag}`)}
            chooseScript={false}
            onAdded={() => {
              setMode('view')
              onChanged()
            }}
            onCancel={() => setMode('view')}
          />
        ),
      )}
      {mode === 'history' && <TextHistory layerId={layer.id} language={layer.language_tag} />}
      {revision && revision.revision_number > 1 && (mode === 'view' || mode === 'history') && (
        <div className="row">
          <button
            type="button"
            className="small-action"
            aria-expanded={mode === 'history'}
            onClick={() => setMode(mode === 'history' ? 'view' : 'history')}
          >
            {t(mode === 'history' ? 'submission.history.hide' : 'submission.history.show')}
          </button>
        </div>
      )}
      {editable && mode === 'view' && revision && (
        <div className="row">
          <button type="button" className="small-action" onClick={() => setMode('edit')}>
            {t('submission.edit.start')}
          </button>
          {missing.map(({ languageTag }) => (
            <button
              key={languageTag}
              type="button"
              className="small-action"
              onClick={() => setMode(languageTag)}
            >
              {t(`submission.addTranslation.${languageTag}`)}
            </button>
          ))}
        </div>
      )}
    </li>
  )
}
