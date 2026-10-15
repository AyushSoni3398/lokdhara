import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, SESSION } from '../test/fakeServer'
import { renderApp } from '../test/render'

const RESEARCHER = { ...SESSION, roles: [{ role: 'researcher', scope: null }] }
const ITEM = {
  id: 'sub1',
  title: 'River story',
  kind: 'audio_text',
  content_type: 'story',
  recording_mode: 'free',
  language_tag: 'unr',
  dialect_label: 'Hasada',
  region_coarse: null,
  submitted_at: '2026-10-14T10:05:00Z',
  restriction_flags: [],
  duration_ms: 42400,
  quality_flags: ['very_quiet'],
  text_preview: 'यह एक परीक्षण वाक्य है।',
  text_script: 'Deva',
  text_status: 'unverified',
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('catalogue', () => {
  it('lists items with their text marked unverified and searches with filters', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: RESEARCHER }),
      'GET /catalogue(\\?.*)?': () => ({ body: { items: [ITEM], next_cursor: null } }),
    })
    renderApp('/catalogue')

    const link = await screen.findByRole('link', { name: 'River story' })
    expect(link).toHaveAttribute('href', '/submissions/sub1')
    expect(screen.getByText('Audio and text · Story · 42 seconds · Hasada')).toBeInTheDocument()
    expect(
      screen.getByText('Written by the contributor, not checked by anyone'),
    ).toBeInTheDocument()
    expect(screen.getByText('Audio notes: very quiet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Words in the title or text'), ' नदी ')
    await userEvent.selectOptions(screen.getByLabelText('Content'), 'song')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByRole('link', { name: 'River story' })
    expect(requests.at(-1)?.path).toBe(
      `/catalogue?q=${encodeURIComponent('नदी')}&content_type=song`,
    )
  })

  it('loads the next page on request', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: RESEARCHER }),
      'GET /catalogue\\?cursor=c1': () => ({
        body: { items: [{ ...ITEM, id: 'sub2', title: 'Song' }], next_cursor: null },
      }),
      'GET /catalogue': () => ({ body: { items: [ITEM], next_cursor: 'c1' } }),
    })
    renderApp('/catalogue')
    await userEvent.click(await screen.findByRole('button', { name: 'Show more' }))
    expect(await screen.findByRole('link', { name: 'Song' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'River story' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument()
  })

  it('is not for contributors', async () => {
    fakeServer({ 'GET /auth/me': () => ({ body: SESSION }) })
    renderApp('/catalogue')
    expect(
      await screen.findByText('Only researchers and admins can see the catalogue.'),
    ).toBeInTheDocument()
  })
})
