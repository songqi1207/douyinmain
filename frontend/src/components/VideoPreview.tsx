import { LoaderCircle, LockKeyhole, Sparkles } from "lucide-react";
import { useState } from "react";

import { unlockJobPreview } from "../api";
import type { JobResult } from "../types";

export function VideoPreview({ jobId, result }: { jobId: string; result: JobResult }) {
  const [quality, setQuality] = useState<"720" | "1080">("720");
  const [highUrl, setHighUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const source = quality === "1080" ? highUrl : result.url;

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
    <div className="video-preview-shell">
      <video key={source} src={source} poster={result.poster_url || undefined} controls playsInline preload="metadata" />
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
