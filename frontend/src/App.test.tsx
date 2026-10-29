import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from './i18n'
import { fakeServer, problem, SESSION } from './test/fakeServer'
import { renderApp } from './test/render'

describe('app shell and sign-in', () => {
  beforeEach(async () => {
    window.localStorage.clear()
    await i18n.changeLanguage('hi')
  })
  afterEach(() => vi.unstubAllGlobals())

  it('asks to sign in, in Hindi by default', async () => {
    fakeServer({ 'GET /auth/me': () => problem(401, 'not_authenticated') })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'साइन इन' })).toBeInTheDocument()
  })

  it('switches to English and remembers the choice', async () => {
    fakeServer({ 'GET /auth/me': () => problem(401, 'not_authenticated') })
    renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: 'English' }))
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(window.localStorage.getItem('lkd.language')).toBe('en')
    expect(document.documentElement.lang).toBe('en')
  })

  it('explains a failed sign-in, then opens the home page', async () => {
    let attempts = 0
    const { requests } = fakeServer({
      'GET /auth/me': () => problem(401, 'not_authenticated'),
      'POST /auth/login': () =>
        ++attempts === 1 ? problem(401, 'invalid_credentials') : { body: SESSION },
      'GET /submissions.*': () => ({ body: { items: [] } }),
    })
    renderApp('/submissions')
    await userEvent.type(await screen.findByLabelText('यूज़रनेम'), 'asha')
    await userEvent.type(screen.getByLabelText('पासवर्ड'), 'wrong password')
    await userEvent.click(screen.getByRole('button', { name: 'साइन इन करें' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('यूज़रनेम या पासवर्ड सही नहीं है।')

    await userEvent.click(screen.getByRole('button', { name: 'साइन इन करें' }))
    // Back to the page that asked for sign-in.
    expect(await screen.findByRole('heading', { name: 'मेरी प्रविष्टियाँ' })).toBeInTheDocument()
    const listCall = requests.find((r) => r.path.startsWith('/submissions'))
    expect(listCall?.method).toBe('GET')
  })

  it('sends the CSRF token with changes and signs out', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'POST /auth/logout': () => ({ status: 204 }),
    })
    renderApp('/')
    expect(await screen.findByText('स्वागत है, Asha')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'साइन आउट' }))
    expect(await screen.findByRole('heading', { name: 'साइन इन' })).toBeInTheDocument()
    const logout = requests.find((r) => r.path === '/auth/logout')
    expect(logout?.headers.get('X-CSRF-Token')).toBe('csrf-1')
  })

  it('starts the next person at home after a sign-out, not on the last page', async () => {
    let signedIn = true
    fakeServer({
      'GET /auth/me': () => (signedIn ? { body: SESSION } : problem(401, 'not_authenticated')),
      'POST /auth/logout': () => {
        signedIn = false
        return { status: 204 }
      },
      'POST /auth/login': () => {
        signedIn = true
        return { body: SESSION }
      },
      'GET /submissions.*': () => ({ body: { items: [] } }),
    })
    renderApp('/submissions')
    expect(await screen.findByRole('heading', { name: 'मेरी प्रविष्टियाँ' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'साइन आउट' }))
    await userEvent.type(await screen.findByLabelText('यूज़रनेम'), 'ravi')
    await userEvent.type(screen.getByLabelText('पासवर्ड'), 'a long password')
    await userEvent.click(screen.getByRole('button', { name: 'साइन इन करें' }))
    expect(await screen.findByText('स्वागत है, Asha')).toBeInTheDocument()
  })

  it('shows a not-found page for unknown routes', async () => {
    fakeServer({ 'GET /auth/me': () => problem(401, 'not_authenticated') })
    renderApp('/does-not-exist')
    expect(await screen.findByRole('heading', { name: 'पेज नहीं मिला' })).toBeInTheDocument()
  })
})
