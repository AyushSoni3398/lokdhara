import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import * as api from '../api/endpoints'
import type { AgeBand, Speaker } from '../api/types'
import { ErrorMessage } from '../components/ErrorMessage'

const AGE_BANDS: AgeBand[] = ['under_18', '18-29', '30-44', '45-59', '60+', 'undisclosed']
// BCP 47 tags; the server keeps whatever is chosen (docs/DATA_DICTIONARY.md).
const LANGUAGES = ['unr', 'hi', 'sck', 'sat', 'kru', 'en'] as const

interface Fields {
  fullName: string
  contact: string
  village: string
  notes: string | null
  dialect: string
  region: string
  ageBand: AgeBand | ''
  gender: string
  firstLanguage: string
}

/** The signed-in person's own speaker profile, made once if it does not exist yet. */
async function ownSpeaker(): Promise<Speaker> {
  const own = (await api.listSpeakers()).find((s) => s.is_self)
  if (own) return own
  try {
    return await api.createSpeaker(true)
  } catch (failure) {
    if (failure instanceof ApiError && failure.code === 'self_speaker_exists') {
      const again = (await api.listSpeakers()).find((s) => s.is_self)
      if (again) return again
    }
    throw failure
  }
}

const orNull = (value: string) => value.trim() || null

/**
 * Details asked once, at sign-up, and reused for every recording (ADR-028): name, phone and
 * village are restricted identity; age group, area and languages are kept only with consent.
 */
export function ProfilePage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [search] = useSearchParams()
  const setup = search.get('setup') === '1'
  const [speaker, setSpeaker] = useState<Speaker | null>(null)
  const [fields, setFields] = useState<Fields | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const own = await ownSpeaker()
        if (cancelled) return
        if (!own.has_active_consent) {
          // Consent comes first: it decides whether age, area and languages may be kept.
          const back = `/account/profile${setup ? '?setup=1' : ''}`
          void navigate(`/speakers/${own.id}/consent?next=${encodeURIComponent(back)}`, {
            replace: true,
          })
          return
        }
        const identity = await api.getSpeakerIdentity(own.id)
        if (cancelled) return
        setSpeaker(own)
        setFields({
          fullName: identity.full_name ?? '',
          contact: identity.contact ?? '',
          village: identity.village ?? '',
          notes: identity.notes ?? null,
          dialect: own.dialect_label ?? '',
          region: own.region_coarse ?? '',
          ageBand: own.age_band ?? '',
          gender: own.gender_self_described ?? '',
          firstLanguage: own.first_language ?? '',
        })
      } catch (failure) {
        if (!cancelled) setError(failure)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [navigate, setup])

  if (!speaker || !fields) return <ErrorMessage error={error} />

  const demographics = speaker.demographics_consented === true
  const set = (changes: Partial<Fields>) => {
    setSaved(false)
    setFields({ ...fields, ...changes })
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.putSpeakerIdentity(speaker.id, {
        full_name: orNull(fields.fullName),
        contact: orNull(fields.contact),
        village: orNull(fields.village),
        // Notes are the team's; keep them as they are.
        notes: fields.notes,
      })
      const updated = await api.updateSpeaker(speaker.id, {
        dialect_label: orNull(fields.dialect),
        ...(demographics
          ? {
              age_band: fields.ageBand || null,
              gender_self_described: orNull(fields.gender),
              first_language: fields.firstLanguage || null,
              region_coarse: orNull(fields.region),
            }
          : {}),
      })
      setSpeaker(updated)
      if (setup) void navigate('/', { replace: true })
      else setSaved(true)
    } catch (failure) {
      setError(failure)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h1>{t(setup ? 'profile.setupTitle' : 'profile.title')}</h1>
      <p className="note">{t('profile.intro')}</p>
      <form className="form" onSubmit={(event) => void save(event)}>
        <h2>{t('profile.private')}</h2>
        <p className="note">{t('profile.privateHint')}</p>
        <label>
          {t('profile.fullName')}
          <input
            value={fields.fullName}
            onChange={(e) => set({ fullName: e.target.value })}
            maxLength={200}
            autoComplete="name"
          />
        </label>
        <label>
          {t('profile.contact')}
          <input
            type="tel"
            value={fields.contact}
            onChange={(e) => set({ contact: e.target.value })}
            maxLength={200}
            autoComplete="tel"
            inputMode="tel"
          />
          <small>{t('profile.contactHint')}</small>
        </label>
        <label>
          {t('profile.village')}
          <input
            value={fields.village}
            onChange={(e) => set({ village: e.target.value })}
            maxLength={200}
          />
        </label>

        <h2>{t('profile.aboutVoice')}</h2>
        <label>
          {t('details.dialect')}
          <input
            value={fields.dialect}
            onChange={(e) => set({ dialect: e.target.value })}
            maxLength={100}
          />
          <small>{t('profile.reusedHint')}</small>
        </label>
        {demographics ? (
          <>
            <label>
              {t('details.region')}
              <input
                value={fields.region}
                onChange={(e) => set({ region: e.target.value })}
                maxLength={100}
              />
              <small>{t('details.regionHint')}</small>
            </label>
            <label>
              {t('profile.ageBand')}
              <select
                value={fields.ageBand}
                onChange={(e) => set({ ageBand: e.target.value as AgeBand | '' })}
              >
                <option value="">{t('profile.notSaid')}</option>
                {AGE_BANDS.map((band) => (
                  <option key={band} value={band}>
                    {t(`profile.ages.${band}`)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t('profile.gender')}
              <input
                value={fields.gender}
                onChange={(e) => set({ gender: e.target.value })}
                maxLength={60}
              />
              <small>{t('profile.genderHint')}</small>
            </label>
            <label>
              {t('profile.firstLanguage')}
              <select
                value={fields.firstLanguage}
                onChange={(e) => set({ firstLanguage: e.target.value })}
              >
                <option value="">{t('profile.notSaid')}</option>
                {LANGUAGES.map((tag) => (
                  <option key={tag} value={tag}>
                    {t(`profile.languages.${tag}`)}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : (
          <p className="note">
            {t('profile.noDemographics')}{' '}
            <Link to={`/speakers/${speaker.id}/consent?next=/account/profile`}>
              {t('profile.changeConsent')}
            </Link>
          </p>
        )}
        <ErrorMessage error={error} />
        {saved && <p role="status">{t('profile.saved')}</p>}
        <button type="submit" className="action primary" disabled={busy}>
          {t(setup ? 'profile.finish' : 'profile.save')}
        </button>
        {setup && (
          <Link to="/" className="action">
            {t('profile.later')}
          </Link>
        )}
      </form>
    </section>
  )
}
