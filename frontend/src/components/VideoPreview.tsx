import { LoaderCircle, LockKeyhole, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { unlockJobPreview } from "../api";
import type { JobResult } from "../types";

export type VideoOrientation = "unknown" | "portrait" | "landscape";

const PORTRAIT_WORKFLOW_CODES = new Set(["OWN01", "OWN02", "OWN03"]);

export function videoOrientationHint(workflowCode: string): VideoOrientation {
  return PORTRAIT_WORKFLOW_CODES.has(String(workflowCode || "").toUpperCase()) ? "portrait" : "unknown";
}

export function VideoPreview({
  jobId,
  result,
  orientationHint = "unknown",
}: {
  jobId: string;
  result: JobResult;
  orientationHint?: VideoOrientation;
}) {
  const [quality, setQuality] = useState<"720" | "1080">("720");
  const [orientation, setOrientation] = useState<VideoOrientation>(orientationHint);
  const [ready, setReady] = useState(false);
  const [highUrl, setHighUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The default source is a small local fast-preview with Range support.
  // R2 remains the high-quality download and unlocked 1080p source.
  const source = quality === "1080" ? highUrl : `/api/v1/jobs/${encodeURIComponent(jobId)}/preview-stream`;

  useEffect(() => {
    setOrientation(orientationHint);
    setReady(false);
  }, [orientationHint, source]);

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
      <div className={`video-preview-stage ${ready ? "ready" : "loading"}`}>
        <video
          key={source}
          src={source}
          poster={result.poster_url || undefined}
          controls
          playsInline
          preload="auto"
          onLoadedMetadata={(event) => {
            const video = event.currentTarget;
            setOrientation(video.videoHeight > video.videoWidth ? "portrait" : "landscape");
          }}
          onLoadedData={() => setReady(true)}
          onCanPlay={() => setReady(true)}
        />
        {!ready && (
          <div className="video-preview-loading" role="status">
            <LoaderCircle className="spin" size={24} />
            <span>正在加载视频预览</span>
          </div>
        )}
      </div>
      <div className="video-quality-bar" role="group" aria-label="视频清晰度">
        <button type="button" className={quality === "720" ? "active" : ""} onClick={() => setQuality("720")}>
          极速 <small>流畅预览</small>
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
