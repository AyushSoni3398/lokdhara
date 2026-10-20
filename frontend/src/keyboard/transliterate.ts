/**
 * Turns Roman letters into Devanagari the way people already type Hindi in chat messages:
 * "naam" → "नाम", "kitaab" → "किताब", "kShetra" → "क्षेत्र". Capitals mark the retroflex
 * letters (T, Th, D, Dh, N) and ṣ (Sh); "M" is the anusvara, ".n" the chandrabindu, "H" the
 * visarga. Anything else (digits, punctuation, spaces) is kept as it is.
 */
const CONSONANTS: [string, string][] = [
  ['kSh', 'क्ष'],
  ['ksh', 'क्ष'],
  ['GY', 'ज्ञ'],
  ['tr', 'त्र'],
  ['chh', 'छ'],
  ['kh', 'ख'],
  ['gh', 'घ'],
  ['ng', 'ङ'],
  ['ch', 'च'],
  ['jh', 'झ'],
  ['ny', 'ञ'],
  ['Th', 'ठ'],
  ['Dh', 'ढ'],
  ['th', 'थ'],
  ['dh', 'ध'],
  ['ph', 'फ'],
  ['bh', 'भ'],
  ['Sh', 'ष'],
  ['sh', 'श'],
  ['Rh', 'ढ़'],
  ['R', 'ड़'],
  ['k', 'क'],
  ['g', 'ग'],
  ['c', 'च'],
  ['j', 'ज'],
  ['T', 'ट'],
  ['D', 'ड'],
  ['N', 'ण'],
  ['t', 'त'],
  ['d', 'द'],
  ['n', 'न'],
  ['p', 'प'],
  ['f', 'फ़'],
  ['b', 'ब'],
  ['m', 'म'],
  ['y', 'य'],
  ['r', 'र'],
  ['l', 'ल'],
  ['v', 'व'],
  ['w', 'व'],
  ['s', 'स'],
  ['h', 'ह'],
  ['z', 'ज़'],
  ['q', 'क़'],
  ['x', 'क्स'],
]
// Roman vowel → [letter on its own, sign after a consonant ('' for the inherent "a")].
const VOWELS: [string, string, string][] = [
  ['aa', 'आ', 'ा'],
  ['ai', 'ऐ', 'ै'],
  ['au', 'औ', 'ौ'],
  ['ee', 'ई', 'ी'],
  ['ii', 'ई', 'ी'],
  ['oo', 'ऊ', 'ू'],
  ['uu', 'ऊ', 'ू'],
  ['ri', 'ऋ', 'ृ'],
  ['A', 'आ', 'ा'],
  ['I', 'ई', 'ी'],
  ['U', 'ऊ', 'ू'],
  ['a', 'अ', ''],
  ['i', 'इ', 'ि'],
  ['u', 'उ', 'ु'],
  ['e', 'ए', 'े'],
  ['o', 'ओ', 'ो'],
]
const MARKS: [string, string][] = [
  ['.n', 'ँ'],
  ['M', 'ं'],
  ['H', 'ः'],
  ['.', '।'],
]
const HALANT = '्'

function match<T extends [string, ...string[]]>(
  table: T[],
  text: string,
  at: number,
): T | undefined {
  return table.find(([roman]) => text.startsWith(roman, at))
}

export function transliterate(roman: string): string {
  let out = ''
  let i = 0
  let afterConsonant = false
  while (i < roman.length) {
    const vowel = match(VOWELS, roman, i)
    // "ri" after a consonant is r + i (as in "kitaabri"), except at the start of a word.
    if (vowel && !(afterConsonant && vowel[0] === 'ri')) {
      out += afterConsonant ? vowel[2] : vowel[1]
      i += vowel[0].length
      afterConsonant = false
      continue
    }
    const consonant = match(CONSONANTS, roman, i)
    if (consonant) {
      if (afterConsonant) out += HALANT // two consonants in a row join
      out += consonant[1]
      i += consonant[0].length
      afterConsonant = true
      continue
    }
    const mark = match(MARKS, roman, i)
    if (mark) {
      out += mark[1]
      i += mark[0].length
    } else {
      out += roman[i]
      i += 1
    }
    afterConsonant = false
  }
  return out
}
