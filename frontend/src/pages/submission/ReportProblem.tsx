import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import * as api from '../../api/endpoints'
import type { ReportReason } from '../../api/types'
import { Choice } from '../../components/Choice'
import { ErrorMessage } from '../../components/ErrorMessage'

const REASONS: ReportReason[] = [
  'personal_information',
  'third_party_voice',
  'culturally_restricted',
  'wrong_content',
]

/** Tells the admins something is wrong with an item; an admin decides whether to hide it. */
export function ReportProblem({ submissionId }: { submissionId: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState<ReportReason>()
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<unknown>(null)

  if (sent) return <p className="note">{t('report.sent')}</p>
  if (!open)
    return (
      <div className="row">
        <button type="button" className="small-action" onClick={() => setOpen(true)}>
          {t('report.start')}
        </button>
      </div>
    )

  const send = async () => {
    if (!reason) return
    setBusy(true)
    setError(null)
    try {
      await api.reportSubmission(submissionId, reason, note.trim() || undefined)
      setSent(true)
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="step">
      <Choice
        name="report-reason"
        legend={t('report.why')}
        options={REASONS.map((value) => ({ value, label: t(`report.reasons.${value}`) }))}
        value={reason}
        onChange={setReason}
      />
      <label>
        {t('report.note')}
        <textarea
          rows={3}
          maxLength={1000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <p className="note">{t('report.privacy')}</p>
      <ErrorMessage error={error} />
      <div className="row">
        <button
          type="button"
          className="small-action"
          disabled={busy || !reason}
          onClick={() => void send()}
        >
          {t('report.send')}
        </button>
        <button
          type="button"
          className="small-action"
          disabled={busy}
          onClick={() => setOpen(false)}
        >
          {t('report.cancel')}
        </button>
      </div>
    </div>
  )
}
