import { Check, LoaderCircle, LockKeyhole, Mail, ShieldCheck, Sparkles } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { login, register } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { setAuth } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const isRegister = mode === "register";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      if (isRegister) {
        const result = await register(email);
        setSuccess(result.message);
        setEmail("");
        return;
      }
      const auth = await login(email, password);
      setAuth(auth);
      if (auth.user?.must_change_password) {
        navigate("/account/security");
        return;
      }
      const redirect = searchParams.get("redirect");
      navigate(redirect?.startsWith("/") && !redirect.startsWith("//") ? redirect : "/");
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Layout>
      <main className="auth-page page-width">
        <section className="auth-card upgraded">
          <span className="brand-mark"><Sparkles /></span>
          <span className="eyebrow">{isRegister ? "JOIN THE STUDIO" : "WELCOME BACK"}</span>
          <h1>{isRegister ? "申请创作者账号" : "登录创作工作台"}</h1>
          <p>{isRegister ? "提交邮箱，审核通过后登录密码会发送到你的邮箱。" : "继续你的创作、设备和视频记录。"}</p>
          <form onSubmit={(event) => void submit(event)}>
            <label>
              <span>{isRegister ? "申请邮箱" : "邮箱 / 用户名"}</span>
              <div className="input-with-icon"><Mail /><input autoComplete="username" type={isRegister ? "email" : "text"} value={email} onChange={(event) => setEmail(event.target.value)} placeholder={isRegister ? "name@example.com" : "输入邮箱或用户名"} required /></div>
            </label>
            {!isRegister && (
              <label>
                <span>登录密码</span>
                <div className="input-with-icon"><LockKeyhole /><input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="输入登录密码" required /></div>
              </label>
            )}
            {error && <div className="notice error">{error}</div>}
            {success && <div className="notice success"><Check />{success}</div>}
            <button className="primary-button" disabled={busy || Boolean(success)} type="submit">{busy ? <LoaderCircle className="spin" /> : <ShieldCheck />}{busy ? "正在提交" : isRegister ? "提交注册申请" : "安全登录"}</button>
          </form>
          <div className="auth-switch">{isRegister ? <>已经收到通过邮件？<Link to="/login">立即登录</Link></> : <>还没有账号？<Link to="/register">申请注册</Link></>}</div>
          <small className="auth-trust"><ShieldCheck />密码和第三方密钥都不会发送到前端页面</small>
        </section>
      </main>
    </Layout>
  );
}
