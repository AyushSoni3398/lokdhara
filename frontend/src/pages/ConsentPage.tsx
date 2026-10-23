import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams, useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import * as api from '../api/endpoints'
import type { Attribution, ConsentAnswers, ConsentForm, ConsentMethod, Speaker } from '../api/types'
import { Choice } from '../components/Choice'
import { ErrorMessage } from '../components/ErrorMessage'
import { FormText } from '../components/FormText'
import type { DraftAudio } from '../drafts/types'
import { AudioCapture } from '../recording/AudioCapture'

// docs/CONSENT_AND_DATA_GOVERNANCE.md §3.1: asked one by one, every answer starts as No.
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
  const [answers, setAnswers] = useState<Record<Permission, boolean>>(
    () => Object.fromEntries(PERMISSIONS.map((p) => [p, false])) as Record<Permission, boolean>,
  )
  const [attribution, setAttribution] = useState<Attribution>('pseudonymous')
  const [method, setMethod] = useState<ConsentMethod>('in_app')
  const [paperReference, setPaperReference] = useState('')
  const [evidence, setEvidence] = useState<DraftAudio | undefined>()
  // Under 18: a parent or guardian agrees together with the speaker (Q-L4).
  const [minor, setMinor] = useState(false)
  const [guardian, setGuardian] = useState('')
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

  const yesNo = (permission: Permission) => (
    <Choice
      key={permission}
      name={permission}
      legend={t(`consent.questions.${permission}`)}
      options={[
        { value: 'yes', label: t('consent.yes') },
        { value: 'no', label: t('consent.no') },
      ]}
      value={answers[permission] ? 'yes' : 'no'}
      onChange={(value) => setAnswers({ ...answers, [permission]: value === 'yes' })}
    />
  )

  const missingEvidence = method === 'oral_recorded' && !evidence
  const missingReference = method === 'paper_reference' && !paperReference.trim()
  const missingGuardian = minor && !guardian.trim()
  const canSave =
    answers.allow_store_and_review &&
    !missingEvidence &&
    !missingReference &&
    !missingGuardian &&
    !busy

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const body: ConsentAnswers = {
      consent_form_id: form.id,
      method,
      ...answers,
      attribution_preference: attribution,
      ...(method === 'paper_reference' ? { paper_reference: paperReference.trim() } : {}),
      ...(minor ? { guardian_involved: true, guardian_relationship: guardian.trim() } : {}),
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
        <p className="note">{t('consent.defaultNo')}</p>
        {PERMISSIONS.map(yesNo)}
        {!answers.allow_store_and_review && <p className="note">{t('consent.storeRequired')}</p>}
        <Choice
          name="attribution"
          legend={t('consent.questions.attribution')}
          options={(['pseudonymous', 'name', 'none'] as const).map((value) => ({
            value,
            label: t(`consent.attribution.${value}`),
          }))}
          value={attribution}
          onChange={setAttribution}
        />
        <Choice
          name="minor"
          legend={t('consent.minor.legend')}
          options={[
            { value: 'no', label: t('consent.no') },
            { value: 'yes', label: t('consent.yes') },
          ]}
          value={minor ? 'yes' : 'no'}
          onChange={(value) => setMinor(value === 'yes')}
        />
        {minor && (
          <>
            <p className="note">{t('consent.minor.hint')}</p>
            <label>
              {t('consent.minor.relationship')}
              <input
                value={guardian}
                onChange={(e) => setGuardian(e.target.value)}
                maxLength={60}
                required
              />
            </label>
          </>
        )}
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
        <ErrorMessage error={error} />
        <button type="submit" className="action primary" disabled={!canSave}>
          {t('consent.save')}
        </button>
      </form>
    </section>
  )
}
