import { Headphones, Heart, LoaderCircle, Mic2, Pause, Play, Search } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, fetchVoices, generateSpeech, toggleFavorite } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import { usePreferences } from "../preferences";
import type { Voice } from "../types";

export function VoicesPage() {
  const { tr } = usePreferences();
  const { user, voice_favorites } = useAuth();
  const navigate = useNavigate();
  const [voices, setVoices] = useState<Voice[]>([]);
  const [query, setQuery] = useState("");
  const [gender, setGender] = useState("all");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [favorites, setFavorites] = useState(new Set<string>());
  const [selectedId, setSelectedId] = useState("");
  const [playingId, setPlayingId] = useState("");
  const [text, setText] = useState("");
  const [speed, setSpeed] = useState(1);
  const [generating, setGenerating] = useState(false);
  const [audio, setAudio] = useState<{ url: string; duration: number; message: string } | null>(null);
  const [error, setError] = useState("");
  const [service, setService] = useState({ available: false, provider: "", message: "正在读取配音服务" });
  const auditionAudio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => setFavorites(new Set(voice_favorites)), [voice_favorites.join("|")]);
  useEffect(() => {
    fetchVoices().then((catalog) => {
      setVoices(catalog.voices);
      setSelectedId(catalog.voices[0]?.id || "");
      setService({ available: catalog.available, provider: catalog.provider, message: catalog.message });
    }).catch((nextError: Error) => setError(nextError.message));
    return () => auditionAudio.current?.pause();
  }, []);

  const filteredVoices = useMemo(() => voices.filter((voice) => {
    const matchesQuery = !query || `${voice.name} ${voice.description} ${voice.id}`.toLowerCase().includes(query.toLowerCase());
    return matchesQuery && (gender === "all" || voice.gender === gender) && (!favoritesOnly || favorites.has(voice.id));
  }), [voices, query, gender, favoritesOnly, favorites]);
  const selectedVoice = voices.find((voice) => voice.id === selectedId);

  function requireCreator() {
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/voices")}`);
      return false;
    }
    if (user.must_change_password) {
      navigate("/account/security");
      return false;
    }
    return true;
  }

  async function audition(voice: Voice) {
    if (!requireCreator()) return;
    if (playingId === voice.id) {
      auditionAudio.current?.pause();
      setPlayingId("");
      return;
    }
    auditionAudio.current?.pause();
    setPlayingId(voice.id);
    setError("");
    try {
      const result = await generateSpeech(`你好，我是${voice.name}。这是一段真实音色试听。`, voice.id, speed);
      const player = new Audio(result.audio.url);
      auditionAudio.current = player;
      player.onended = () => setPlayingId("");
      player.onerror = () => setPlayingId("");
      await player.play();
    } catch (nextError) {
      setPlayingId("");
      const apiError = nextError as ApiError;
      if (apiError.code === "password_change_required") navigate("/account/security");
      else setError(apiError.message);
    }
  }

  async function save(voiceId: string) {
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/voices")}`);
      return;
    }
    try {
      const result = await toggleFavorite("voice", voiceId);
      setFavorites((current) => {
        const next = new Set(current);
        if (result.selected) next.add(voiceId); else next.delete(voiceId);
        return next;
      });
    } catch (nextError) {
      setError((nextError as Error).message);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!requireCreator()) return;
    if (!selectedVoice || !text.trim()) {
      setError(tr("请选择音色并输入配音文案", "Choose a voice and enter your script"));
      return;
    }
    setGenerating(true);
    setError("");
    try {
      const result = await generateSpeech(text.trim(), selectedVoice.id, speed);
      setAudio(result.audio);
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <Layout>
      <main className="voices-page page-width">
        <section className="page-heading voice-heading"><span className="page-icon"><Headphones /></span><div><h1>{tr("声音工作室", "Voice Studio")}</h1><p>{tr("搜索真实音色、在线试听，并生成可下载配音。", "Explore voices, preview them and create downloadable narration.")}</p></div></section>
        <div className={`service-status ${service.available ? "ready" : "unavailable"}`}><strong>{service.available ? tr("配音服务可用", "Voice service ready") : tr("配音服务不可用", "Voice service unavailable")}</strong><span>{service.message}</span></div>
        <section className="voice-toolbar">
          <label className="search-box"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称或 ID" /></label>
          <div className="voice-filter-row">
            {[["all", "不限"], ["female", "女声"], ["male", "男声"], ["boy", "男童"], ["girl", "女童"], ["neutral", "中性"]].map(([value, label]) => <button className={gender === value ? "active" : ""} key={value} type="button" onClick={() => setGender(value)}>{label}</button>)}
            <button className={favoritesOnly ? "active" : ""} type="button" onClick={() => user ? setFavoritesOnly((value) => !value) : navigate(`/login?redirect=${encodeURIComponent("/voices")}`)}><Heart />我的收藏</button>
          </div>
        </section>
        <div className="voice-layout">
          <section>
            <div className="catalog-summary">{tr(`共 ${filteredVoices.length} 个音色`, `${filteredVoices.length} voices`)}</div>
            <div className="voice-grid">
              {filteredVoices.map((voice) => (
                <article className={`voice-card ${selectedId === voice.id ? "selected" : ""}`} key={voice.id} onClick={() => setSelectedId(voice.id)}>
                  <div className="voice-avatar"><Mic2 /></div>
                  <div className="voice-info"><h3>{voice.name}</h3><p>{voice.description}</p><span>{voice.gender_label} · {voice.language} · {voice.model}</span></div>
                  <div className="voice-card-actions">
                    <button type="button" aria-label={`试听 ${voice.name}`} onClick={(event) => { event.stopPropagation(); void audition(voice); }}>{playingId === voice.id ? <Pause /> : <Play />}</button>
                    <button className={favorites.has(voice.id) ? "selected" : ""} type="button" aria-label={`收藏 ${voice.name}`} onClick={(event) => { event.stopPropagation(); void save(voice.id); }}><Heart fill={favorites.has(voice.id) ? "currentColor" : "none"} /></button>
                  </div>
                </article>
              ))}
            </div>
            {!filteredVoices.length && <div className="empty-state">{favoritesOnly ? tr("还没有收藏音色", "No favorite voices yet") : service.message}</div>}
          </section>
          <aside className="tts-panel">
            <div className="section-title"><span>{tr("制作配音", "Create narration")}</span><small>{selectedVoice?.name || tr("未选择音色", "No voice selected")}</small></div>
            <form onSubmit={(event) => void submit(event)}>
              <label><span>{tr("配音文案", "Script")}</span><textarea maxLength={5000} value={text} onChange={(event) => setText(event.target.value)} placeholder={tr("输入需要配音的文案", "Enter the script to narrate")} /><small>{text.length} / 5000</small></label>
              <label><span>{tr("语速", "Speed")}: {speed.toFixed(1)}x</span><input type="range" min="0.5" max="2" step="0.1" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} /></label>
              {error && <div className="notice error">{error}</div>}
              <button className="primary-button" disabled={generating || !service.available || !selectedVoice || !text.trim()} type="submit">{generating ? <LoaderCircle className="spin" /> : <Mic2 />}{generating ? tr("生成中", "Generating") : tr("生成配音", "Generate narration")}</button>
            </form>
            {audio && <div className="audio-result"><strong>{tr("配音已生成", "Narration ready")}</strong><audio src={audio.url} controls /><a href={audio.url} download>{tr("下载配音", "Download audio")}</a><small>{tr(`时长约 ${audio.duration.toFixed(1)} 秒`, `About ${audio.duration.toFixed(1)} seconds`)}</small></div>}
          </aside>
        </div>
      </main>
    </Layout>
  );
}
