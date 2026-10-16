import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import * as api from '../api/endpoints'
import type { ReceivedVia, Speaker, Withdrawal, WithdrawalScope } from '../api/types'
import { hasRole, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'
import { withdrawalState } from './WithdrawalsPage'

const SCOPES: WithdrawalScope[] = ['full', 'specific_items', 'narrow']
const VIA: ReceivedVia[] = ['facilitator', 'phone', 'in_person', 'email', 'in_app']

/**
 * Admins carry out withdrawal requests (docs/USER_FLOWS.md F3): log one that came by phone or in
 * person, check who asked, then accept or refuse it, and close it once it is done.
 */
export function AdminWithdrawalsPage() {
  const { t } = useTranslation()
  const isAdmin = hasRole(useSession(), 'admin')
  const [openOnly, setOpenOnly] = useState(true)
  const [requests, setRequests] = useState<Withdrawal[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (isAdmin) api.listWithdrawalQueue(openOnly).then(setRequests, setError)
  }, [isAdmin, openOnly])

  if (!isAdmin) return <p className="note">{t('jobs.adminOnly')}</p>

  const changed = (updated: Withdrawal) =>
    setRequests((current) => {
      const rest = current?.filter((r) => r.id !== updated.id) ?? []
      return openOnly && updated.completed_at ? rest : [updated, ...rest]
    })

  return (
    <section>
      <h1>{t('adminWithdrawals.title')}</h1>
      <p className="note">{t('adminWithdrawals.intro')}</p>
      <LogRequest onLogged={changed} />
      <ErrorMessage error={error} />
      <label className="inline">
        <input
          type="checkbox"
          checked={!openOnly}
          onChange={(e) => setOpenOnly(!e.target.checked)}
        />
        {t('adminWithdrawals.showClosed')}
      </label>
      {requests?.length === 0 && <p className="note">{t('adminWithdrawals.none')}</p>}
      <ul className="list">
        {requests?.map((request) => (
          <RequestCard key={request.id} request={request} onChange={changed} />
        ))}
      </ul>
    </section>
  )
}

