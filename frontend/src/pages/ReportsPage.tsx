import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import * as api from '../api/endpoints'
import type { ReportedItem, ReportReason, Restriction } from '../api/types'
import { hasRole, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'

export const RESTRICTIONS: Restriction[] = [
  'contains_pii',
  'third_party_voice',
  'culturally_restricted',
  'sensitive',
  'minor',
]
// The flag that usually answers each reason; the admin can pick another.
const SUGGESTED: Record<ReportReason, Restriction> = {
  personal_information: 'contains_pii',
  third_party_voice: 'third_party_voice',
  culturally_restricted: 'culturally_restricted',
  wrong_content: 'sensitive',
}

/** Admins answer reports: hide the item with a restriction flag, or dismiss (ROADMAP M6). */
export function ReportsPage() {
  const { t } = useTranslation()
  const session = useSession()
  const isAdmin = hasRole(session, 'admin')
  const [items, setItems] = useState<ReportedItem[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (isAdmin) api.listOpenReports().then(setItems, setError)
  }, [isAdmin])

  if (!isAdmin) return <p className="note">{t('jobs.adminOnly')}</p>

  const decided = (id: string) =>
    setItems((current) => current?.filter((item) => item.submission.id !== id) ?? null)

  return (
    <section>
      <h1>{t('reports.title')}</h1>
      <p className="note">{t('reports.intro')}</p>
      <ErrorMessage error={error} />
      {items?.length === 0 && <p className="note">{t('reports.none')}</p>}
      <ul className="list">
        {items?.map((item) => (
          <ReportedItemCard key={item.submission.id} item={item} onDecided={decided} />
        ))}
      </ul>
    </section>
  )
}

function ReportedItemCard({
  item,
  onDecided,
}: {
  item: ReportedItem
  onDecided: (id: string) => void
}) {
  const { t, i18n } = useTranslation()
  const { submission, reports } = item
  const [restriction, setRestriction] = useState<Restriction>(
    SUGGESTED[reports[0]?.reason ?? 'personal_information'],
  )
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const date = (iso: string) => new Date(iso).toLocaleDateString(i18n.resolvedLanguage)

  const decide = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      onDecided(submission.id)
    } catch (caught) {
      setError(caught)
      setBusy(false)
    }
  }

  return (
    <li className="list-item">
      <Link to={`/submissions/${submission.id}`}>
        <strong>{submission.title || t(`kinds.${submission.kind}`)}</strong>
      </Link>
      {submission.restriction_flags.length > 0 && (
        <span className="note">
          {t('reports.alreadyHidden', {
            reasons: submission.restriction_flags.map((f) => t(`restrictions.${f}`)).join(', '),
          })}
        </span>
      )}
      <ul>
        {reports.map((report) => (
          <li key={report.id}>
            {t(`report.reasons.${report.reason}`)} · {date(report.created_at)}
            {report.note && <p className="user-text">{report.note}</p>}
          </li>
        ))}
      </ul>
      <label>
        {t('reports.restriction')}
        <select value={restriction} onChange={(e) => setRestriction(e.target.value as Restriction)}>
          {RESTRICTIONS.map((value) => (
            <option key={value} value={value}>
              {t(`restrictions.${value}`)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t('reports.note')}
        <textarea
          rows={2}
          maxLength={2000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <ErrorMessage error={error} />
      <div className="row">
        <button
          type="button"
          className="small-action"
          disabled={busy || !note.trim()}
          onClick={() =>
            void decide(() => api.hideSubmission(submission.id, restriction, note.trim()))
          }
        >
          {t('reports.hide')}
        </button>
        <button
          type="button"
          className="small-action"
          disabled={busy || !note.trim()}
          onClick={() => void decide(() => api.dismissReports(submission.id, note.trim()))}
        >
          {t('reports.dismiss')}
        </button>
      </div>
    </li>
  )
}
