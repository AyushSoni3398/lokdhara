import type { Script } from '../api/types'

/**
 * The same rule the server uses (backend/app/text/scripts.py), so the contributor sees the
 * warning while typing instead of only after sending: a text is a mismatch when it has letters
 * but none in the chosen script. Mixed text is normal; "Mixed or other" never warns.
 */
const TAG = /\[[a-z]+\]/g
const WRAPPED = /\[(?:\?|[a-z]{2,3}:)([^[\]\n]*)\]/g
const LETTER = /[^\p{Script=Common}\p{Script=Inherited}]/u

function nagMundari(): RegExp {
  try {
    return new RegExp('\\p{Script=Nag_Mundari}', 'u')
  } catch {
    // Browsers older than Unicode 15 do not know the name; this is its block.
    return /[\u{1E4D0}-\u{1E4FF}]/u
  }
}

const SCRIPTS: Partial<Record<Script, RegExp>> = {
  Deva: /\p{Script=Devanagari}/u,
  Latn: /\p{Script=Latin}/u,
  Nagm: nagMundari(),
}

export function scriptMismatch(text: string, declared: Script): boolean {
  const pattern = SCRIPTS[declared]
  if (!pattern) return false
  const words = text.replace(TAG, ' ').replace(WRAPPED, '$1')
  return LETTER.test(words) && !pattern.test(words)
}
