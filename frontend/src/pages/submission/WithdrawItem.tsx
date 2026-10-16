import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import * as api from '../../api/endpoints'
import { ErrorMessage } from '../../components/ErrorMessage'

/** Asks for one sent item to be taken back; an admin checks the request (F3). */
export function WithdrawItem({ submissionId }: { submissionId: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<unknown>(null)

  if (sent)
    return (
      <p className="note" role="status">
        {t('withdrawal.sent')} <Link to="/withdrawals">{t('withdrawal.myRequests')}</Link>
      </p>
    )

  const send = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.requestWithdrawal({
        scope: 'specific_items',
        submission_id: submissionId,
        note: note.trim() || undefined,
      })
      setSent(true)
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="step">
      <p className="note">{t('withdrawal.itemIntro')}</p>
      {open ? (
        <>
          <p className="note">{t('withdrawal.copies')}</p>
          <label>
            {t('withdrawal.note')}
            <textarea
              rows={2}
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <ErrorMessage error={error} />
          <div className="row">
            <button
              type="button"
              className="small-action"
              disabled={busy}
              onClick={() => void send()}
            >
              {t('withdrawal.send')}
            </button>
            <button
              type="button"
              className="small-action"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              {t('withdrawal.cancel')}
            </button>
          </div>
        </>
      ) : (
        <button type="button" className="small-action" onClick={() => setOpen(true)}>
          {t('withdrawal.itemStart')}
        </button>
      )}
    </div>
  )
}
