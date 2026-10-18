import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import * as api from '../api/endpoints'
import type { MfaSetup } from '../api/types'
import { useAuth, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'

/** Turning on two-step sign-in with an authenticator app (docs/ACCESS_CONTROL.md §4). */
export function TwoStepPage() {
  const { t } = useTranslation()
  const session = useSession()
  const { refresh } = useAuth()
  const navigate = useNavigate()
  const [setup, setSetup] = useState<MfaSetup | null>(null)
  const [code, setCode] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  const start = () => run(async () => setSetup(await api.startMfaSetup()))
  const confirm = (event: FormEvent) => {
    event.preventDefault()
    return run(async () => setRecoveryCodes((await api.confirmMfa(code)).recovery_codes))
  }
  const finish = () =>
    run(async () => {
      await refresh()
      void navigate('/', { replace: true })
    })

  if (recoveryCodes) {
    return (
      <section>
        <h1>{t('twoStep.codesTitle')}</h1>
        <p className="warning">{t('twoStep.codesIntro')}</p>
        <ul className="recovery-codes">
          {recoveryCodes.map((c) => (
            <li key={c}>
              <code>{c}</code>
            </li>
          ))}
        </ul>
        <ErrorMessage error={error} />
        <button
          type="button"
          className="action primary"
          disabled={busy}
          onClick={() => void finish()}
        >
          {t('twoStep.done')}
        </button>
      </section>
    )
  }

  if (session.mfa_enabled) {
    return (
      <section>
        <h1>{t('twoStep.title')}</h1>
        <p className="note">{t('twoStep.alreadyOn')}</p>
      </section>
    )
  }

  return (
    <section>
      <h1>{t('twoStep.title')}</h1>
      {session.mfa_setup_required && <p className="warning">{t('twoStep.required')}</p>}
      <p className="note">{t('twoStep.intro')}</p>
      {!setup ? (
        <button
          type="button"
          className="action primary"
          disabled={busy}
          onClick={() => void start()}
        >
          {t('twoStep.start')}
        </button>
      ) : (
        <form className="form" onSubmit={(event) => void confirm(event)}>
          <p>{t('twoStep.scan')}</p>
          <img
            className="qr"
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(setup.qr_svg)}`}
            alt={t('twoStep.qrAlt')}
            width={220}
            height={220}
          />
          <p className="note">
            {t('twoStep.manual')} <code className="secret">{setup.secret}</code>
          </p>
          <label>
            {t('twoStep.codeLabel')}
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="one-time-code"
              inputMode="numeric"
              pattern="[0-9 ]{6,7}"
              maxLength={7}
              required
            />
          </label>
          <button type="submit" className="action primary" disabled={busy}>
            {t('twoStep.confirm')}
          </button>
        </form>
      )}
      <ErrorMessage error={error} />
    </section>
  )
}
