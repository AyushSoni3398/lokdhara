import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import type { Prompt } from '../../api/types'
import i18n from '../../i18n'
import { PromptCard } from './PromptStep'

const sentence: Prompt = {
  id: 'p1',
  prompt_type: 'read_sentence',
  text: 'गड़ारे दाअ मेनाअ।',
  text_language_tag: 'unr',
  script_code: 'Deva',
  translation_hi: 'नदी में पानी है।',
  translation_en: 'There is water in the river.',
  image_url: null,
  audio_url: null,
  started_again: false,
}

describe('PromptCard', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('shows what the sentence means in the app language', async () => {
    render(<PromptCard prompt={sentence} />)
    expect(screen.getByText('गड़ारे दाअ मेनाअ।')).toBeInTheDocument()
    expect(screen.getByText('Meaning: There is water in the river.')).toBeInTheDocument()
    await i18n.changeLanguage('hi')
    expect(await screen.findByText('अर्थ: नदी में पानी है।')).toBeInTheDocument()
  })

  it('does not repeat a prompt that is already in the app language', async () => {
    await i18n.changeLanguage('hi')
    const question = { ...sentence, text: 'यह चित्र देखिए।', text_language_tag: 'hi' }
    render(<PromptCard prompt={{ ...question, translation_hi: 'यह चित्र देखिए।' }} />)
    expect(screen.queryByText(/अर्थ:/)).toBeNull()
  })
})
