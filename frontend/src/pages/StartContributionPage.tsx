import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { ApiError } from '../api/client'
import * as api from '../api/endpoints'
import type { Speaker } from '../api/types'
import { hasRole, useSession } from '../auth/session'
import { ErrorMessage } from '../components/ErrorMessage'
import { ChooseSpeakerPage } from './ChooseSpeakerPage'

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
 * "New recording" (docs/USER_FLOWS.md F1). Facilitators and admins choose whose voice it is,
 * since recording other people is their job (Q-G12). Everyone else records their own voice or
 * text, so they go straight to consent or the recording.
 */
export function StartContributionPage() {
  const session = useSession()
  return hasRole(session, 'facilitator', 'admin') ? <ChooseSpeakerPage /> : <OwnVoice />
}

function OwnVoice() {
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
