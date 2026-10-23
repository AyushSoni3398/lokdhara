import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import { fakeServer, problem, SESSION, SPEAKER } from '../test/fakeServer'
import { renderApp } from '../test/render'

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

async function fillAccount(password = 'a long passphrase', repeat = password) {
  await userEvent.type(screen.getByLabelText(/Your name as others see it/), 'Asha')
  await userEvent.type(screen.getByLabelText(/^Username/), 'asha')
  await userEvent.type(screen.getByLabelText(/^Password/), password)
  await userEvent.type(screen.getByLabelText('Type the password again'), repeat)
}

describe('sign-up', () => {
  it('is linked from the sign-in page', async () => {
    fakeServer({ 'GET /auth/me': () => problem(401, 'not_authenticated') })
    const { router } = renderApp('/login')
    await userEvent.click(await screen.findByRole('link', { name: 'Create an account' }))
    expect(router.state.location.pathname).toBe('/signup')
  })

  it('makes an account, signs in and asks for the profile next', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => problem(401, 'not_authenticated'),
      'POST /auth/signup': () => ({ status: 201, body: SESSION }),
      'GET /speakers\\?mine=true': () => ({ body: { items: [] } }),
      'POST /speakers': () => ({ status: 201, body: { ...SPEAKER, has_active_consent: false } }),
      'GET /speakers/s1': () => ({ body: { ...SPEAKER, has_active_consent: false } }),
      'GET /consent-forms/current.*': () => problem(404, 'consent_form_not_found'),
    })
    const { router } = renderApp('/signup')
    await screen.findByRole('heading', { name: 'Create an account' })
    await fillAccount()
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/speakers/s1/consent'))
    expect(router.state.location.search).toContain(encodeURIComponent('/account/profile?setup=1'))
    expect(requests.find((r) => r.path === '/auth/signup')?.body).toEqual({
      username: 'asha',
      display_name: 'Asha',
      password: 'a long passphrase',
      locale: 'en',
    })
  })

  it('checks that both passwords match before sending', async () => {
    const { requests } = fakeServer({ 'GET /auth/me': () => problem(401, 'not_authenticated') })
    renderApp('/signup')
    await screen.findByRole('heading', { name: 'Create an account' })
    await fillAccount('a long passphrase', 'a different one')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByRole('alert')).toHaveTextContent('The two passwords are not the same.')
    expect(requests.some((r) => r.method === 'POST')).toBe(false)
  })
})

describe('profile', () => {
  it('saves private details and demographics once consent allows them', async () => {
    const consented = { ...SPEAKER, demographics_consented: true, region_coarse: null }
    const identity = { full_name: null, contact: null, village: null, notes: 'team note' }
    const { requests } = fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /speakers\\?mine=true': () => ({ body: { items: [consented] } }),
      'GET /speakers/s1/identity': () => ({ body: { ...identity, updated_at: null } }),
      'PUT /speakers/s1/identity': (r) => ({ body: r.body }),
      'PATCH /speakers/s1': (r) => ({ body: { ...consented, ...(r.body as object) } }),
    })
    renderApp('/account/profile')

    await userEvent.type(await screen.findByLabelText(/^Phone number/), '9000000000')
    await userEvent.type(screen.getByLabelText(/Dialect/), 'Hasada')
    await userEvent.selectOptions(screen.getByLabelText('Age group'), '18-29')
    await userEvent.selectOptions(screen.getByLabelText('First language'), 'unr')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(requests.find((r) => r.method === 'PUT')?.body).toEqual({
      full_name: null,
      contact: '9000000000',
      village: null,
      notes: 'team note',
    })
    expect(requests.find((r) => r.method === 'PATCH')?.body).toEqual({
      dialect_label: 'Hasada',
      age_band: '18-29',
      gender_self_described: null,
      first_language: 'unr',
      region_coarse: null,
    })
  })

  it('does not ask for demographics the person chose not to share', async () => {
    fakeServer({
      'GET /auth/me': () => ({ body: SESSION }),
      'GET /speakers\\?mine=true': () => ({
        body: { items: [{ ...SPEAKER, demographics_consented: false }] },
      }),
      'GET /speakers/s1/identity': () => ({
        body: { full_name: null, contact: null, village: null, notes: null, updated_at: null },
      }),
    })
    renderApp('/account/profile')
    expect(await screen.findByText(/You chose not to share/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Age group')).not.toBeInTheDocument()
  })
})

describe('links from the team', () => {
  it('accepts an invitation with the token from the link and signs in', async () => {
    let signedIn = false
    const { requests } = fakeServer({
      'GET /auth/me': () => (signedIn ? { body: SESSION } : problem(401, 'not_authenticated')),
      'POST /auth/invitations/accept': () => ({ status: 201, body: {} }),
      'POST /auth/login': () => {
        signedIn = true
        return { body: SESSION }
      },
      'GET /submissions.*': () => ({ body: { items: [] } }),
    })
    const { router } = renderApp('/invite#tok123')
    await screen.findByRole('heading', { name: 'Accept your invitation' })
    await fillAccount()
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
    expect(requests.find((r) => r.path === '/auth/invitations/accept')?.body).toMatchObject({
      token: 'tok123',
      username: 'asha',
    })
  })

  it('sets a new password from a reset link', async () => {
    const { requests } = fakeServer({
      'GET /auth/me': () => problem(401, 'not_authenticated'),
      'POST /auth/password-reset': () => ({ status: 204 }),
    })
    renderApp('/reset-password#tok456')
    await userEvent.type(await screen.findByLabelText(/^New password/), 'a long passphrase')
    await userEvent.type(screen.getByLabelText('Type the password again'), 'a long passphrase')
    await userEvent.click(screen.getByRole('button', { name: 'Save new password' }))
    expect(await screen.findByText(/Your password is changed/)).toBeInTheDocument()
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({
      token: 'tok456',
      password: 'a long passphrase',
    })
  })

  it('explains that a link without a token does not work', async () => {
    fakeServer({ 'GET /auth/me': () => problem(401, 'not_authenticated') })
    renderApp('/reset-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('This link does not work')
  })
})
