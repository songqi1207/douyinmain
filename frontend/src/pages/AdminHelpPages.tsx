import { BookOpen, FileText, LoaderCircle, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  approveRegistration,
  fetchRegistrationApplications,
  rejectRegistration,
} from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import type { RegistrationApplication } from "../types";

export function RegistrationAdminPage() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [applications, setApplications] = useState<RegistrationApplication[]>([]);
  const [status, setStatus] = useState("pending");
  const [emailService, setEmailService] = useState({ configured: false, sender: null as string | null, message: "正在检查邮件服务" });
  const [busyId, setBusyId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load(selectedStatus = status) {
    setLoading(true);
    try {
      const result = await fetchRegistrationApplications(selectedStatus);
      setApplications(result.items);
      setEmailService({
        configured: result.email_service.configured,
        sender: result.email_service.sender || null,
        message: result.email_service.message,
      });
      setError("");
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/admin/registrations")}`);
      return;
    }
    if (user.role !== "admin") {
      setError("当前账号不是管理员，不能查看注册申请");
      setLoading(false);
      return;
    }
    void load(status);
  }, [authLoading, user?.id, status]);

  async function review(applicationId: string, action: "approve" | "reject") {
    setBusyId(applicationId);
    setError("");
    setMessage("");
    try {
      const result = action === "approve"
        ? await approveRegistration(applicationId)
        : await rejectRegistration(applicationId);
      setMessage(result.message);
      await load(status);
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setBusyId("");
    }
  }

  return (
    <Layout>
      <main className="content-page page-width admin-registration-page">
        <div className="page-heading"><span className="page-icon"><FileText /></span><div><h1>注册申请审核</h1><p>通过后系统生成临时密码，并发送到申请邮箱。</p></div></div>
        <div className={`service-status ${emailService.configured ? "ready" : "unavailable"}`}><strong>{emailService.configured ? "审批邮件可发送" : "审批邮件未配置"}</strong><span>{emailService.message}{emailService.sender ? ` · ${emailService.sender}` : ""}</span></div>
        <div className="admin-filter-row">{[["pending", "待审核"], ["approved", "已通过"], ["rejected", "已拒绝"], ["all", "全部"]].map(([value, label]) => <button type="button" className={status === value ? "active" : ""} key={value} onClick={() => setStatus(value)}>{label}</button>)}</div>
        {error && <div className="notice error">{error}</div>}
        {message && <div className="notice success">{message}</div>}
        {loading ? <div className="loading-state"><LoaderCircle className="spin" />正在加载申请</div> : applications.length ? (
          <div className="application-list">
            {applications.map((application) => (
              <article className="application-card" key={application.id}>
                <div><strong>{application.email}</strong><p>申请时间：{new Date(application.created_at * 1000).toLocaleString("zh-CN")}</p>{application.delivery_error && <small>上次发信失败：{application.delivery_error}</small>}</div>
                <span className={`application-status ${application.status}`}>{({ pending: "待审核", delivering: "发信中", approved: "已通过", rejected: "已拒绝" } as const)[application.status]}</span>
                {application.status === "pending" && <div className="application-actions"><button type="button" disabled={!emailService.configured || busyId === application.id} onClick={() => void review(application.id, "approve")}>通过并发密码</button><button className="danger" type="button" disabled={busyId === application.id} onClick={() => void review(application.id, "reject")}>拒绝</button></div>}
              </article>
            ))}
          </div>
        ) : <div className="empty-state">当前没有该状态的注册申请</div>}
      </main>
    </Layout>
  );
}

export function HelpPage() {
  return (
    <Layout>
      <main className="content-page page-width help-page">
        <div className="page-heading"><span className="page-icon"><BookOpen /></span><div><h1>使用帮助</h1><p>从一个主题到可下载视频，只需要完成一次设备准备。</p></div></div>
        <section className="help-steps">
          <article><em>01</em><h3>登录并修改临时密码</h3><p>注册申请通过后，用邮件中的密码登录，并按提示换成自己的安全密码。</p></article>
          <article><em>02</em><h3>连接剪映助手</h3><p>在设备中心下载并配对一次，之后网页会在创作时自动唤醒助手。</p></article>
          <article><em>03</em><h3>输入一个主题</h3><p>选择书单、香烟或神话，只填写主题，后台自动完成内容、配音和画面。</p></article>
          <article><em>04</em><h3>下载最终视频</h3><p>等待任务完成后直接播放或下载 MP4，也可以随时从创作记录恢复。</p></article>
        </section>
        <section className="faq-panel">
          <h2>常见问题</h2>
          <details open><summary>为什么一键生成按钮还不能点击？</summary><p>请依次检查账号是否已登录、临时密码是否已修改、对应工作流是否发布，以及剪映设备是否在线。</p></details>
          <details><summary>刷新页面会丢失任务吗？</summary><p>不会。任务在服务器持续执行，首页会恢复最近一次任务，全部历史都保存在创作记录。</p></details>
          <details><summary>为什么需要 Windows 助手？</summary><p>助手负责在你的电脑上创建剪映草稿并原生导出 MP4。首次配对后，网页可以自动唤醒。</p></details>
          <details><summary>能看到 Coze 或米核密钥吗？</summary><p>不能。所有第三方 Token、工作流 ID 和渲染参数只在服务器读取。</p></details>
          <details><summary>还可以手工上传 draft_key 吗？</summary><p>可以，在<Link to="/jianying-export">手工剪映导出</Link>页面粘贴或上传 JSON。</p></details>
        </section>
      </main>
    </Layout>
  );
}

export function NotFoundPage() {
  return (
    <Layout>
      <main className="page-width not-found-page">
        <span><Sparkles /></span><h1>页面走丢了</h1><p>这里没有可用内容，回到工作台继续创作吧。</p><Link className="primary-button" to="/">返回创作工作台</Link>
      </main>
    </Layout>
  );
}
