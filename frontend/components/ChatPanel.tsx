"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatApi, API_BASE_URL } from "@/lib/api";
import SourcesToggleButton from "@/components/SourcesToggleButton";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Array<{
    bvid: string;
    title: string;
    url: string;
    chunk_index?: number;
    start_time?: number | null;
    end_time?: number | null;
  }>;
  grounding?: {
    grounded?: boolean;
    retrieval_confidence?: number;
    answerability?: string;
  };
}

interface Props {
  statsKey?: number;
  sessionId?: string;
  folderIds?: number[];
  onSourcesToggle?: () => void;
  sourcesExpanded?: boolean;
}

type ChatMode = "rag" | "agent";

export default function ChatPanel({ statsKey, sessionId, folderIds, onSourcesToggle, sourcesExpanded }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatMode, setChatMode] = useState<ChatMode>("rag");
  const endRef = useRef<HTMLDivElement>(null);
  const marker = "[[SOURCES_JSON]]";

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // RAG模式发送
  const sendRAG = async (q: string, assistantId: string) => {
    const response = await fetch(`${API_BASE_URL}/chat/ask/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        question: q,
        session_id: sessionId,
        folder_ids: folderIds,
      }),
    });

    if (!response.ok || !response.body) {
      throw new Error("流式接口不可用");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let done = false;
    let buffer = "";
    let sourcesJson = "";
    let inSources = false;

    while (!done) {
      const { value, done: doneReading } = await reader.read();
      done = doneReading;
      if (value) {
        const chunk = decoder.decode(value, { stream: !done });
        if (chunk) {
          if (inSources) {
            sourcesJson += chunk;
          } else {
            buffer += chunk;
            const markerIndex = buffer.indexOf(marker);
            if (markerIndex !== -1) {
              const contentPart = buffer.slice(0, markerIndex);
              sourcesJson = buffer.slice(markerIndex + marker.length);
              buffer = contentPart;
              inSources = true;
            }
          }
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: buffer } : m
            )
          );
        }
      }
    }

    if (sourcesJson) {
      try {
        const parsed = JSON.parse(sourcesJson);
        const parsedSources = Array.isArray(parsed) ? parsed : parsed?.sources;
        const grounding = Array.isArray(parsed) ? undefined : parsed?.grounding;
        if (Array.isArray(parsedSources)) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, sources: parsedSources, grounding } : m
            )
          );
        }
      } catch {
        // 忽略解析错误
      }
    }
  };

  // Agent模式发送
  const sendAgent = async (q: string, assistantId: string) => {
    const response = await fetch(`${API_BASE_URL}/agent/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: q,
        session_id: sessionId,
        stream: true,
      }),
    });

    if (!response.ok || !response.body) {
      throw new Error("Agent接口不可用");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      if (value) {
        const chunk = decoder.decode(value, { stream: false });
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6);
            if (dataStr === "[DONE]") continue;

            try {
              const data = JSON.parse(dataStr);

              if (data.type === "ai" && data.content) {
                buffer += data.content;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId ? { ...m, content: buffer } : m
                  )
                );
              } else if (data.type === "tool") {
                // 工具调用结果：仅记录到日志，不显示在前端
                // const toolName = data.name || "工具";
                // const toolContent = data.content || "";
                // buffer += `\n\n[调用工具: ${toolName}]\n${toolContent}`;
                // setMessages((prev) =>
                //   prev.map((m) =>
                //     m.id === assistantId ? { ...m, content: buffer } : m
                //   )
                // );
              } else if (data.type === "error") {
                throw new Error(data.content || "Agent执行出错");
              }
            } catch {
              // 忽略解析错误
            }
          }
        }
      }
    }
  };

  const send = async () => {
    if (!input.trim() || loading) return;
    const q = input.trim();
    setInput("");

    // 为每次对话创建唯一的 ID
    const userId = Date.now().toString();
    const assistantId = (Date.now() + 1).toString();

    // 清空历史显示，只显示当前问题和答案
    // 后端的 memory 系统仍然会保留上下文
    setMessages([
      { id: userId, role: "user", content: q },
      { id: assistantId, role: "assistant", content: "", sources: [] },
    ]);
    setLoading(true);

    try {
      if (chatMode === "rag") {
        await sendRAG(q, assistantId);
      } else {
        await sendAgent(q, assistantId);
      }
    } catch (e) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content: `错误: ${e instanceof Error ? e.message : "请求失败"}`,
              }
            : m
        )
      );
    }

    setLoading(false);
  };

  return (
    <div className="panel-inner" style={{ position: "relative" }}>
      {/* 收藏夹切换按钮 - 绝对定位在左上角 */}
      <div style={{ position: "absolute", top: "16px", left: "16px", zIndex: 10 }}>
        <SourcesToggleButton
          onClick={onSourcesToggle || (() => {})}
          title={sourcesExpanded ? "收起收藏夹" : "展开收藏夹"}
        />
      </div>

      <div className="panel-header">
        <div className="flex gap-3 items-center w-full justify-center">
          {/* 模式切换 - 液态玻璃效果 */}
          <div className="glass-mode-switcher">
            <div className="glass-slider" style={{
              transform: chatMode === "rag" ? "translateX(0)" : "translateX(100%)"
            }} />
            <button
              onClick={() => setChatMode("rag")}
              className={`glass-mode-btn ${chatMode === "rag" ? "active" : ""}`}
            >
              <span className="mode-icon">📚</span>
              RAG模式
            </button>
            <button
              onClick={() => setChatMode("agent")}
              className={`glass-mode-btn ${chatMode === "agent" ? "active" : ""}`}
            >
              <span className="mode-icon">🤖</span>
              Agent模式
            </button>
          </div>

          {messages.length > 0 && (
            <button onClick={() => setMessages([])} className="btn btn-ghost btn-sm" title="清空">
              清空
            </button>
          )}
        </div>
      </div>

      <div className="panel-body">
        <div className="chat-scroll">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div>
                <div className="status-pill">
                  {chatMode === "rag" ? "检索就绪" : "Agent就绪"}
                </div>
                <p className="text-sm text-[var(--muted)] mt-3">
                  {chatMode === "rag"
                    ? "把收藏夹变成可提问的知识库"
                    : "支持B站搜索和网络搜索的智能助手"}
                </p>
              </div>
              <div className="prompt-grid">
                {chatMode === "rag" ? (
                  <>
                    {[
                      "总结收藏夹里最有价值的内容",
                      "有哪些适合快速复习的系列？",
                      "列出与某个主题相关的视频并给出关键点",
                      "用一句话概括每个视频的重点",
                    ].map((q, i) => (
                      <button key={i} onClick={() => setInput(q)} className="prompt-chip">
                        {q}
                      </button>
                    ))}
                  </>
                ) : (
                  <>
                    {[
                      "帮我搜索Python教程",
                      "推荐一些AI相关的视频",
                      "查找最新的技术教程",
                      "搜索机器学习入门内容",
                    ].map((q, i) => (
                      <button key={i} onClick={() => setInput(q)} className="prompt-chip">
                        {q}
                      </button>
                    ))}
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="chat-window">
              {messages.map((m) => (
                <div key={m.id} className={`message ${m.role}`}>
                  <div className="message-bubble">
                    <ReactMarkdown className="markdown" remarkPlugins={[remarkGfm]}>
                      {m.content}
                    </ReactMarkdown>
                    {m.grounding && (
                      <div className="mt-2 text-xs text-gray-500">
                        {m.grounding.grounded ? "✓ 已由收藏证据支持" : "证据不足，已拒绝补全"}
                        {typeof m.grounding.retrieval_confidence === "number" && (
                          <> · 检索置信度 {Math.round(m.grounding.retrieval_confidence * 100)}%</>
                        )}
                      </div>
                    )}
                    {m.sources && m.sources.length > 0 && (
                      <div className="source-list">
                        {m.sources.map((s, i) => (
                          <a key={i}
                            href={typeof s.start_time === "number"
                              ? `${s.url}${s.url.includes("?") ? "&" : "?"}t=${Math.floor(s.start_time)}`
                              : s.url}
                            target="_blank" rel="noopener noreferrer" className="source-link">
                            {s.title}
                            {typeof s.chunk_index === "number" ? ` #${s.chunk_index}` : ""}
                            {typeof s.start_time === "number" ? ` · ${Math.floor(s.start_time)}s` : ""}
                            {typeof s.end_time === "number" ? `–${Math.floor(s.end_time)}s` : ""}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="message assistant">
                  <div className="message-bubble">
                    <div className="flex gap-1">
                      {[0, 1, 2].map((i) => (
                        <div key={i} className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse" style={{ animationDelay: `${i * 0.15}s` }} />
                      ))}
                    </div>
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>
          )}
        </div>
      </div>

      <div className="panel-footer">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            placeholder={chatMode === "rag" ? "输入问题..." : "搜索或提问..."}
            className="input"
          />
          <button onClick={send} disabled={!input.trim() || loading} className="btn btn-primary">
            发送
          </button>
        </div>
        {chatMode === "agent" && (
          <div className="text-xs text-gray-500 mt-1">
            Agent模式支持B站搜索、网络搜索等功能
          </div>
        )}
      </div>
    </div>
  );
}
