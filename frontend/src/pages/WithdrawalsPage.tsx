import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import * as api from '../api/endpoints'
import type { Speaker, Withdrawal } from '../api/types'
import { ErrorMessage } from '../components/ErrorMessage'

/** What a withdrawal request means for the person who asked, in plain words. */
export function withdrawalState(request: Withdrawal): string {
  if (request.status === 'verified' && request.requested_scope !== 'narrow')
    return request.erased_at ? 'deleted' : 'deleting'
  return request.status
}

/**
 * Taking recordings back (docs/USER_FLOWS.md F3): the requests someone made, and a way to take
 * back everything of a speaker they act for. One item is taken back from its own page.
 */
export function WithdrawalsPage() {
  const { t, i18n } = useTranslation()
  const [requests, setRequests] = useState<Withdrawal[] | null>(null)
  const [speakers, setSpeakers] = useState<Speaker[]>([])
  const [error, setError] = useState<unknown>(null)
  const date = (iso: string) => new Date(iso).toLocaleDateString(i18n.resolvedLanguage)

  const reload = useCallback(() => {
    api.listMyWithdrawals().then(setRequests, setError)
    api.listSpeakers().then(setSpeakers, setError)
  }, [])
  useEffect(reload, [reload])

  const active = speakers.filter((speaker) => speaker.status === 'active')

  return (
    <section>
      <p>
        <Link to="/submissions">{t('submission.back')}</Link>
      </p>
      <h1>{t('withdrawal.title')}</h1>
      <p className="note">{t('withdrawal.intro')}</p>
      <ErrorMessage error={error} />

      <h2>{t('withdrawal.myRequests')}</h2>
      {requests?.length === 0 && <p className="note">{t('withdrawal.none')}</p>}
      <ul className="list">
        {requests?.map((request) => (
          <li key={request.id} className="list-item">
            <strong>{t(`withdrawal.scopes.${request.requested_scope}`)}</strong>
            <span>
              {request.speaker_code} · {date(request.received_at)}
            </span>
            <span className="status">{t(`withdrawal.states.${withdrawalState(request)}`)}</span>
          </li>
        ))}
      </ul>

      {active.map((speaker) => (
        <WithdrawSpeaker key={speaker.id} speaker={speaker} onSent={reload} />
      ))}
    </section>
  )
}

function WithdrawSpeaker({ speaker, onSent }: { speaker: Speaker; onSent: () => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const who = speaker.is_self ? t('withdrawal.myself') : speaker.speaker_code

  const send = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.requestWithdrawal({
        scope: 'full',
        speaker_id: speaker.id,
        note: note.trim() || undefined,
      })
      setOpen(false)
      onSent()
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="step">
      <h2>{t('withdrawal.everythingOf', { who })}</h2>
      <p className="note">{t('withdrawal.fullIntro')}</p>
      <p>
        <Link to={`/speakers/${speaker.id}/consent`}>{t('withdrawal.changeConsent')}</Link>
      </p>
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
          {t('withdrawal.fullStart', { who })}
        </button>
      )}
      <ErrorMessage error={error} />
    </div>
  )
}
