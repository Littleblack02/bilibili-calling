"use client";

import { useEffect, useState, useCallback } from "react";

export interface PushNotification {
  type: string;
  session_id: string;
  data: {
    push_time: string;
    count: number;
    recommendations: Array<{
      bvid: string;
      title: string;
      author: string;
      pic?: string;
      reason?: string;
    }>;
    source: string;
    timestamp: string;
  };
}

interface Props {
  sessionId: string | null;
  onNotification?: (notification: PushNotification) => void;
}

export function useWebSocket({ sessionId, onNotification }: Props) {
  const [connected, setConnected] = useState(false);
  const [lastNotification, setLastNotification] = useState<PushNotification | null>(null);

  useEffect(() => {
    if (!sessionId) return;

    // 获取正确的 WebSocket URL
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") || "localhost:8000";
    const wsUrl = `${protocol}//${host}/recommendations/ws/${sessionId}`;

    let ws: WebSocket | null = null;
    let reconnectTimer: NodeJS.Timeout | null = null;
    let heartbeatInterval: NodeJS.Timeout | null = null;
    let isConnecting = false;

    const connect = () => {
      if (isConnecting || (ws && ws.readyState === WebSocket.OPEN)) {
        return;
      }

      isConnecting = true;

      try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log("WebSocket connected");
          setConnected(true);
          isConnecting = false;

          // 启动心跳
          heartbeatInterval = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: "ping" }));
            }
          }, 30000); // 每30秒发送一次心跳
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);

            // 处理不同类型的消息
            if (data.type === "pong") {
              // 心跳响应，忽略
              return;
            }

            // 推荐相关消息
            if (data.type === "recommendations" && Array.isArray(data.data)) {
              const notification: PushNotification = {
                type: data.type,
                session_id: sessionId,
                data: {
                  push_time: "now",
                  count: data.data.length,
                  recommendations: data.data,
                  source: "realtime",
                  timestamp: new Date().toISOString()
                }
              };
              setLastNotification(notification);
              onNotification?.(notification);
            }

            // 推送通知
            if (data.type === "daily_recommendations" || data.type === "external_recommendations") {
              setLastNotification(data);
              onNotification?.(data);
            }
          } catch (e) {
            console.error("Failed to parse WebSocket message:", e);
          }
        };

        ws.onclose = (event) => {
          setConnected(false);
          isConnecting = false;

          // 清理定时器
          if (heartbeatInterval) {
            clearInterval(heartbeatInterval);
            heartbeatInterval = null;
          }

          // 5秒后重连
          if (!reconnectTimer) {
            reconnectTimer = setTimeout(() => {
              reconnectTimer = null;
              connect();
            }, 5000);
          }
        };

        ws.onerror = (error) => {
          console.error("WebSocket error:", error);
          isConnecting = false;
        };
      } catch (e) {
        console.error("Failed to connect WebSocket:", e);
        isConnecting = false;
      }
    };

    connect();

    return () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (heartbeatInterval) {
        clearInterval(heartbeatInterval);
        heartbeatInterval = null;
      }
      if (ws) {
        ws.close();
        ws = null;
      }
    };
  }, [sessionId]);

  return { connected, lastNotification };
}

// 推送通知组件
export default function PushNotificationToast({
  notification,
  onClose,
}: {
  notification: PushNotification | null;
  onClose: () => void;
}) {
  if (!notification) return null;

  const { data } = notification;
  const timeLabel = data.push_time === "12:00" ? "午餐推荐" :
                     data.push_time === "18:00" ? "下班推荐" : "为您推荐";

  return (
    <div className="push-toast">
      <div className="push-toast-header">
        <span className="push-toast-icon">🎬</span>
        <span className="push-toast-title">{timeLabel}</span>
        <button onClick={onClose} className="push-toast-close" aria-label="关闭">
          ×
        </button>
      </div>
      <div className="push-toast-body">
        <p className="push-toast-desc">为您精选了 {data.count} 条视频</p>
        <div className="push-toast-videos">
          {data.recommendations.slice(0, 3).map((video, index) => (
            <div key={index} className="push-toast-video">
              {video.pic && (
                <img src={video.pic} alt={video.title} className="push-toast-thumb" />
              )}
              <div className="push-toast-info">
                <span className="push-toast-video-title">{video.title}</span>
                <span className="push-toast-author">@{video.author}</span>
              </div>
            </div>
          ))}
        </div>
        {data.recommendations.length > 3 && (
          <div className="push-toast-footer">
            <button className="btn btn-sm btn-outline">
              查看全部 ({data.count})
            </button>
          </div>
        )}
      </div>
      <style jsx>{`
        .push-toast {
          position: fixed;
          bottom: 24px;
          right: 24px;
          width: 340px;
          background: rgba(255, 255, 255, 0.98);
          border: 1px solid var(--border);
          border-radius: 16px;
          box-shadow: 0 20px 60px rgba(255, 94, 157, 0.2);
          backdrop-filter: blur(12px);
          z-index: 1000;
          animation: slideUp 0.4s ease;
          overflow: hidden;
        }

        .push-toast-header {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 14px 16px;
          background: linear-gradient(135deg, #ff5a9d 0%, #ff9ec4 100%);
          color: white;
        }

        .push-toast-icon {
          font-size: 18px;
        }

        .push-toast-title {
          font-weight: 600;
          font-size: 15px;
          flex: 1;
        }

        .push-toast-close {
          width: 24px;
          height: 24px;
          border-radius: 50%;
          border: none;
          background: rgba(255, 255, 255, 0.2);
          color: white;
          cursor: pointer;
          font-size: 18px;
          line-height: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s ease;
        }

        .push-toast-close:hover {
          background: rgba(255, 255, 255, 0.3);
        }

        .push-toast-body {
          padding: 16px;
        }

        .push-toast-desc {
          font-size: 13px;
          color: var(--muted);
          margin-bottom: 12px;
        }

        .push-toast-videos {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .push-toast-video {
          display: flex;
          gap: 10px;
          align-items: center;
          padding: 8px;
          border-radius: 10px;
          background: rgba(255, 94, 157, 0.05);
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .push-toast-video:hover {
          background: rgba(255, 94, 157, 0.1);
        }

        .push-toast-thumb {
          width: 48px;
          height: 36px;
          border-radius: 6px;
          object-fit: cover;
        }

        .push-toast-info {
          flex: 1;
          min-width: 0;
        }

        .push-toast-video-title {
          display: block;
          font-size: 13px;
          font-weight: 500;
          color: var(--ink);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          margin-bottom: 2px;
        }

        .push-toast-author {
          font-size: 11px;
          color: var(--muted);
        }

        .push-toast-footer {
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px dashed var(--border);
        }

        @keyframes slideUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
      `}</style>
    </div>
  );
}