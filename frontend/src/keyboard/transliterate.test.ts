import { describe, expect, it } from 'vitest'

import { transliterate } from './transliterate'

describe('transliterate', () => {
  it.each([
    ['naam', 'नाम'],
    ['kitaab', 'किताब'],
    ['hindee', 'हिंदी'.replace('ं', 'न्')],
    ['hiMdI', 'हिंदी'],
    ['bhaarat', 'भारत'],
    ['kShetra', 'क्षेत्र'],
    ['paanii', 'पानी'],
    ['aam', 'आम'],
    ['ghar', 'घर'],
    ['TamaaTar', 'टमाटर'],
    ['maa.n', 'माँ'],
    ['ek do teen', 'एक दो तीन'],
    ['ho gayaa.', 'हो गया।'],
    ['riShi', 'ऋषि'],
    ['bachchaa', 'बच्चा'],
    // Two consonants join; type the "a" between them to keep them apart.
    ['laRakaa', 'लड़का'],
  ])('%s → %s', (roman, devanagari) => {
    expect(transliterate(roman)).toBe(devanagari)
  })

  it('keeps digits and punctuation', () => {
    expect(transliterate('12, 3?')).toBe('12, 3?')
  })
})
