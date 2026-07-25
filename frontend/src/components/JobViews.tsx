import { Check, Circle, Download, LoaderCircle, RotateCcw, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import type { Job } from "../types";

const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "等待执行",
  running: "正在生成内容",
  rendering: "正在通过剪映渲染",
  succeeded: "生成完成",
  failed: "生成失败",
};

const PHASES = [
  { label: "排队", threshold: 0 },
  { label: "内容生成", threshold: 15 },
  { label: "草稿生成", threshold: 45 },
  { label: "剪映渲染", threshold: 70 },
  { label: "完成", threshold: 100 },
];

export function JobProgress({
  job,
  onRetry,
  retrying = false,
}: {
  job: Job;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  let progressPhase = 0;
  PHASES.forEach((phase, index) => {
    if (job.progress >= phase.threshold) progressPhase = index;
  });
  const activePhase = job.status === "succeeded" ? PHASES.length - 1 : progressPhase;
  return (
    <section className="job-panel" aria-live="polite" aria-label="任务执行进度">
      <div className="job-heading">
        <div><span className={`status-dot ${job.status}`} />{STATUS_TEXT[job.status]}</div>
        <strong>{job.progress}%</strong>
      </div>
      <div className="progress-track" aria-hidden="true"><i style={{ width: `${job.progress}%` }} /></div>
      <ol className="job-phases">
        {PHASES.map((phase, index) => {
          const done = job.status === "succeeded" || index < activePhase;
          const active = index === activePhase && job.status !== "failed";
          return (
            <li className={done ? "done" : active ? "active" : ""} key={phase.label}>
              <span>{done ? <Check /> : active ? <LoaderCircle className="spin" /> : <Circle />}</span>
              {phase.label}
            </li>
          );
        })}
      </ol>
      <p>{job.stage}</p>
      {job.error && <div className="notice error">{job.error.message}</div>}
      {job.status === "failed" && onRetry && (
        <button className="secondary-button" disabled={retrying} type="button" onClick={onRetry}>
          <RotateCcw size={15} />{retrying ? "正在重试" : "安全重试"}
        </button>
      )}
    </section>
  );
}

export function Results({ job, compact = false }: { job: Job; compact?: boolean }) {
  if (job.status !== "succeeded") return null;
  return (
    <section className={`result-panel ${compact ? "compact" : ""}`}>
      <div className="section-title">
        <span>生成结果</span>
        <small>任务已安全保存到创作记录</small>
      </div>
      <div className={`result-grid ${job.results.length === 1 ? "single" : ""}`}>
        {job.results.map((result, index) => (
          <article className="result-item" key={`${result.url}-${index}`}>
            {result.type === "image" ? (
              <img src={result.url} alt={`${job.display_title} 生成结果 ${index + 1}`} />
            ) : result.type === "video" ? (
              <video src={result.url} poster={result.poster_url || undefined} controls playsInline />
            ) : (
              <div className="draft-result">
                <Sparkles />
                <strong>{result.format === "draft_key" ? "剪映草稿已生成" : "工作流文件已生成"}</strong>
              </div>
            )}
            <div className="result-actions">
              <span>结果 {index + 1}</span>
              <a href={result.url} target="_blank" rel="noreferrer" download={result.downloadable || undefined}>
                <Download size={14} />{result.type === "video" ? "下载视频" : "打开 / 下载"}
              </a>
            </div>
          </article>
        ))}
      </div>
      <div className="result-footer">
        <Link to="/records">查看全部创作记录</Link>
      </div>
    </section>
  );
}