function LogRequest({ onLogged }: { onLogged: (request: Withdrawal) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [speakers, setSpeakers] = useState<Speaker[]>([])
  const [scope, setScope] = useState<WithdrawalScope>('full')
  const [speakerId, setSpeakerId] = useState('')
  const [submissionId, setSubmissionId] = useState('')
  const [via, setVia] = useState<ReceivedVia>('facilitator')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (open)
      api
        .listAllSpeakers()
        .then((all) => setSpeakers(all.filter((s) => s.status !== 'withdrawn')), setError)
  }, [open])

  if (!open)
    return (
      <p>
        <button type="button" className="small-action" onClick={() => setOpen(true)}>
          {t('adminWithdrawals.log')}
        </button>
      </p>
    )

  const item = scope === 'specific_items'
  const ready = item ? submissionId.trim() !== '' : speakerId !== ''
  const send = async () => {
    setBusy(true)
    setError(null)
    try {
      onLogged(
        await api.requestWithdrawal({
          scope,
          ...(item ? { submission_id: submissionId.trim() } : { speaker_id: speakerId }),
          received_via: via,
          note: note.trim() || undefined,
        }),
      )
      setOpen(false)
      setSubmissionId('')
      setNote('')
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="step"
      onSubmit={(event) => {
        event.preventDefault()
        void send()
      }}
    >
      <h2>{t('adminWithdrawals.log')}</h2>
      <p className="note">{t('adminWithdrawals.logIntro')}</p>
      <label>
        {t('adminWithdrawals.scope')}
        <select value={scope} onChange={(e) => setScope(e.target.value as WithdrawalScope)}>
          {SCOPES.map((value) => (
            <option key={value} value={value}>
              {t(`withdrawal.scopes.${value}`)}
            </option>
          ))}
        </select>
      </label>
      {item ? (
        <label>
          {t('adminWithdrawals.submissionId')}
          <input value={submissionId} onChange={(e) => setSubmissionId(e.target.value)} />
        </label>
      ) : (
        <label>
          {t('adminWithdrawals.speaker')}
          <select value={speakerId} onChange={(e) => setSpeakerId(e.target.value)}>
            <option value="">{t('adminWithdrawals.chooseSpeaker')}</option>
            {speakers.map((speaker) => (
              <option key={speaker.id} value={speaker.id}>
                {speaker.speaker_code}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        {t('adminWithdrawals.receivedVia')}
        <select value={via} onChange={(e) => setVia(e.target.value as ReceivedVia)}>
          {VIA.map((value) => (
            <option key={value} value={value}>
              {t(`adminWithdrawals.via.${value}`)}
            </option>
          ))}
        </select>
      </label>
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
        <button type="submit" className="small-action" disabled={busy || !ready}>
          {t('adminWithdrawals.logButton')}
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
    </form>
  )
}

function RequestCard({
  request,
  onChange,
}: {
  request: Withdrawal
  onChange: (request: Withdrawal) => void
}) {
  const { t, i18n } = useTranslation()
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const date = (iso: string) => new Date(iso).toLocaleDateString(i18n.resolvedLanguage)
  const narrow = request.requested_scope === 'narrow'
  const waiting = request.status === 'received'
  const closable = request.status === 'verified' && (narrow || request.erased_at !== null)

  const decide = async (decision: 'verify' | 'reject' | 'complete') => {
    // Accepting deletes files and texts for good, so it asks once more.
    if (decision === 'verify' && !narrow && !window.confirm(t('adminWithdrawals.verifyConfirm')))
      return
    setBusy(true)
    setError(null)
    try {
      onChange(await api.decideWithdrawal(request.id, decision, note.trim()))
      setNote('')
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="list-item">
      <strong>
        {t(`withdrawal.scopes.${request.requested_scope}`)} · {request.speaker_code}
      </strong>
      {request.submission_id && (
        <Link to={`/submissions/${request.submission_id}`}>{t('adminWithdrawals.openItem')}</Link>
      )}
      <span className="note">
        {t('adminWithdrawals.received', {
          date: date(request.received_at),
          via: t(`adminWithdrawals.via.${request.received_via}`),
        })}
      </span>
      <span className="status">{t(`withdrawal.states.${withdrawalState(request)}`)}</span>
      {request.note && <p className="user-text">{request.note}</p>}
      {request.actions_taken && request.actions_taken.length > 0 && (
        <ul>
          {request.actions_taken.map((entry) => (
            <li key={`${entry.action}-${entry.at}`}>
              {t(`adminWithdrawals.actions.${entry.action}`, { defaultValue: entry.action })} ·{' '}
              {date(entry.at)}
              {entry.note && <p className="user-text">{entry.note}</p>}
            </li>
          ))}
        </ul>
      )}
      {waiting && narrow && (
        <p className="note">
          {t('adminWithdrawals.narrowFirst')}{' '}
          <Link to={`/speakers/${request.speaker_id}/consent`}>
            {t('adminWithdrawals.consentPage')}
          </Link>
        </p>
      )}
      {(waiting || closable) && (
        <label>
          {t(waiting ? 'adminWithdrawals.checkNote' : 'adminWithdrawals.closeNote')}
          <textarea
            rows={2}
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      )}
      <ErrorMessage error={error} />
      {waiting && (
        <div className="row">
          <button
            type="button"
            className="small-action"
            disabled={busy || !note.trim()}
            onClick={() => void decide('verify')}
          >
            {t('adminWithdrawals.verify')}
          </button>
          <button
            type="button"
            className="small-action"
            disabled={busy || !note.trim()}
            onClick={() => void decide('reject')}
          >
            {t('adminWithdrawals.reject')}
          </button>
        </div>
      )}
      {closable && (
        <button
          type="button"
          className="small-action"
          disabled={busy || !note.trim()}
          onClick={() => void decide('complete')}
        >
          {t('adminWithdrawals.complete')}
        </button>
      )}
    </li>
  )
}
