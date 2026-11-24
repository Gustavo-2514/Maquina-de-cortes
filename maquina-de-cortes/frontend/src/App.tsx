import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import HomePage from '@/pages/Home'
import DownloadsPage from '@/pages/Downloads'
import ProjectPage from '@/pages/Project'
import ProjectsPage from '@/pages/Projects'
import QueuePage from '@/pages/Queue'
import SettingsPage from '@/pages/Settings'

// o editor é a maior tela: carrega sob demanda
const EditorPage = lazy(() => import('@/pages/Editor'))

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/inicio" replace />} />
        <Route path="inicio" element={<HomePage />} />
        <Route path="downloads" element={<DownloadsPage />} />
        <Route path="projetos" element={<ProjectsPage />} />
        <Route path="projetos/:id" element={<ProjectPage />} />
        <Route
          path="cortes/:clipId"
          element={
            <Suspense fallback={<p className="p-8 text-sm text-muted-foreground">Abrindo o editor…</p>}>
              <EditorPage />
            </Suspense>
          }
        />
        <Route path="fila" element={<QueuePage />} />
        <Route path="configuracoes" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/inicio" replace />} />
      </Route>
    </Routes>
  )
}
