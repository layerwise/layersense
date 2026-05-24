import { useCallback, useRef, useState } from 'react'

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

const panelClass =
  'rounded-xl border border-[#ded9d1] bg-white/[0.87] p-3 shadow-[0_6px_18px_rgba(57,48,34,0.08)]'
const panelHeadingClass = 'm-0 mb-2 font-heading text-[0.92rem] font-semibold text-[var(--text-h)]'

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

const deriveStatusFromJob = (job: RenderJobSnapshot): AppStatus => {
  if (job.status === 'failed') return 'error'
  if (job.final_url) return 'complete'
  if (job.preview_url) return 'waiting_for_final'
  return 'waiting_for_preview'
}

function App() {
  const [prompt, setPrompt] = useState('')
  const [submitStatus, setSubmitStatus] = useState<AppStatus>('idle')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [initialJob, setInitialJob] = useState<RenderJobSnapshot | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const canvasRef = useRef<CanvasHandle>(null)

  const polledJob = useRenderJob({ jobId, initialJob })
  const currentJob = polledJob ?? initialJob

  const previewUrl = currentJob?.preview_url ? normalizeArtifactUrl(currentJob.preview_url) : null
  const finalUrl = currentJob?.final_url ? normalizeArtifactUrl(currentJob.final_url) : null
  const error = currentJob ? currentJob.error : submitError
  const status: AppStatus = currentJob ? deriveStatusFromJob(currentJob) : submitStatus

  const handleGenerate = useCallback(async () => {
    try {
      setSubmitError(null)
      setJobId(null)
      setInitialJob(null)
      setSubmitStatus('submitting_to_agent')

      const snapshot = canvasRef.current?.getSceneSnapshot() ?? {
        elements: [],
        appState: {},
        files: {},
      }

      const animation = await createAnimation({ prompt, scene: snapshot })
      setSubmitStatus('queueing_render')
      const renderResponse = await queueRender({
        source_code: animation.source_code,
        content_hash: animation.content_hash,
        conversation_id: animation.conversation_id,
        cli_flags: {},
      })
      setJobId(renderResponse.job_id)
      setInitialJob(renderResponse.job)
    } catch (requestError) {
      setSubmitError(normalizeError(requestError))
      setSubmitStatus('error')
    }
  }, [prompt])

  return (
    <main className="flex-1 grid min-h-0 w-full grid-rows-[auto_1fr] gap-3 bg-[radial-gradient(circle_at_15%_20%,rgba(255,189,89,0.14),transparent_40%),radial-gradient(circle_at_85%_15%,rgba(85,173,255,0.14),transparent_45%),#f5f4f1] p-3 text-[#2f2b25] text-left lg:h-screen lg:max-h-screen">
      <header className="grid grid-cols-1 items-start gap-3 lg:grid-cols-[1fr_auto]">
        <div className="justify-self-stretch text-center lg:justify-self-center">
          <h1 className="m-0 font-heading text-[clamp(1.15rem,1.45vw,1.45rem)] font-bold leading-[1.05] tracking-[-0.01em] text-[var(--text-h)] [@media(max-height:860px)]:text-[clamp(1.25rem,1.8vw,1.7rem)]">
            LayerSense Studio
          </h1>
          <p className="mt-[0.18rem] mb-0 text-[0.82rem] text-[#5a5147] [@media(max-height:860px)]:text-[0.84rem]">
            Draw in Excalidraw, describe your animation, then generate and render.
          </p>
        </div>
        <button
          type="button"
          className="cursor-pointer self-start justify-self-center rounded-lg border border-[#cbc3b7] bg-white/80 px-[0.62rem] py-[0.38rem] font-sans text-[0.85rem] font-semibold text-[#3f372d] lg:justify-self-auto"
          onClick={() => setIsSidebarCollapsed((value) => !value)}
          aria-label={isSidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
        >
          {isSidebarCollapsed ? 'Show Sidebar' : 'Hide Sidebar'}
        </button>
      </header>

      <section
        className={`grid min-h-0 gap-3 ${isSidebarCollapsed ? 'grid-cols-1' : 'grid-cols-1 lg:grid-cols-[minmax(0,1fr)_clamp(320px,23vw,390px)]'}`}
      >
        <section className={`${panelClass} flex flex-col min-h-[66vh] lg:min-h-0`}>
          <h2 className={panelHeadingClass}>Canvas</h2>
          <div className="relative flex-1 min-h-0 overflow-hidden rounded-[10px] border border-[#d2cbc0] bg-white">
            <Canvas ref={canvasRef} />
          </div>
        </section>

        {!isSidebarCollapsed ? (
          <aside className="grid min-h-0 gap-3 overflow-auto grid-rows-[auto_auto] lg:grid-rows-[auto_1fr]">
            <section className={`${panelClass} flex flex-col`}>
              <h2 className={panelHeadingClass}>Prompt</h2>
              <label className="mb-2 block font-sans text-sm font-semibold" htmlFor="animation-prompt">
                Describe the animation sequence
              </label>
              <textarea
                className="mb-[0.6rem] box-border w-full resize-y rounded-lg border border-[#cfc6b6] p-[0.6rem] font-sans"
                id="animation-prompt"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Create the circle, then move it to the right while changing color."
                rows={5}
              />

              <button
                className="cursor-pointer rounded-lg border-0 bg-[#1f7a63] px-[0.9rem] py-[0.6rem] font-sans text-[0.95rem] font-bold text-white disabled:cursor-not-allowed disabled:opacity-[0.55]"
                type="button"
                onClick={handleGenerate}
                disabled={isGenerateDisabled(status)}
              >
                Generate
              </button>
            </section>

            <section className={`${panelClass} min-h-0 flex flex-col`}>
              <h2 className={panelHeadingClass}>Render Output</h2>
              <div className="flex-1 min-h-0 flex flex-col">
                <VideoPlayer previewUrl={previewUrl} finalUrl={finalUrl} error={error} status={status} />
              </div>
            </section>
          </aside>
        ) : null}
      </section>
    </main>
  )
}

export default App
