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
    <section className="video-player" aria-live="polite">
      <p className="video-status">{statusLabel[status]}</p>

      {error ? <p className="video-error">{error}</p> : null}

      {src ? (
        <video data-testid="render-video" src={src} controls autoPlay={false} playsInline preload="metadata" />
      ) : (
        <p>No render yet</p>
      )}
    </section>
  )
}
