import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { ApiError } from '../api/client'
import * as api from '../api/endpoints'
import type { Speaker } from '../api/types'
import { ErrorMessage } from '../components/ErrorMessage'

/**
 * "Whose voice or text?" (docs/USER_FLOWS.md F1), shown only to facilitators and admins, who
 * record other people as part of their job (Q-G12).
 */
export function ChooseSpeakerPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [speakers, setSpeakers] = useState<Speaker[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    api.listSpeakers().then(setSpeakers, setError)
  }, [])

  const go = (speaker: Speaker) => {
    // Consent comes first, so nobody is recorded before agreeing (docs/USER_FLOWS.md F1 note 2).
    const next = `/contribute/${speaker.id}/new`
    void navigate(
      speaker.has_active_consent
        ? next
        : `/speakers/${speaker.id}/consent?next=${encodeURIComponent(next)}`,
    )
  }

  const create = async (forSelf: boolean) => {
    setError(null)
    try {
      go(await api.createSpeaker(forSelf))
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === 'self_speaker_exists') {
        const own = (await api.listSpeakers()).find((s) => s.is_self)
        if (own) return go(own)
      }
      setError(failure)
    }
  }

  if (!speakers) return <ErrorMessage error={error} />
  const self = speakers.find((s) => s.is_self)
  const others = speakers.filter((s) => !s.is_self && s.status === 'active')

  return (
    <section>
      <h1>{t('speaker.title')}</h1>
      <div className="actions">
        <button
          type="button"
          className="action primary"
          onClick={() => (self ? go(self) : void create(true))}
        >
          <span aria-hidden="true">🙋</span> {t('speaker.myself')}
        </button>
        <button type="button" className="action" onClick={() => void create(false)}>
          <span aria-hidden="true">➕</span> {t('speaker.newPerson')}
        </button>
      </div>
      {others.length > 0 && (
        <>
          <h2>{t('speaker.registered')}</h2>
          <ul className="list">
            {others.map((speaker) => (
              <li key={speaker.id}>
                <button type="button" className="list-item" onClick={() => go(speaker)}>
                  <strong>{speaker.speaker_code}</strong>
                  <span>
                    {speaker.has_active_consent
                      ? t('speaker.hasConsent')
                      : t('speaker.needsConsent')}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      <ErrorMessage error={error} />
    </section>
  )
}
