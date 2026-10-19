import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { ScriptWarning } from './ScriptWarning'

describe('ScriptWarning', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('names the chosen script when the text is in another one', () => {
    render(<ScriptWarning text="hoyo" script="Deva" />)
    expect(screen.getByRole('status')).toHaveTextContent('does not seem to be in Devanagari')
  })

  it('stays hidden for text in the chosen script', () => {
    render(<ScriptWarning text="होयो" script="Deva" />)
    expect(screen.queryByRole('status')).toBeNull()
  })
})
