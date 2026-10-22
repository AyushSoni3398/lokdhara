import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import * as api from '../api/endpoints'
import type { Submission } from '../api/types'
import { ErrorMessage } from '../components/ErrorMessage'
import { useDrafts } from '../drafts/DraftsProvider'
import { useDraftStore } from '../drafts/store'
import type { Draft } from '../drafts/types'

/** What is still on this phone, and what the server has (FR-S7). */
export function MySubmissionsPage() {
  const { t, i18n } = useTranslation()
  const { drafts, uploading, uploadNow, refresh } = useDrafts()
  const store = useDraftStore()
  const [submissions, setSubmissions] = useState<Submission[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const pending = drafts.filter((draft) => draft.ready).length
  // Server drafts are still listed above, from the device.
  const sent = submissions?.filter((submission) => submission.status !== 'draft')
  // Accepted audio has its listening copy, which is what the zip holds (ADR-026).
  const canDownloadAll = sent?.some(
    (submission) =>
      submission.kind !== 'text' &&
      submission.status === 'accepted' &&
      submission.restriction_flags.length === 0,
  )

  useEffect(() => {
    // Reload the server's list whenever an upload round finishes.
    if (!uploading) api.listSubmissions().then(setSubmissions, setError)
  }, [uploading, pending])

  const discard = async (draft: Draft) => {
    if (!window.confirm(t('submissions.discardConfirm'))) return
    await store.remove(draft.clientSubmissionId)
    await refresh()
  }

  const date = (iso: string) => new Date(iso).toLocaleDateString(i18n.resolvedLanguage)

  return (
    <section>
      <h1>{t('submissions.title')}</h1>

      {drafts.length > 0 && (
        <>
          <h2>{t('submissions.onDevice')}</h2>
          <ul className="list">
            {drafts.map((draft) => (
              <li key={draft.clientSubmissionId} className="list-item">
                <strong>{draft.details.title || t(`kinds.${draft.kind}`)}</strong>
                <span>
                  {draft.speakerCode} · {date(draft.createdAt)}
                </span>
                {draft.ready ? (
                  <span className="status waiting">
                    {uploading ? t('submissions.uploading') : t('submissions.waiting')}
                  </span>
                ) : (
                  <span className="status">{t('submissions.unfinished')}</span>
                )}
                {draft.ready && draft.lastError && <ErrorMessage error={draft.lastError} />}
                <div className="row">
                  {!draft.ready && (
                    <Link to={`/drafts/${draft.clientSubmissionId}`} className="small-action">
                      {t('submissions.continue')}
                    </Link>
                  )}
                  {!draft.progress.submissionId && (
                    <button
                      type="button"
                      className="small-action"
                      onClick={() => void discard(draft)}
                    >
                      {t('submissions.discard')}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {pending > 0 && (
            <button type="button" className="action" disabled={uploading} onClick={uploadNow}>
              {t('submissions.retry')}
            </button>
          )}
          <p className="note">{t('submissions.keptOnDevice')}</p>
        </>
      )}

      <h2>{t('submissions.sent')}</h2>
      <ErrorMessage error={error} />
      {sent?.length === 0 && <p className="note">{t('submissions.none')}</p>}
      <ul className="list">
        {sent?.map((submission) => (
          <li key={submission.id} className="list-item">
            <Link to={`/submissions/${submission.id}`}>
              <strong>{submission.title || t(`kinds.${submission.kind}`)}</strong>
            </Link>
            <span>{date(submission.submitted_at ?? submission.created_at)}</span>
            <span className={`status status-${submission.status}`}>
              {t(`statuses.${submission.status}`, { defaultValue: submission.status })}
            </span>
          </li>
        ))}
      </ul>
      {canDownloadAll && (
        <>
          <a className="action" href={api.MY_RECORDINGS_ZIP_URL} download>
            {t('submissions.downloadAll')}
          </a>
          <p className="note">{t('submissions.downloadAllNote')}</p>
        </>
      )}
      <p>
        <Link to="/withdrawals">{t('withdrawal.link')}</Link>
      </p>
    </section>
  )
}
