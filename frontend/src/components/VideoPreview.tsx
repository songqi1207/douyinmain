import { LoaderCircle, LockKeyhole, Sparkles } from "lucide-react";
import { useState } from "react";

import { unlockJobPreview } from "../api";
import type { JobResult } from "../types";

export function VideoPreview({ jobId, result }: { jobId: string; result: JobResult }) {
  const [quality, setQuality] = useState<"720" | "1080">("720");
  const [orientation, setOrientation] = useState<"unknown" | "portrait" | "landscape">("unknown");
  const [highUrl, setHighUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Preview is cached on the application server once, then FileResponse
  // serves fast local Range responses. R2 remains the high-quality download.
  const source = quality === "1080" ? highUrl : `/api/v1/jobs/${encodeURIComponent(jobId)}/preview-stream`;

  async function choose1080() {
    if (highUrl) {
      setQuality("1080");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const unlocked = await unlockJobPreview(jobId);
      setHighUrl(unlocked.url);
      setQuality("1080");
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`video-preview-shell ${orientation}`} data-orientation={orientation}>
      <video
        key={source}
        src={source}
        poster={result.poster_url || undefined}
        controls
        playsInline
        preload="metadata"
        onLoadedMetadata={(event) => {
          const video = event.currentTarget;
          setOrientation(video.videoHeight > video.videoWidth ? "portrait" : "landscape");
        }}
      />
      <div className="video-quality-bar" role="group" aria-label="视频清晰度">
        <button type="button" className={quality === "720" ? "active" : ""} onClick={() => setQuality("720")}>
          720P <small>流畅预览</small>
        </button>
        <button type="button" className={quality === "1080" ? "active premium" : "premium"} disabled={busy} onClick={() => void choose1080()}>
          {busy ? <LoaderCircle className="spin" size={14} /> : highUrl ? <Sparkles size={14} /> : <LockKeyhole size={14} />}
          1080P <small>{highUrl ? "已解锁" : "10 积分"}</small>
        </button>
      </div>
      {error && <p className="video-quality-error">{error}</p>}
    </div>
  );
}
