import { useCallback, useRef, useState } from 'react'

import './App.css'
import { createAnimation, queueRender } from './api'
import { Canvas, type CanvasHandle } from './components/Canvas'
import { VideoPlayer } from './components/VideoPlayer'
import { useRenderEvents } from './hooks/useRenderEvents'

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

function App() {
  const [prompt, setPrompt] = useState('')
  const [status, setStatus] = useState<AppStatus>('idle')
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [finalUrl, setFinalUrl] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const canvasRef = useRef<CanvasHandle>(null)

  const handleArtifactReady = useCallback((payload: { previewUrl: string; finalUrl: string }) => {
    setPreviewUrl(payload.previewUrl)
    setFinalUrl(payload.finalUrl)
    setStatus('complete')
    setError(null)
  }, [])

  const handlePreviewReady = useCallback((url: string) => {
    setPreviewUrl(url)
    setStatus('waiting_for_final')
  }, [])

  const handleRenderReady = useCallback((url: string) => {
    setFinalUrl(url)
    setStatus('complete')
    setError(null)
  }, [])

  const handleRenderFailed = useCallback((payload: { error: string; stderr?: string }) => {
    setError(payload.error)
    setStatus('error')
  }, [])

  useRenderEvents({
    conversationId,
    onArtifactReady: handleArtifactReady,
    onPreviewReady: handlePreviewReady,
    onRenderReady: handleRenderReady,
    onRenderFailed: handleRenderFailed,
  })

  const handleGenerate = useCallback(async () => {
    try {
      setError(null)
      setPreviewUrl(null)
      setFinalUrl(null)
      setConversationId(null)
      setStatus('submitting_to_agent')

      const snapshot = canvasRef.current?.getSceneSnapshot() ?? {
        elements: [],
        appState: {},
        files: {},
      }

      const animation = await createAnimation({ prompt, scene: snapshot })
      setConversationId(animation.conversation_id)

      setStatus('queueing_render')
      await queueRender({
        scene_path: animation.scene_path,
        conversation_id: animation.conversation_id,
      })

      setStatus('waiting_for_preview')
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
