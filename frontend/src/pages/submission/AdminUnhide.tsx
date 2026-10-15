import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import * as api from '../../api/endpoints'
import type { Restriction } from '../../api/types'
import { ErrorMessage } from '../../components/ErrorMessage'

/** Lets an admin take back a hiding decision, with a reason (ROADMAP M6). */
export function AdminUnhide({
  submissionId,
  flags,
  onChanged,
}: {
  submissionId: string
  flags: Restriction[]
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const [flag, setFlag] = useState<Restriction | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const unhide = async (restriction: Restriction) => {
    setBusy(true)
    setError(null)
    try {
      await api.unhideSubmission(submissionId, restriction, note.trim())
      setFlag(null)
      setNote('')
      onChanged()
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  if (!flag)
    return (
      <div className="row">
        {flags.map((value) => (
          <button key={value} type="button" className="small-action" onClick={() => setFlag(value)}>
            {t('reports.unhide', { reason: t(`restrictions.${value}`) })}
          </button>
        ))}
      </div>
    )
  return (
    <div className="step">
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
          onClick={() => void unhide(flag)}
        >
          {t('reports.unhide', { reason: t(`restrictions.${flag}`) })}
        </button>
        <button
          type="button"
          className="small-action"
          disabled={busy}
          onClick={() => setFlag(null)}
        >
          {t('report.cancel')}
        </button>
      </div>
    </div>
  )
}
