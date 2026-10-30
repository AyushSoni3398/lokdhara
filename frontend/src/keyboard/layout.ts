/**
 * Every key of an on-screen keyboard, shown all at once (no pages to switch). Each row fills the
 * same number of columns, so the keys share the phone's width evenly and nothing wraps.
 */
export type Keyboard = { columns: number; rows: string[][] }

/**
 * Devanagari in the order of the varnamala, so people who learnt Hindi at school find letters
 * where they expect them. Each matra sits under its vowel (ा under आ) and the halant under अ.
 * Vowel signs and the halant join the letter before them, so "क" + "ि" gives "कि" and
 * "क" + "्" + "ष" gives "क्ष".
 */
export const DEVANAGARI: Keyboard = {
  columns: 11,
  rows: [
    ['अ', 'आ', 'इ', 'ई', 'उ', 'ऊ', 'ऋ', 'ए', 'ऐ', 'ओ', 'औ'],
    ['्', 'ा', 'ि', 'ी', 'ु', 'ू', 'ृ', 'े', 'ै', 'ो', 'ौ'],
    ['क', 'ख', 'ग', 'घ', 'ङ', 'च', 'छ', 'ज', 'झ', 'ञ', 'ं'],
    ['ट', 'ठ', 'ड', 'ढ', 'ण', 'त', 'थ', 'द', 'ध', 'न', 'ँ'],
    ['प', 'फ', 'ब', 'भ', 'म', 'य', 'र', 'ल', 'व', 'श', 'ः'],
    ['ष', 'स', 'ह', 'ड़', 'ढ़', 'क्ष', 'त्र', 'ज्ञ', 'ऑ', 'ॉ', '़'],
    ['०', '१', '२', '३', '४', '५', '६', '७', '८', '९', '।'],
    [',', '.', '?', '!', '-', "'", '"', '(', ')', ':', '॥'],
  ],
}

/** Code points `from` to `to` of a Unicode block, in order. */
function block(from: number, to: number): string[] {
  return Array.from({ length: to - from + 1 }, (_, i) => String.fromCodePoint(from + i))
}

/**
 * Mundari Bani (Nag Mundari, Unicode 15): every letter, sign and digit of the script. It has no
 * matras: each vowel is a letter of its own and leads a group of letters (O, A, I, U, E), and the
 * rows follow those groups in the script's own order.
 */
export const NAG_MUNDARI: Keyboard = {
  columns: 10,
  rows: [
    block(0x1e4d0, 0x1e4d9), // O OP OL OY ONG, A AJ AB ANY AH
    block(0x1e4da, 0x1e4e3), // I IS IDD IT IH, U UC UD UK UR
    block(0x1e4e4, 0x1e4ed), // E ENN EG EM EN ETT ELL, signs ojod muhor toyor
    block(0x1e4f0, 0x1e4f9), // digits 0 to 9
    [...block(0x1e4ee, 0x1e4ef), '।', '.', ',', '?', '!', '-', '(', ')'], // signs ikir sutuh
  ],
}

/** Names read out for Mundari Bani keys, whose letters few phones can say yet. */
const NAG_MUNDARI_NAMES = [
  ...'o op ol oy ong a aj ab any ah i is idd it ih u uc ud uk ur e enn eg em en ett ell'.split(' '),
  ...'ojod muhor toyor ikir sutuh'.split(' ').map((name) => `${name} sign`),
  ...'0 1 2 3 4 5 6 7 8 9'.split(' '),
]

export function keyName(key: string): string | undefined {
  const index = (key.codePointAt(0) ?? 0) - 0x1e4d0
  return index >= 0 && index < NAG_MUNDARI_NAMES.length ? NAG_MUNDARI_NAMES[index] : undefined
}

/**
 * Combining signs are shown on a dotted circle so they are visible on their own. Mundari Bani
 * signs are shown alone: its font has no dotted circle, and the pair would draw as empty boxes.
 */
export function keyLabel(key: string): string {
  return /^\p{M}/u.test(key) && keyName(key) === undefined ? `◌${key}` : key
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
