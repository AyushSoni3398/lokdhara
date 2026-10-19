/**
 * Keys of the on-screen Devanagari keyboard, in the order of the varnamala, so people who learnt
 * Hindi at school find letters where they expect them. Vowel signs (matras) and the halant join
 * the letter before them, so "क" + "ि" gives "कि" and "क" + "्" + "ष" gives "क्ष".
 */
export const KEY_ROWS: Record<'letters' | 'signs' | 'numbers', string[][]> = {
  letters: [
    ['अ', 'आ', 'इ', 'ई', 'उ', 'ऊ', 'ऋ', 'ए', 'ऐ', 'ओ', 'औ'],
    ['क', 'ख', 'ग', 'घ', 'ङ', 'च', 'छ', 'ज', 'झ', 'ञ'],
    ['ट', 'ठ', 'ड', 'ढ', 'ण', 'त', 'थ', 'द', 'ध', 'न'],
    ['प', 'फ', 'ब', 'भ', 'म', 'य', 'र', 'ल', 'व'],
    ['श', 'ष', 'स', 'ह', 'ड़', 'ढ़', 'क्ष', 'त्र', 'ज्ञ'],
  ],
  signs: [
    ['ा', 'ि', 'ी', 'ु', 'ू', 'ृ', 'े', 'ै', 'ो', 'ौ'],
    ['ं', 'ँ', 'ः', '्', '़', 'ॅ', 'ॉ', 'ऑ'],
  ],
  numbers: [
    ['०', '१', '२', '३', '४', '५', '६', '७', '८', '९'],
    ['।', '॥', ',', '?', '!', '-', '(', ')', '[', ']'],
  ],
}

/** Combining signs are shown on a dotted circle so they are visible on their own. */
export function keyLabel(key: string): string {
  return /^\p{M}/u.test(key) ? `◌${key}` : key
}

/** Puts `key` in place of the selection; returns the new text and where the cursor goes. */
export function insertAt(
  text: string,
  start: number,
  end: number,
  key: string,
): { text: string; cursor: number } {
  return { text: text.slice(0, start) + key + text.slice(end), cursor: start + key.length }
}

/** Deletes the selection, or the one code point before the cursor (a matra, not the whole syllable). */
export function deleteBack(
  text: string,
  start: number,
  end: number,
): { text: string; cursor: number } {
  if (start !== end) return { text: text.slice(0, start) + text.slice(end), cursor: start }
  if (start === 0) return { text, cursor: 0 }
  const before = Array.from(text.slice(0, start))
  before.pop()
  const kept = before.join('')
  return { text: kept + text.slice(start), cursor: kept.length }
}
