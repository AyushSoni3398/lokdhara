import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { ApiError } from '../api/client'
import * as api from '../api/endpoints'
import type { Speaker } from '../api/types'
import { ErrorMessage } from '../components/ErrorMessage'

/** Finds the signed-in user's own speaker profile, making it the first time. */
async function ownSpeaker(): Promise<Speaker> {
  const own = (await api.listSpeakers()).find((s) => s.is_self)
  if (own) return own
  try {
    return await api.createSpeaker(true)
  } catch (failure) {
    if (failure instanceof ApiError && failure.code === 'self_speaker_exists') {
      const made = (await api.listSpeakers()).find((s) => s.is_self)
      if (made) return made
    }
    throw failure
  }
}

/**
 * "New recording" always records the signed-in user's own voice or text (docs/USER_FLOWS.md F1),
 * so there is no "whose voice?" question: go straight to consent or the recording.
 */
export function StartContributionPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    ownSpeaker().then((speaker) => {
      // Consent comes first, so nobody is recorded before agreeing (docs/USER_FLOWS.md F1 note 2).
      const next = `/contribute/${speaker.id}/new`
      void navigate(
        speaker.has_active_consent
          ? next
          : `/speakers/${speaker.id}/consent?next=${encodeURIComponent(next)}`,
        { replace: true },
      )
    }, setError)
  }, [navigate])

  return <ErrorMessage error={error} />
}
