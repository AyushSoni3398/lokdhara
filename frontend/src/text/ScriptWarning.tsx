import { useTranslation } from 'react-i18next'

import type { Script } from '../api/types'
import { scriptMismatch } from './scripts'

/** A gentle note under a text box; the text is never changed or blocked. */
export function ScriptWarning({
  text,
  script,
  canChoose = true,
}: {
  text: string
  script: Script
  /** Whether a script choice is shown above the text box. */
  canChoose?: boolean
}) {
  const { t } = useTranslation()
  if (!scriptMismatch(text, script)) return null
  return (
    <p className="status waiting" role="status">
      {t(canChoose ? 'text.scriptMismatch' : 'submission.scriptMismatch', {
        script: t(`scripts.${script}`),
      })}
    </p>
  )
}
