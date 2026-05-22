import { useCallback, useEffect, useRef, useState } from 'react'

import './App.css'
import { CONTROLLER_BASE, createAnimation, queueRender } from './api'
import { Canvas, type CanvasHandle } from './components/Canvas'
import { VideoPlayer } from './components/VideoPlayer'
import { useRenderJob } from './hooks/useRenderJob'
import type { RenderJobSnapshot } from './types'

type AppStatus =
  | 'idle'
  | 'submitting_to_agent'
  | 'queueing_render'
  | 'waiting_for_preview'
  | 'waiting_for_final'
  | 'complete'
  | 'error'

const isGenerateDisabled = (status: AppStatus): boolean =>
  status === 'submitting_to_agent' || status === 'queueing_render'

const normalizeError = (error: unknown): string => {
  if (error instanceof Error) {
    return error.message
  }

  return 'Unexpected error'
}

const normalizeArtifactUrl = (url: string): string => {
  if (url.startsWith('/')) {
    return `${CONTROLLER_BASE}${url}`
  }

  return url
}

function App() {
  const [prompt, setPrompt] = useState('')
  const [status, setStatus] = useState<AppStatus>('idle')
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [finalUrl, setFinalUrl] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [initialJob, setInitialJob] = useState<RenderJobSnapshot | null>(null)
  const canvasRef = useRef<CanvasHandle>(null)

  const polledJob = useRenderJob({ jobId, initialJob })
  const currentJob = polledJob ?? initialJob

  useEffect(() => {
    if (!currentJob) return

    setPreviewUrl(currentJob.preview_url ? normalizeArtifactUrl(currentJob.preview_url) : null)
    setFinalUrl(currentJob.final_url ? normalizeArtifactUrl(currentJob.final_url) : null)
    setError(currentJob.error)

    if (currentJob.status === 'failed') {
      setStatus('error')
    } else if (currentJob.final_url) {
      setStatus('complete')
    } else if (currentJob.preview_url) {
      setStatus('waiting_for_final')
    } else {
      setStatus('waiting_for_preview')
    }
  }, [currentJob])

  const handleGenerate = useCallback(async () => {
    try {
      setError(null)
      setPreviewUrl(null)
      setFinalUrl(null)
      setJobId(null)
      setInitialJob(null)
      setStatus('submitting_to_agent')

      const snapshot = canvasRef.current?.getSceneSnapshot() ?? {
        elements: [],
        appState: {},
        files: {},
      }

      const animation = await createAnimation({ prompt, scene: snapshot })
      setStatus('queueing_render')
      const renderResponse = await queueRender({
        source_code: animation.source_code,
        content_hash: animation.content_hash,
        conversation_id: animation.conversation_id,
        cli_flags: {},
      })
      setJobId(renderResponse.job_id)
      setInitialJob(renderResponse.job)
      setStatus(renderResponse.job.preview_url ? 'waiting_for_final' : 'waiting_for_preview')
    } catch (requestError) {
      setError(normalizeError(requestError))
      setStatus('error')
    }
  }, [prompt])

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="header-copy">
          <h1>LayerSense Studio</h1>
          <p>Draw in Excalidraw, describe your animation, then generate and render.</p>
        </div>
        <button
          type="button"
          className="sidebar-toggle"
          onClick={() => setIsSidebarCollapsed((value) => !value)}
          aria-label={isSidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
        >
          {isSidebarCollapsed ? 'Show Sidebar' : 'Hide Sidebar'}
        </button>
      </header>

      <section className={`workspace-grid${isSidebarCollapsed ? ' workspace-grid--collapsed' : ''}`}>
        <section className="panel panel-canvas">
          <h2>Canvas</h2>
          <div className="canvas-frame">
            <Canvas ref={canvasRef} />
          </div>
        </section>

        {!isSidebarCollapsed ? (
          <aside className="inspector">
            <section className="panel panel-controls">
              <h2>Prompt</h2>
              <label htmlFor="animation-prompt">Describe the animation sequence</label>
              <textarea
                id="animation-prompt"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Create the circle, then move it to the right while changing color."
                rows={5}
              />

              <button type="button" onClick={handleGenerate} disabled={isGenerateDisabled(status)}>
                Generate
              </button>
            </section>

            <section className="panel panel-output">
              <h2>Render Output</h2>
              <VideoPlayer previewUrl={previewUrl} finalUrl={finalUrl} error={error} status={status} />
            </section>
          </aside>
        ) : null}
      </section>
    </main>
  )
}

export default App
