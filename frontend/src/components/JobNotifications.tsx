import { Bell, BellOff, Check, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { fetchJobs } from "../api";
import { useAuth } from "../auth";
import { usePreferences } from "../preferences";
import type { Job } from "../types";

export const JOB_NOTIFICATIONS_ENABLED_KEY = "job-notifications-enabled";
export const JOB_NOTIFICATIONS_REQUEST_EVENT = "job-notifications-request";
export const JOB_NOTIFICATIONS_STATE_EVENT = "job-notifications-state";
const TERMINAL = new Set<Job["status"]>(["succeeded", "failed"]);

function notificationText(job: Job, tr: (zh: string, en: string) => string) {
  if (job.status === "succeeded") {
    return { title: tr("视频已生成完成", "Video completed"), body: tr(`${job.display_title || "创作任务"} 已完成，可以查看或下载视频。`, `${job.display_title || "Creation"} is ready to view or download.`) };
  }
  return { title: tr("视频生成失败", "Video generation failed"), body: tr(`${job.display_title || "创作任务"} 处理失败，请打开创作记录查看原因。`, `${job.display_title || "Creation"} failed. Open your creations to review the issue.`) };
}

export function JobNotifications() {
  const { user } = useAuth();
  const { tr, language } = usePreferences();
  const [enabled, setEnabled] = useState(() => localStorage.getItem(JOB_NOTIFICATIONS_ENABLED_KEY) === "true");
  const [toast, setToast] = useState<{ kind: "success" | "error"; title: string; body: string } | null>(null);
  const statuses = useRef(new Map<string, Job["status"]>());
  const initialized = useRef(false);
  const watcherStartedAt = useRef(Date.now() / 1000);
  const toastTimer = useRef<number | undefined>(undefined);

  function showToast(job: Job) {
    const message = notificationText(job, tr);
    setToast({ kind: job.status === "succeeded" ? "success" : "error", ...message });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 8000);

    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    try {
      const notification = new Notification(message.title, {
        body: message.body,
        tag: `workflow-job-${job.id}`,
      });
      notification.onclick = () => {
        window.focus();
        window.location.assign("/business/records");
        notification.close();
      };
    } catch {
      // The in-page toast remains available when the OS notification fails.
    }
  }

  useEffect(() => {
    statuses.current.clear();
    initialized.current = false;
    watcherStartedAt.current = Date.now() / 1000;
  }, [user?.id]);

  useEffect(() => {
    // Browser permissions can be revoked after this preference was saved.
    if (enabled && typeof Notification !== "undefined" && Notification.permission === "denied") {
      localStorage.setItem(JOB_NOTIFICATIONS_ENABLED_KEY, "false");
      setEnabled(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!user || !enabled) return;
    let active = true;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const { items } = await fetchJobs({ page: 1, pageSize: 50 });
        if (!active) return;
        for (const job of items) {
          const previous = statuses.current.get(job.id);
          const becameTerminal = previous && !TERMINAL.has(previous) && TERMINAL.has(job.status);
          const completedBetweenPolls = !previous
            && TERMINAL.has(job.status)
            && job.created_at >= watcherStartedAt.current;
          if (initialized.current && (becameTerminal || completedBetweenPolls)) {
            showToast(job);
          }
          statuses.current.set(job.id, job.status);
        }
        initialized.current = true;
      } catch {
        // A temporary polling failure must not disable notifications.
      } finally {
        if (active) timer = window.setTimeout(poll, 5000);
      }
    };

    void poll();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [user?.id, enabled, language]);

  useEffect(() => () => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
  }, []);

  useEffect(() => {
    const requestNotifications = () => {
      if (!enabled) void toggle();
    };
    window.addEventListener(JOB_NOTIFICATIONS_REQUEST_EVENT, requestNotifications);
    return () => window.removeEventListener(JOB_NOTIFICATIONS_REQUEST_EVENT, requestNotifications);
  }, [enabled]);

  async function toggle() {
    if (enabled) {
      localStorage.setItem(JOB_NOTIFICATIONS_ENABLED_KEY, "false");
      setEnabled(false);
      window.dispatchEvent(new Event(JOB_NOTIFICATIONS_STATE_EVENT));
      return;
    }
    if (typeof Notification === "undefined") {
      setToast({ kind: "error", title: tr("无法开启通知", "Notifications unavailable"), body: tr("当前浏览器不支持系统通知。", "This browser does not support system notifications.") });
      return;
    }
    // Chrome and Edge require HTTPS for system notifications (localhost is exempt).
    const localHost = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
    if (window.isSecureContext === false && !localHost) {
      setToast({
        kind: "error",
        title: tr("请使用安全连接", "Use a secure connection"),
        body: tr("系统通知需要 HTTPS，请打开 https://api.songqi.online/business/ 后再开启。", "System notifications require HTTPS. Open https://api.songqi.online/business/ and try again."),
      });
      return;
    }
    let permission: NotificationPermission;
    try {
      permission = Notification.permission === "default"
        ? await Notification.requestPermission()
        : Notification.permission;
    } catch {
      setToast({ kind: "error", title: tr("通知未开启", "Notifications blocked"), body: tr("浏览器没有返回通知权限，请检查网站权限设置。", "The browser did not grant permission. Check this site's notification settings.") });
      return;
    }
    if (permission !== "granted") {
      setToast({ kind: "error", title: tr("通知未开启", "Notifications blocked"), body: tr("浏览器已阻止通知，请在网站权限中允许通知。", "Allow notifications in your browser's site permissions.") });
      return;
    }
    localStorage.setItem(JOB_NOTIFICATIONS_ENABLED_KEY, "true");
    setEnabled(true);
    window.dispatchEvent(new Event(JOB_NOTIFICATIONS_STATE_EVENT));
    setToast({ kind: "success", title: tr("任务通知已开启", "Task notifications enabled"), body: tr("视频完成或失败时会立即提醒你。", "You will be notified when a video completes or fails.") });
    try {
      const confirmation = new Notification(tr("任务通知已连接", "Task notifications connected"), {
        body: tr("视频完成或失败时会提醒你。", "You will be alerted when a video completes or fails."),
        tag: "workflow-notifications-connected",
      });
      window.setTimeout(() => confirmation?.close?.(), 5000);
    } catch {
      // The in-page confirmation remains available when the OS notification fails.
    }
  }

  if (!user) return null;

  return (
    <>
      <button
        className={`job-notification-toggle ${enabled ? "active" : ""}`}
        type="button"
        onClick={() => void toggle()}
        aria-label={enabled ? tr("关闭任务通知", "Disable task notifications") : tr("开启任务通知", "Enable task notifications")}
        title={enabled ? tr("任务通知已开启", "Task notifications enabled") : tr("开启任务完成通知", "Enable completion notifications")}
      >
        {enabled ? <Bell size={15} /> : <BellOff size={15} />}
        <span>{enabled ? tr("通知已开", "Notifications on") : tr("开启通知", "Enable alerts")}</span>
      </button>
      {toast && (
        <aside className={`job-notification-toast ${toast.kind}`} role="status" aria-live="polite">
          <span>{toast.kind === "success" ? <Check /> : <Bell />}</span>
          <div><strong>{toast.title}</strong><p>{toast.body}</p></div>
          <button type="button" onClick={() => setToast(null)} aria-label={tr("关闭通知", "Dismiss notification")}><X /></button>
        </aside>
      )}
    </>
  );
}
