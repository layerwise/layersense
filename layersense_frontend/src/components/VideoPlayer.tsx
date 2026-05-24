type VideoPlayerStatus =
  | 'idle'
  | 'submitting_to_agent'
  | 'queueing_render'
  | 'waiting_for_preview'
  | 'waiting_for_final'
  | 'complete'
  | 'error'

type VideoPlayerProps = {
  previewUrl: string | null
  finalUrl: string | null
  error: string | null
  status: VideoPlayerStatus
}

const statusLabel: Record<VideoPlayerStatus, string> = {
  idle: 'Ready to generate',
  submitting_to_agent: 'Generating scene from prompt...',
  queueing_render: 'Queueing render...',
  waiting_for_preview: 'Waiting for preview render...',
  waiting_for_final: 'Preview ready. Waiting for final render...',
  complete: 'Final render ready',
  error: 'Error',
}

export const VideoPlayer = ({ previewUrl, finalUrl, error, status }: VideoPlayerProps) => {
  const src = finalUrl ?? previewUrl

  return (
    <section className="flex flex-col flex-1 gap-2 font-sans min-h-0" aria-live="polite">
      <p className="m-0 mb-2 shrink-0 text-[#594e3f]">{statusLabel[status]}</p>

      {error ? <p className="m-0 mb-[0.6rem] shrink-0 font-semibold text-[#b6422e]">{error}</p> : null}

      {src ? (
        <video
          className="w-full flex-1 object-contain rounded-lg bg-black min-h-0"
          data-testid="render-video"
          src={src}
          controls
          autoPlay={false}
          playsInline
          preload="metadata"
        />
      ) : (
        <p>No render yet</p>
      )}
    </section>
  )
}
