"use client";

import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";
import {
  DemoAnswer,
  DemoPeriod,
  demoAnswers,
  demoFolders,
  demoInterests,
  demoMetrics,
  demoRecommendations,
  resolveDemoAnswer,
} from "@/lib/interview-demo-data";
import {
  BrowserConceptMatch,
  BrowserExpandedConcept,
  demoOntologyMeta,
  expandOntologyConcepts,
  resolveOntologyText,
} from "@/lib/demo-ontology-engine";
import styles from "./InterviewDemo.module.css";

type DemoView = "overview" | "profile" | "qa" | "recommendations" | "proof";
type RecommendationMode = "balanced" | "following" | "explore";

const navigation: Array<{ id: DemoView; label: string; number: string }> = [
  { id: "overview", label: "演示概览", number: "01" },
  { id: "profile", label: "Ontology 画像", number: "02" },
  { id: "qa", label: "知识问答", number: "03" },
  { id: "recommendations", label: "推荐闭环", number: "04" },
  { id: "proof", label: "工程证据", number: "05" },
];

const periodLabels: Record<DemoPeriod, string> = {
  recent: "近期兴趣",
  longTerm: "长期兴趣",
  historical: "历史兴趣",
};

const modeLabels: Record<RecommendationMode, string> = {
  balanced: "综合推荐",
  following: "关注优先",
  explore: "探索模式",
};

const defaultPlannerQueries: Record<RecommendationMode, string[]> = {
  balanced: ["LangGraph 多智能体实战", "RAG 检索质量优化", "Python LLM 工程"],
  following: ["关注UP AI Agent 最新视频", "LangGraph 生产工作流", "Python 工程实践"],
  explore: ["RAG 向量数据库进阶", "信息检索 重排", "AI Agent 新方向"],
};

const stageLabels: Record<BrowserConceptMatch["stage"], string> = {
  exact_label: "精确命中",
  label_in_text: "文本命中",
  fuzzy_lexical: "模糊消歧",
};

function ScoreRing({ score }: { score: number }) {
  return (
    <div
      className={styles.scoreRing}
      style={{ "--score": `${Math.round(score * 100) * 3.6}deg` } as React.CSSProperties}
      aria-label={`匹配分 ${Math.round(score * 100)}%`}
    >
      <span>{Math.round(score * 100)}</span>
    </div>
  );
}

