"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import LoginModal from "@/components/LoginModal";
import DemoFlowModal from "@/components/DemoFlowModal";
import SourcesPanel from "@/components/SourcesPanel";
import ChatPanel from "@/components/ChatPanel";
import RecommendationsPanel from "@/components/RecommendationsPanel";
import PushNotificationToast, { useWebSocket, PushNotification } from "@/components/PushNotification";
import ProfileVisualization from "@/components/ProfileVisualization";
import ScheduleManager from "@/components/ScheduleManager";
import { UserInfo, authApi } from "@/lib/api";

export default function Home() {
  const [session, setSession] = useState<string | null>(null);
  const [user, setUser] = useState<string | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [showDemo, setShowDemo] = useState(false);
  const [showRecommendations, setShowRecommendations] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);
  const [statsKey, setStatsKey] = useState(0);
  const [selectedFolderIds, setSelectedFolderIds] = useState<number[]>([]);
  const [currentNotification, setCurrentNotification] = useState<PushNotification | null>(null);
  const [sourcesExpanded, setSourcesExpanded] = useState(true);

  // WebSocket 连接，用于接收推送通知
  const { connected } = useWebSocket({
    sessionId: session,
    onNotification: (notification) => {
      setCurrentNotification(notification);
    },
  });

  // 拖拽调整宽度
  const [leftWidth, setLeftWidth] = useState(320);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLElement>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging || !containerRef.current) return;
    const containerRect = containerRef.current.getBoundingClientRect();
    const newWidth = e.clientX - containerRect.left;
    // 限制最小 200px，最大 50% 容器宽度
    const min = 200;
    const max = containerRect.width * 0.5;
    setLeftWidth(Math.max(min, Math.min(max, newWidth)));
  }, [isDragging]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  useEffect(() => {
    if (isDragging) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    } else {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  useEffect(() => {
    const s = localStorage.getItem("bili_session");
    const u = localStorage.getItem("bili_user");
    if (s && u) {
      setSession(s);
      setUser(u);
    }
  }, []);

  const onLogin = (sid: string, info: UserInfo) => {
    setSession(sid);
    setUser(info.uname);
    setShowLogin(false);
    localStorage.setItem("bili_session", sid);
    localStorage.setItem("bili_user", info.uname);
  };

  const onLogout = () => {
    if (session) authApi.logout(session).catch(() => { });
    setSession(null);
    setUser(null);
    localStorage.removeItem("bili_session");
    localStorage.removeItem("bili_user");
  };

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="brand">
          <div className="brand-mark">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M4 6h16M4 12h16M4 18h10" />
            </svg>
          </div>
          <div>
            <span className="brand-title">bilibili_calling</span>
            <span className="brand-subtitle">智能推荐 · 知识检索</span>
          </div>
        </div>

        <div className="topbar-actions">
          {user ? (
            <>
              <button
                onClick={() => setShowRecommendations(true)}
                className="btn btn-outline"
                style={{ marginRight: "10px" }}
              >
                推荐视频
              </button>
              <button
                onClick={() => setShowProfile(true)}
                className="btn btn-outline"
                style={{ marginRight: "10px" }}
                title="查看兴趣画像"
              >
                兴趣画像
              </button>
              <button
                onClick={() => setShowSchedule(true)}
                className="btn btn-outline"
                style={{ marginRight: "10px" }}
                title="管理定时任务"
              >
                定时任务
              </button>
              <span className="user-chip">
                <span>已登录</span>
                <strong>{user}</strong>
              </span>
              <button onClick={onLogout} className="btn-icon" title="退出">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
            </>
          ) : (
            <button onClick={() => setShowLogin(true)} className="btn btn-primary">
              扫码登录
            </button>
          )}
        </div>
      </header>

      <main className="app-main">
        {!session ? (
          <section className="hero">
            <div className="hero-content">
              <span className="hero-kicker">B站智能助手</span>
              <h1 className="hero-title">智能推荐 · 知识检索</h1>
              <p className="hero-desc">
                打破信息闭塞，懂人心的智能推荐系统。（休闲小助手）
              </p>

              <div className="hero-actions">
                <button className="btn btn-primary btn-lg" onClick={() => setShowLogin(true)}>
                  扫码登录开始构建
                </button>
                <button className="btn btn-outline" onClick={() => setShowDemo(true)}>
                  体验检索流程
                </button>
              </div>
            </div>

          </section>
        ) : (
          <section className="workspace" ref={containerRef}>
            <aside
              className="panel panel-sources"
              style={{
                width: sourcesExpanded ? leftWidth : 0,
                flexShrink: 0,
                overflow: sourcesExpanded ? "visible" : "hidden",
                transition: "width 0.3s ease"
              }}
            >
              <SourcesPanel
                sessionId={session}
                onBuildDone={() => setStatsKey((v) => v + 1)}
                onSelectionChange={setSelectedFolderIds}
              />
            </aside>

            {/* 拖拽分隔条 */}
            {sourcesExpanded && (
              <div
                className="resizer"
                onMouseDown={handleMouseDown}
                style={{ cursor: "col-resize" }}
              />
            )}

            <section className="panel panel-chat" style={{
                flex: 1,
                minWidth: 400,
                transition: "flex 0.3s ease"
              }}>
              <ChatPanel
                statsKey={statsKey}
                sessionId={session ?? undefined}
                folderIds={selectedFolderIds}
                onSourcesToggle={() => setSourcesExpanded(!sourcesExpanded)}
                sourcesExpanded={sourcesExpanded}
              />
            </section>
          </section>
        )}
      </main>

      <footer className="app-footer">
        <p>BiliMind © 2026 · 基于 Bilibili API 构建 · 由 AI 驱动</p>
      </footer>

      <LoginModal isOpen={showLogin} onClose={() => setShowLogin(false)} onSuccess={onLogin} />
      <DemoFlowModal isOpen={showDemo} onClose={() => setShowDemo(false)} />

      {showRecommendations && session && (
        <div className="modal-backdrop" onClick={() => setShowRecommendations(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <RecommendationsPanel
              sessionId={session}
              onClose={() => setShowRecommendations(false)}
            />
          </div>
        </div>
      )}

      {showProfile && session && (
        <div className="modal-backdrop" onClick={() => setShowProfile(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <ProfileVisualization
              sessionId={session}
              onClose={() => setShowProfile(false)}
            />
          </div>
        </div>
      )}

      {showSchedule && session && (
        <div className="modal-backdrop" onClick={() => setShowSchedule(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <ScheduleManager
              sessionId={session}
              folderIds={selectedFolderIds}
              onClose={() => setShowSchedule(false)}
            />
          </div>
        </div>
      )}

      {/* 推送通知弹窗 */}
      <PushNotificationToast
        notification={currentNotification}
        onClose={() => setCurrentNotification(null)}
      />

      {/* 连接状态指示器 */}
      {session && (
        <div className={`ws-indicator ${connected ? "connected" : "disconnected"}`}>
          <span className="ws-dot" />
          <span className="ws-text">{connected ? "已连接" : "连接中..."}</span>
        </div>
      )}
    </div>
  );
}
