import type { ReactNode } from 'react'
import type { RouteObject } from 'react-router'

import { RequireAuth } from './auth/session'
import { Layout } from './components/Layout'
import { ChooseSpeakerPage } from './pages/ChooseSpeakerPage'
import { ConsentPage } from './pages/ConsentPage'
import { FailedJobsPage } from './pages/FailedJobsPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { MySubmissionsPage } from './pages/MySubmissionsPage'
import { SubmissionPage } from './pages/SubmissionPage'
import { NewSubmissionPage } from './pages/NewSubmissionPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ReportsPage } from './pages/ReportsPage'

const signedIn = (page: ReactNode) => <RequireAuth>{page}</RequireAuth>

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: signedIn(<HomePage />) },
      { path: 'login', element: <LoginPage /> },
      { path: 'contribute', element: signedIn(<ChooseSpeakerPage />) },
      { path: 'contribute/:speakerId/new', element: signedIn(<NewSubmissionPage />) },
      { path: 'drafts/:draftId', element: signedIn(<NewSubmissionPage />) },
      { path: 'speakers/:speakerId/consent', element: signedIn(<ConsentPage />) },
      { path: 'submissions', element: signedIn(<MySubmissionsPage />) },
      { path: 'submissions/:submissionId', element: signedIn(<SubmissionPage />) },
      { path: 'admin/jobs', element: signedIn(<FailedJobsPage />) },
      { path: 'admin/reports', element: signedIn(<ReportsPage />) },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