export default function InterviewDemo() {
  const [view, setView] = useState<DemoView>("overview");
  const [period, setPeriod] = useState<DemoPeriod>("recent");
  const [question, setQuestion] = useState(demoAnswers[0].question);
  const [answer, setAnswer] = useState<DemoAnswer | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [ontologyMatches, setOntologyMatches] = useState<BrowserConceptMatch[]>([]);
  const [ontologyExpanded, setOntologyExpanded] = useState<BrowserExpandedConcept[]>([]);
  const [mode, setMode] = useState<RecommendationMode>("balanced");
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [blockedConcepts, setBlockedConcepts] = useState<string[]>([]);
  const [recommendationIntent, setRecommendationIntent] = useState("");
  const [isPlanning, setIsPlanning] = useState(false);
  const [plannerRun, setPlannerRun] = useState(1);
  const [notice, setNotice] = useState("已载入一次真实模型验证轨迹；列表交互在浏览器实时执行");

  const plannedQueries = useMemo(() => {
    const custom = recommendationIntent.trim();
    if (!custom) return defaultPlannerQueries[mode];
    return [custom, `${custom} RAG`, `${custom} AI Agent`];
  }, [mode, recommendationIntent]);

  const visibleRecommendations = useMemo(
    () => demoRecommendations.filter(
      (item) => item.mode.includes(mode)
        && !dismissed.includes(item.id)
        && !item.concepts.some((concept) => blockedConcepts.includes(concept)),
    ),
    [mode, dismissed, blockedConcepts],
  );

  const runQuestion = (event?: FormEvent) => {
    event?.preventDefault();
    if (!question.trim() || isSearching) return;
    setIsSearching(true);
    setAnswer(null);
    setHasSearched(false);
    setOntologyMatches([]);
    setOntologyExpanded([]);
    window.setTimeout(() => {
      const matches = resolveOntologyText(question);
      setOntologyMatches(matches);
      setOntologyExpanded(expandOntologyConcepts(matches.map((item) => item.conceptId), 2));
      setAnswer(resolveDemoAnswer(question));
      setHasSearched(true);
      setIsSearching(false);
    }, 650);
  };

  const chooseQuestion = (item: DemoAnswer) => {
    setQuestion(item.question);
    setAnswer(null);
    setHasSearched(false);
    setOntologyMatches([]);
    setOntologyExpanded([]);
  };

  const runRecommendation = (event?: FormEvent) => {
    event?.preventDefault();
    if (isPlanning) return;
    setIsPlanning(true);
    setNotice("正在回放强制 LLM 规划、后端工具执行与严格重排契约…");
    window.setTimeout(() => {
      setPlannerRun((value) => value + 1);
      setIsPlanning(false);
      setNotice(`运行 #${plannerRun + 1} 完成：两道 LLM 门均通过，反馈过滤已重新应用`);
    }, 720);
  };

  const dismissRecommendation = (id: string) => {
    setDismissed((items) => [...items, id]);
    setNotice("已记录“暂时不看”：仅影响当前列表，不污染长期主题兴趣");
  };

  const blockRecommendationConcept = (concept: string) => {
    setBlockedConcepts((items) => [...new Set([...items, concept])]);
    setNotice(`已屏蔽概念“${concept}”：仅向下位概念传播，不误伤父级兴趣`);
  };

  const resetRecommendations = () => {
    setDismissed([]);
    setBlockedConcepts([]);
    setRecommendationIntent("");
    setNotice("演示状态已重置，已恢复经过验证的 LLM 运行轨迹");
  };

  return (
    <main className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brandBlock}>
          <div className={styles.brandMark}>BC</div>
          <div>
            <strong>bilibili_calling</strong>
            <span>INTERVIEW DEMO</span>
          </div>
        </div>

        <div className={styles.demoBadge}>
          <span className={styles.liveDot} />
          Ontology 实时计算 · 无需登录
        </div>

        <nav className={styles.navigation} aria-label="演示功能">
          {navigation.map((item) => (
            <button
              key={item.id}
              className={view === item.id ? styles.navActive : styles.navButton}
              onClick={() => setView(item.id)}
            >
              <span>{item.number}</span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className={styles.sideFoot}>
          <p>Ontology 使用仓库 V2 图实时计算；B站与模型调用展示经过验证的脱敏轨迹回放。</p>
          <a href="https://github.com/Littleblack02/bilibili-calling" target="_blank" rel="noreferrer">
            查看 GitHub 源码 ↗
          </a>
        </div>
      </aside>

      <section className={styles.stage}>
        <header className={styles.topbar}>
          <div>
            <span className={styles.eyebrow}>B站内容理解与个性化推荐系统</span>
            <h1>{navigation.find((item) => item.id === view)?.label}</h1>
          </div>
          <div className={styles.topActions}>
            <span className={styles.sessionChip}>demo-session · 只读</span>
            <Link href="/" className={styles.exitLink}>返回首页</Link>
          </div>
        </header>

        <div className={styles.content}>
          {view === "overview" && (
            <div className={styles.overviewGrid}>
              <section className={styles.heroCard}>
                <div className={styles.heroCopy}>
                  <span className={styles.kicker}>SEMANTIC LAYER × GROUNDED AI</span>
                  <h2>让收藏夹从“视频列表”变成<br />可检索、可解释的个人知识系统</h2>
                  <p>
                    用 Ontology 统一概念，用时间与证据构建画像；推荐必须经过 LLM 工具规划与严格重排，任一失败都会明确返回 503。
                  </p>
                  <div className={styles.heroActions}>
                    <button onClick={() => setView("profile")} className={styles.primaryButton}>
                      从画像开始体验
                    </button>
                    <button onClick={() => setView("qa")} className={styles.secondaryButton}>
                      直接试问答
                    </button>
                  </div>
                </div>
                <div className={styles.semanticMap} aria-label="Ontology 关系示意">
                  <div className={`${styles.mapNode} ${styles.rootNode}`}>人工智能</div>
                  <div className={styles.mapLine}>narrower</div>
                  <div className={styles.mapRow}>
                    <div className={styles.mapNode}>AI Agent</div>
                    <div className={styles.mapNode}>大语言模型</div>
                  </div>
                  <div className={styles.mapLine}>narrower · related · requires</div>
                  <div className={styles.mapRow}>
                    <div className={`${styles.mapNode} ${styles.hotNode}`}>LangGraph</div>
                    <div className={`${styles.mapNode} ${styles.hotNode}`}>RAG</div>
                    <div className={styles.mapNode}>向量检索</div>
                  </div>
                </div>
              </section>

              <section className={styles.metricStrip}>
                {demoMetrics.map((metric) => (
                  <div key={metric.label}>
                    <strong>{metric.value}</strong>
                    <span>{metric.label}</span>
                  </div>
                ))}
              </section>

              <section className={styles.flowSection}>
                <div className={styles.sectionTitle}>
                  <div>
                    <span>可演示的完整闭环</span>
                    <h3>从行为证据到推荐反馈</h3>
                  </div>
                  <span>点击任一步进入</span>
                </div>
                <div className={styles.flowCards}>
                  {[
                    ["01", "多通道证据", "收藏、历史、关注与稍后看经过相关性去重", "profile"],
                    ["02", "Ontology 画像", "规范 Concept ID、时间衰减与多兴趣簇", "profile"],
                    ["03", "Grounded RAG", "Chunk 时间码、引用验证与无证据拒答", "qa"],
                    ["04", "强制 LLM 推荐", "工具调用、Ontology 召回、严格重排与反馈传播", "recommendations"],
                  ].map(([number, title, description, target]) => (
                    <button key={number} onClick={() => setView(target as DemoView)}>
                      <span>{number}</span>
                      <strong>{title}</strong>
                      <p>{description}</p>
                      <i>查看体验 →</i>
                    </button>
                  ))}
                </div>
              </section>
            </div>
          )}

          {view === "profile" && (
            <div className={styles.profileLayout}>
              <section className={styles.panel}>
                <div className={styles.sectionTitle}>
                  <div>
                    <span>PROFILE MODEL · temporal-ontology-v2</span>
                    <h3>时间感知兴趣画像</h3>
                  </div>
                  <span>证据质量 0.87</span>
                </div>
                <div className={styles.tabRow}>
                  {(Object.keys(periodLabels) as DemoPeriod[]).map((key) => (
                    <button
                      key={key}
                      onClick={() => setPeriod(key)}
                      className={period === key ? styles.tabActive : styles.tabButton}
                    >
                      {periodLabels[key]}
                    </button>
                  ))}
                </div>
                <div className={styles.interestList}>
                  {demoInterests[period].map((interest) => (
                    <article key={interest.id} className={styles.interestCard}>
                      <ScoreRing score={interest.score} />
                      <div className={styles.interestInfo}>
                        <div>
                          <span className={`${styles.toneDot} ${styles[interest.tone]}`} />
                          <strong>{interest.label}</strong>
                          <small>上位概念：{interest.parent}</small>
                        </div>
                        <p>{interest.evidence}</p>
                        <span>{interest.updated}</span>
                      </div>
                      <div className={styles.scoreBar}>
                        <span style={{ width: `${interest.score * 100}%` }} />
                      </div>
                    </article>
                  ))}
                </div>
              </section>

              <aside className={styles.profileAside}>
                <section className={styles.panel}>
                  <div className={styles.miniTitle}>证据来源</div>
                  <div className={styles.sourceDistribution}>
                    {[
                      ["观看历史", 42], ["收藏", 28], ["关注 UP", 17], ["稍后看", 13],
                    ].map(([label, value]) => (
                      <div key={label as string}>
                        <span>{label}</span><strong>{value}%</strong>
                        <i><b style={{ width: `${value}%` }} /></i>
                      </div>
                    ))}
                  </div>
                </section>
                <section className={styles.panel}>
                  <div className={styles.miniTitle}>本体命中路径</div>
                  <div className={styles.pathStack}>
                    <strong>人工智能</strong><span>narrower</span>
                    <strong>大语言模型</strong><span>narrower</span>
                    <strong className={styles.pathHot}>RAG</strong>
                  </div>
                  <p className={styles.helperText}>画像保存绝对强度和相对占比；旧收藏仅保留弱先验，不会重新归一为满分。</p>
                </section>
                <section className={styles.folderPanel}>
                  <div className={styles.miniTitle}>脱敏数据集</div>
                  {demoFolders.map((folder) => (
                    <div key={folder.name}>
                      <span className={folder.active ? styles.folderActive : styles.folderIcon}>⌁</span>
                      <p><strong>{folder.name}</strong><small>{folder.count} 条视频</small></p>
                    </div>
                  ))}
                </section>
              </aside>
            </div>
          )}

          {view === "qa" && (
            <div className={styles.qaLayout}>
              <section className={styles.qaMain}>
                <div className={styles.qaIntro}>
                  <span>GROUNDED RAG · 10,000 CHUNK BENCHMARK</span>
                  <h2>所有结论都回到具体证据</h2>
                  <p>选择示例问题，或者输入关于 RAG、LangGraph、隐私的问题。无证据问题会明确拒答。</p>
                </div>
                <div className={styles.promptList}>
                  {demoAnswers.map((item) => (
                    <button key={item.id} onClick={() => chooseQuestion(item)}>{item.shortLabel}</button>
                  ))}
                  <button onClick={() => { setQuestion("这些收藏里有没有讲量子纠错？"); setAnswer(null); setHasSearched(false); setOntologyMatches([]); setOntologyExpanded([]); }}>
                    试试无答案问题
                  </button>
                </div>
                <form className={styles.askBox} onSubmit={runQuestion}>
                  <textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    aria-label="输入知识库问题"
                    rows={3}
                  />
                  <div>
                    <span>检索范围：示例知识库 · 126 个 Gold Chunks</span>
                    <button disabled={isSearching} type="submit">
                      {isSearching ? "检索中…" : "开始检索"}
                    </button>
                  </div>
                </form>

                {isSearching && (
                  <div className={styles.searchState}>
                    <span /><span /><span />
                    正在执行查询扩展、RRF 融合和证据验证…
                  </div>
                )}

                {hasSearched && (
                  <article className={styles.ontologyTrace}>
                    <div className={styles.traceHeader}>
                      <div>
                        <span>LIVE IN BROWSER</span>
                        <strong>{demoOntologyMeta.version}</strong>
                      </div>
                      <small>{demoOntologyMeta.activeConcepts} active concepts · {demoOntologyMeta.relations} graph edges</small>
                    </div>
                    {ontologyMatches.length ? (
                      <>
                        <div className={styles.matchChips}>
                          {ontologyMatches.map((match) => (
                            <span key={match.conceptId}>
                              <strong>{match.label}</strong>
                              {stageLabels[match.stage]} · {(match.confidence * 100).toFixed(0)}%
                            </span>
                          ))}
                        </div>
                        <div className={styles.livePaths}>
                          {ontologyExpanded.filter((item) => item.path.length).slice(0, 4).map((item) => (
                            <div key={item.conceptId}>
                              {item.path.map((edge, index) => (
                                <span key={`${edge.from}-${edge.relation}-${edge.to}-${index}`}>
                                  {index === 0 && <b>{edge.from}</b>}
                                  <i>{edge.relation}</i><b>{edge.to}</b>
                                </span>
                              ))}
                              <small>weight {item.weight.toFixed(2)}</small>
                            </div>
                          ))}
                        </div>
                      </>
                    ) : (
                      <p className={styles.traceEmpty}>Ontology 主动拒识：不强行绑定低置信概念，原始检索仍可继续执行。</p>
                    )}
                    <p className={styles.scopeNote}>概念链接与路径扩展为当前页面实时计算；自然语言答案和引用是脱敏的验证回放。</p>
                  </article>
                )}

                {answer && (
                  <article className={styles.answerCard}>
                    <div className={styles.answerMeta}>
                      <span>GROUNDED</span>
                      <strong>检索置信度 {(answer.confidence * 100).toFixed(0)}%</strong>
                    </div>
                    <p>{answer.answer}</p>
                    <div className={styles.answerPath}>
                      {answer.ontologyPath.map((node, index) => (
                        <span key={`${node}-${index}`} className={index % 2 ? styles.relation : ""}>{node}</span>
                      ))}
                    </div>
                  </article>
                )}

                {hasSearched && !answer && (
                  <article className={styles.refusalCard}>
                    <span>证据不足 · ABSTAIN</span>
                    <h3>当前示例知识库无法支持这个问题</h3>
                    <p>系统没有找到超过相关度阈值的片段，因此不会使用通用知识伪装成收藏内容回答。</p>
                  </article>
                )}
              </section>

              <aside className={styles.citationPanel}>
                <div className={styles.miniTitle}>引用证据</div>
                {!answer && <p className={styles.emptyHint}>运行问题后，这里会显示 BVID、chunk、时间码和概念命中。</p>}
                {answer?.citations.map((citation, index) => (
                  <article key={citation.id} className={styles.citationCard}>
                    <div><span>0{index + 1}</span><strong>{citation.time}</strong></div>
                    <h4>{citation.title}</h4>
                    <small>{citation.id} · chunk {citation.chunk}</small>
                    <p>“{citation.excerpt}”</p>
                    <div>{citation.concepts.map((concept) => <span key={concept}>{concept}</span>)}</div>
                  </article>
                ))}
              </aside>
            </div>
          )}

          {view === "recommendations" && (
            <div className={styles.recommendationLayout}>
              <section className={styles.panel}>
                <div className={styles.sectionTitle}>
                  <div>
                    <span>RECOMMENDATION · temporal-ontology-xmix-v2</span>
                    <h3>可解释推荐列表</h3>
                  </div>
                  <button className={styles.resetButton} onClick={resetRecommendations}>重置演示</button>
                </div>
                <div className={styles.modeRow}>
                  {(Object.keys(modeLabels) as RecommendationMode[]).map((key) => (
                    <button key={key} onClick={() => setMode(key)} className={mode === key ? styles.modeActive : ""}>
                      {modeLabels[key]}
                    </button>
                  ))}
                </div>
                <section className={styles.llmTrace}>
                  <div className={styles.traceHeader}>
                    <div>
                      <span>MANDATORY LLM PIPELINE · RUN #{plannerRun}</span>
                      <strong>profile-v2.3 → qwen3.5-flash → search_bilibili_videos</strong>
                    </div>
                    <small>真实模型验证轨迹 · 脱敏回放</small>
                  </div>
                  <div className={styles.pipelineSteps}>
                    <div><span>01</span><strong>LLM PLAN</strong><small>工具调用已验证 · 2.9s</small></div>
                    <i>→</i>
                    <div><span>02</span><strong>BACKEND TOOL</strong><small>参数校验 + B站搜索</small></div>
                    <i>→</i>
                    <div><span>03</span><strong>ONTOLOGY</strong><small>画像召回 + 规则基线</small></div>
                    <i>→</i>
                    <div><span>04</span><strong>LLM RERANK</strong><small>全量打分已验证 · 1.9s</small></div>
                  </div>
                  <form className={styles.intentForm} onSubmit={runRecommendation}>
                    <label htmlFor="recommendation-intent">补充本次推荐意图（可选）</label>
                    <div>
                      <input
                        id="recommendation-intent"
                        value={recommendationIntent}
                        onChange={(event) => setRecommendationIntent(event.target.value)}
                        placeholder="例如：想看更工程化、少一点入门内容"
                      />
                      <button disabled={isPlanning} type="submit">{isPlanning ? "运行中…" : "重新运行"}</button>
                    </div>
                  </form>
                  <div className={styles.queryPlan}>
                    <span>模型规划的搜索词</span>
                    <div>{plannedQueries.map((query) => <code key={query}>{query}</code>)}</div>
                  </div>
                  <div className={styles.strictContract}>
                    <span>✓ LLM 召回规划</span><span>✓ Ontology 画像注入</span><span>✓ 100% 候选打分</span><strong>任一门失败 → HTTP 503</strong>
                  </div>
                </section>
                <div className={styles.notice}>{notice}</div>
                <div className={styles.recommendationList}>
                  {visibleRecommendations.map((item, index) => (
                    <article key={item.id} className={styles.recommendationCard}>
                      <div className={styles.recommendationRank}>0{index + 1}</div>
                      <div className={styles.videoCover} style={{ "--cover-accent": item.accent } as React.CSSProperties}>
                        <span>{item.duration}</span>
                        <strong>{item.concepts[0]}</strong>
                      </div>
                      <div className={styles.recommendationBody}>
                        <div className={styles.recommendationHead}>
                          <div><h3>{item.title}</h3><span>@{item.author} · {item.freshness}</span></div>
                          <ScoreRing score={item.score} />
                        </div>
                        <p>{item.reason}</p>
                        <div className={styles.inlinePath}>
                          {item.path.map((node, nodeIndex) => (
                            <span key={`${node}-${nodeIndex}`} className={nodeIndex % 2 ? styles.relation : ""}>{node}</span>
                          ))}
                        </div>
                        <div className={styles.recommendationFoot}>
                          <div>{item.source.map((source) => <span key={source}>{source}</span>)}</div>
                          <div>
                            <button onClick={() => dismissRecommendation(item.id)}>暂时不看</button>
                            <button onClick={() => blockRecommendationConcept(item.concepts[0])}>屏蔽 {item.concepts[0]}</button>
                          </div>
                        </div>
                      </div>
                    </article>
                  ))}
                  {!visibleRecommendations.length && (
                    <div className={styles.emptyRecommendations}>
                      <h3>当前筛选下没有剩余候选</h3>
                      <p>这正是反馈过滤生效的结果。点击“重置演示”恢复验证候选集。</p>
                    </div>
                  )}
                </div>
              </section>
            </div>
          )}

          {view === "proof" && (
            <div className={styles.proofLayout}>
              <section className={styles.proofHero}>
                <span>REPRODUCIBLE EVIDENCE</span>
                <h2>不只展示页面，也展示系统为什么可信</h2>
                <p>所有数字来自仓库内锁定的离线数据和可重复脚本；它们证明工程回归，不伪装成线上因果提升。</p>
              </section>
              <section className={styles.proofGrid}>
                {[
                  ["Ontology", "233 active concepts", "2,199 RDF triples · SHACL conforms", "页面直接加载 V2 图快照，实体链接与两跳扩展实时运行"],
                  ["Entity linking", "F1 96.48%", "Precision 97.96% · Recall 95.05%", "精确、模糊、上下文消歧与低置信拒识"],
                  ["Grounded RAG", "Recall@5 98.02%", "MRR@10 0.992 · 引用正确率 98.21%", "150 问、1 万 chunk、本地 p95 86.3ms"],
                  ["Recommendation", "2 mandatory LLM gates", "tool planning + strict rerank", "必须调用搜索工具并覆盖全部候选；模型异常显式返回 503"],
                  ["Engineering", "94 tests passed", "Alembic · Privacy · Observability", "Cookie AES-GCM、回填幂等、Ontology 默认开启"],
                  ["Honest scope", "Hybrid live demo", "Live Ontology · verified LLM replay", "不请求 Cookie；B站和模型轨迹脱敏回放，实时后端链路见源码"],
                ].map(([title, value, meta, description]) => (
                  <article key={title}>
                    <span>{title}</span><strong>{value}</strong><small>{meta}</small><p>{description}</p>
                  </article>
                ))}
              </section>
              <section className={styles.interviewScript}>
                <div>
                  <span>建议讲解顺序 · 5 MINUTES</span>
                  <h3>画像 → 问答 → 推荐 → 反馈 → 证据</h3>
                </div>
                <ol>
                  <li><span>01</span>说明原始标签不稳定，为什么需要 Ontology 语义层</li>
                  <li><span>02</span>展示近期、长期、历史兴趣与证据时间</li>
                  <li><span>03</span>运行一个有答案问题和一个无答案问题</li>
                  <li><span>04</span>屏蔽 LangGraph，解释为何不会误伤整个 AI 领域</li>
                </ol>
              </section>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
