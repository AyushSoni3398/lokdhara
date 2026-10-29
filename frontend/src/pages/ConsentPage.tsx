import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams, useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import * as api from '../api/endpoints'
import type { ConsentAnswers, ConsentForm, ConsentMethod, Speaker } from '../api/types'
import { Choice } from '../components/Choice'
import { ErrorMessage } from '../components/ErrorMessage'
import { FormText } from '../components/FormText'
import type { DraftAudio } from '../drafts/types'
import { AudioCapture } from '../recording/AudioCapture'

// docs/CONSENT_AND_DATA_GOVERNANCE.md §3.1: everything is listed, and one "I accept" tick
// agrees to all of it (ADR-031). The tick starts empty.
const PERMISSIONS = [
  'allow_store_and_review',
  'allow_research',
  'allow_public_access',
  'allow_ai_training',
  'allow_commercial_use',
  'demographics_consented',
] as const
type Permission = (typeof PERMISSIONS)[number]

/** Only same-site paths, so the `next` parameter cannot send people elsewhere. */
export function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/'
}

export function ConsentPage() {
  const { t, i18n } = useTranslation()
  const { speakerId = '' } = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const [speaker, setSpeaker] = useState<Speaker | null>(null)
  const [form, setForm] = useState<ConsentForm | null>(null)
  const [accepted, setAccepted] = useState(false)
  const [method, setMethod] = useState<ConsentMethod>('in_app')
  const [paperReference, setPaperReference] = useState('')
  const [evidence, setEvidence] = useState<DraftAudio | undefined>()
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const language = i18n.resolvedLanguage ?? 'hi'

  useEffect(() => {
    api.getSpeaker(speakerId).then(setSpeaker, setError)
  }, [speakerId])

  useEffect(() => {
    // The form in the reading language, or the other language if it has none yet.
    api
      .currentConsentForm(language)
      .catch((failure: unknown) => {
        if (failure instanceof ApiError && failure.code === 'consent_form_not_found') {
          return api.currentConsentForm(language === 'hi' ? 'en' : 'hi')
        }
        throw failure
      })
      .then(setForm, setError)
  }, [language])

  if (!form || !speaker) return <ErrorMessage error={error} />

  const missingEvidence = method === 'oral_recorded' && !evidence
  const missingReference = method === 'paper_reference' && !paperReference.trim()
  const canSave = accepted && !missingEvidence && !missingReference && !busy

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const body: ConsentAnswers = {
      consent_form_id: form.id,
      method,
      ...(Object.fromEntries(PERMISSIONS.map((p) => [p, accepted])) as Record<Permission, boolean>),
      // A code instead of the name, the safest credit (CONSENT_AND_DATA_GOVERNANCE.md §3.1).
      attribution_preference: 'pseudonymous',
      ...(method === 'paper_reference' ? { paper_reference: paperReference.trim() } : {}),
    }
    try {
      await api.recordConsent(
        speaker.id,
        body,
        method === 'oral_recorded' ? evidence?.blob : undefined,
      )
      void navigate(safeNext(search.get('next')), { replace: true })
    } catch (failure) {
      setError(failure)
      setBusy(false)
    }
  }

  return (
    <section>
      <h1>{t('consent.title', { code: speaker.speaker_code })}</h1>
      {form.is_test_form && <p className="warning">{t('consent.testForm')}</p>}
      <FormText markdown={form.body_markdown} />
      <form className="form" onSubmit={(event) => void save(event)}>
        <p>{t('consent.listIntro')}</p>
        <ul>
          {PERMISSIONS.map((permission) => (
            <li key={permission}>{t(`consent.uses.${permission}`)}</li>
          ))}
          <li>{t('consent.uses.credit')}</li>
        </ul>
        <p className="note">{t('consent.withdraw')}</p>
        {!speaker.is_self && (
          <Choice
            name="method"
            legend={t('consent.method.legend')}
            options={(['in_app', 'oral_recorded', 'paper_reference'] as const).map((value) => ({
              value,
              label: t(`consent.method.${value}`),
            }))}
            value={method}
            onChange={setMethod}
          />
        )}
        {method === 'oral_recorded' && (
          <>
            <p className="note">{t('consent.oralHint')}</p>
            <AudioCapture value={evidence} onChange={setEvidence} />
          </>
        )}
        {method === 'paper_reference' && (
          <label>
            {t('consent.paperReference')}
            <input value={paperReference} onChange={(e) => setPaperReference(e.target.value)} />
          </label>
        )}
        <label className="inline">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
          />
          {t('consent.accept')}
        </label>
        <ErrorMessage error={error} />
        <button type="submit" className="action primary" disabled={!canSave}>
          {t('consent.save')}
        </button>
      </form>
    </section>
  )
}
