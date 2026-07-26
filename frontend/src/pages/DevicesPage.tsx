import { Check, Clipboard, Download, Laptop, Link2, LoaderCircle, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  ApiError,
  createRenderDevicePairingCode,
  fetchDraftKeyRenderStatus,
  revokeRenderDevice,
} from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import type { RenderStatus } from "../types";

const EMPTY_STATUS: RenderStatus = {
  configured: false,
  device_online: false,
  central_configured: false,
  devices: [],
  message: "正在检查设备",
};

export function DevicesPage() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<RenderStatus>(EMPTY_STATUS);
  const [pairing, setPairing] = useState<{ code: string; expires_at: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function refresh() {
    try {
      setStatus(await fetchDraftKeyRenderStatus());
    } catch (nextError) {
      setError((nextError as Error).message);
    }
  }

  useEffect(() => {
    if (loading) return;
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/devices")}`);
      return;
    }
    if (user.must_change_password) {
      navigate("/account/security");
      return;
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [loading, user?.id, user?.must_change_password]);

  async function createPairing() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const next = await createRenderDevicePairingCode();
      setPairing(next);
      setMessage("配对码已生成，请在 Windows 助手中输入");
    } catch (nextError) {
      const apiError = nextError as ApiError;
      if (apiError.code === "password_change_required") navigate("/account/security");
      else setError(apiError.message);
    } finally {
      setBusy(false);
    }
  }

  function wakeHelper() {
    const query = new URLSearchParams({ site: window.location.origin });
    if (pairing) query.set("code", pairing.code);
    const launcher = document.createElement("iframe");
    launcher.style.display = "none";
    launcher.src = `douyin-draft://wake?${query.toString()}`;
    document.body.appendChild(launcher);
    window.setTimeout(() => launcher.remove(), 1500);
    setMessage("已尝试唤醒助手，正在等待设备上线");
  }

  async function copyPairing() {
    if (!pairing) return;
    await navigator.clipboard.writeText(pairing.code);
    setMessage("配对码已复制");
  }

  async function removeDevice(deviceId: string) {
    setError("");
    try {
      await revokeRenderDevice(deviceId);
      setMessage("设备已解除");
      await refresh();
    } catch (nextError) {
      setError((nextError as Error).message);
    }
  }

  return (
    <Layout>
      <main className="content-page page-width devices-page">
        <div className="page-heading">
          <span className="page-icon"><Laptop /></span>
          <div><h1>剪映设备中心</h1><p>只需配对一次，之后网页会自动把草稿发送到你的电脑并返回 MP4。</p></div>
        </div>

        <div className={`device-hero-status ${status.configured ? "ready" : ""}`}>
          <span>{status.configured ? <Check /> : <Laptop />}</span>
          <div>
            <strong>{status.message}</strong>
            <p>{status.device_online ? "你的电脑已准备好接收视频任务。" : status.central_configured ? "当前使用服务端视频渲染。" : "完成下方三步，即可从首页一键生成视频。"}</p>
          </div>
          <button type="button" onClick={() => void refresh()}><RefreshCw />刷新状态</button>
        </div>

        <section className="device-onboarding">
          <article>
            <em>01</em>
            <span><Download /></span>
            <h2>下载 AI 视频创作助手</h2>
            <p>下载 Windows 助手并双击运行。当前版本 v1.3.2，会注册为当前用户的后台启动项。</p>
            <a className="secondary-button" href="/api/v1/downloads/draft-bridge?v=1.3.2">下载 v1.3.2</a>
          </article>
          <article>
            <em>02</em>
            <span><Link2 /></span>
            <h2>生成配对码</h2>
            <p>配对码约十分钟有效，只能使用一次，不会暴露你的登录信息。</p>
            <button className="secondary-button" disabled={busy} type="button" onClick={() => void createPairing()}>
              {busy ? <LoaderCircle className="spin" /> : <Link2 />}{busy ? "正在生成" : "生成配对码"}
            </button>
          </article>
          <article>
            <em>03</em>
            <span><Laptop /></span>
            <h2>启动并保持在线</h2>
            <p>网页会在生成时自动唤醒助手；也可以现在手动启动并检查连接。</p>
            <button className="secondary-button" type="button" onClick={wakeHelper}><Laptop />唤醒助手</button>
          </article>
        </section>

        {pairing && (
          <section className="pairing-display" aria-live="polite">
            <div><span>网站地址</span><strong>{window.location.origin}</strong></div>
            <div><span>一次性配对码</span><strong className="pairing-number">{pairing.code}</strong></div>
            <button type="button" onClick={() => void copyPairing()}><Clipboard />复制配对码</button>
          </section>
        )}
        {message && <div className="notice success">{message}</div>}
        {error && <div className="notice error">{error}</div>}

        <section className="connected-devices">
          <div className="section-title"><span>已连接设备</span><small>{status.devices.length} 台</small></div>
          {status.devices.length ? (
            <div className="connected-device-grid">
              {status.devices.map((device) => (
                <article key={device.id}>
                  <span className={`device-computer ${device.online ? "online" : ""}`}><Laptop /></span>
                  <div><strong>{device.name}</strong><small>{device.platform} · {device.online ? "在线" : "离线"}</small></div>
                  <button type="button" aria-label={`解除 ${device.name}`} onClick={() => void removeDevice(device.id)}><Trash2 /></button>
                </article>
              ))}
            </div>
          ) : <div className="small-empty">还没有配对设备，请按上方步骤完成首次连接。</div>}
        </section>
      </main>
    </Layout>
  );
}
