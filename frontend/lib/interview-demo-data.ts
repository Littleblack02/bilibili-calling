export type DemoPeriod = "recent" | "longTerm" | "historical";

export interface DemoInterest {
  id: string;
  label: string;
  score: number;
  evidence: string;
  updated: string;
  parent: string;
  tone: "pink" | "teal" | "amber" | "violet";
}

export interface DemoCitation {
  id: string;
  title: string;
  chunk: number;
  time: string;
  concepts: string[];
  excerpt: string;
}

export interface DemoAnswer {
  id: string;
  question: string;
  shortLabel: string;
  answer: string;
  grounded: boolean;
  confidence: number;
  citations: DemoCitation[];
  ontologyPath: string[];
}

export interface DemoRecommendation {
  id: string;
  title: string;
  author: string;
  duration: string;
  freshness: string;
  score: number;
  source: string[];
  concepts: string[];
  path: string[];
  reason: string;
  mode: Array<"balanced" | "following" | "explore">;
  accent: string;
}

export const demoInterests: Record<DemoPeriod, DemoInterest[]> = {
  recent: [
    {
      id: "rag",
      label: "RAG",
      score: 0.82,
      evidence: "近 14 天观看 3 条、收藏 2 条",
      updated: "2 天前",
      parent: "大语言模型",
      tone: "pink",
    },
    {
      id: "agent",
      label: "AI Agent",
      score: 0.76,
      evidence: "LangGraph 系列连续观看 4 次",
      updated: "3 天前",
      parent: "人工智能",
      tone: "teal",
    },
    {
      id: "vector",
      label: "向量检索",
      score: 0.68,
      evidence: "知识库问答相关证据 5 条",
      updated: "5 天前",
      parent: "信息检索",
      tone: "violet",
    },
  ],
  longTerm: [
    {
      id: "python",
      label: "Python",
      score: 0.88,
      evidence: "跨收藏、课程与历史合并后 18 条证据",
      updated: "持续 11 个月",
      parent: "编程语言",
      tone: "teal",
    },
    {
      id: "ml",
      label: "机器学习",
      score: 0.71,
      evidence: "收藏 7 条、完成课程 1 门",
      updated: "持续 8 个月",
      parent: "人工智能",
      tone: "pink",
    },
    {
      id: "database",
      label: "数据库",
      score: 0.59,
      evidence: "教程与实战内容共 6 条",
      updated: "持续 6 个月",
      parent: "软件工程",
      tone: "amber",
    },
  ],
  historical: [
    {
      id: "docker",
      label: "Docker",
      score: 0.24,
      evidence: "旧收藏 4 条，已按时间衰减",
      updated: "最近证据 388 天前",
      parent: "DevOps",
      tone: "violet",
    },
    {
      id: "frontend",
      label: "前端工程",
      score: 0.18,
      evidence: "旧课程 2 条，未进入近期兴趣",
      updated: "最近证据 512 天前",
      parent: "软件工程",
      tone: "amber",
    },
  ],
};

const citations: Record<string, DemoCitation> = {
  retrieval: {
    id: "BVDEMO001#4",
    title: "从零实现 RAG 知识库",
    chunk: 4,
    time: "05:12–06:03",
    concepts: ["RAG", "向量检索"],
    excerpt: "先用混合检索扩大候选，再通过 reranker 过滤语义相近但证据不足的片段。",
  },
  grounding: {
    id: "BVDEMO007#9",
    title: "大模型幻觉治理实战",
    chunk: 9,
    time: "12:41–13:28",
    concepts: ["Grounded RAG", "引用验证"],
    excerpt: "答案中的事实必须能回指到具体 chunk；上下文不足时应拒答而不是补全常识。",
  },
  langgraph: {
    id: "BVDEMO012#6",
    title: "LangGraph 多智能体工作流",
    chunk: 6,
    time: "08:18–09:06",
    concepts: ["LangGraph", "AI Agent"],
    excerpt: "图状态使分支、重试和人工确认成为显式节点，适合长流程智能体编排。",
  },
  privacy: {
    id: "BVDEMO019#3",
    title: "个人知识库的隐私边界",
    chunk: 3,
    time: "03:20–04:11",
    concepts: ["隐私", "数据安全"],
    excerpt: "认证凭据应加密保存，画像证据必须可查看、暂停使用和按范围删除。",
  },
};

export const demoAnswers: DemoAnswer[] = [
  {
    id: "rag",
    shortLabel: "RAG 如何降低幻觉？",
    question: "这些收藏里有哪些降低 RAG 幻觉的方法？",
    answer:
      "收藏内容给出了三层控制：第一，原始查询与本体扩展结果经过带阈值的混合检索；第二，只对少量高分 chunk 做 rerank；第三，生成后验证每个事实是否被引用片段支持。证据不足时系统返回拒答，而不是用通用知识补全。",
    grounded: true,
    confidence: 0.94,
    citations: [citations.retrieval, citations.grounding],
    ontologyPath: ["RAG", "requires", "信息检索", "related", "引用验证"],
  },
  {
    id: "agent",
    shortLabel: "LangGraph 有什么不同？",
    question: "LangGraph 和普通顺序工作流有什么区别？",
    answer:
      "示例资料强调，LangGraph 将状态、条件分支、循环、失败重试和人工确认表示为图节点与边；普通顺序工作流更适合固定的线性步骤。对于多智能体协作，显式状态图更容易恢复、审计和解释。",
    grounded: true,
    confidence: 0.91,
    citations: [citations.langgraph],
    ontologyPath: ["人工智能", "narrower", "AI Agent", "narrower", "LangGraph"],
  },
  {
    id: "privacy",
    shortLabel: "项目如何保护隐私？",
    question: "这个项目如何处理 Cookie 和用户画像隐私？",
    answer:
      "资料中采用版本化 AES-GCM 加密 Cookie，并用短 session hash 关联日志。用户可以删除单条画像证据、暂停某个通道参与画像，或按 Cookie、画像、账号范围执行确认删除。",
    grounded: true,
    confidence: 0.96,
    citations: [citations.privacy],
    ontologyPath: ["数据安全", "related", "隐私控制"],
  },
];

export const demoRecommendations: DemoRecommendation[] = [
  {
    id: "rec-langgraph",
    title: "LangGraph 多智能体：从状态图到生产工作流",
    author: "AI 工程手记",
    duration: "18:42",
    freshness: "3 天前",
    score: 0.93,
    source: ["近期兴趣", "关注 UP"],
    concepts: ["LangGraph", "AI Agent"],
    path: ["AI Agent", "narrower", "LangGraph"],
    reason: "近期 AI Agent 兴趣与候选的 LangGraph 下位概念直接匹配。",
    mode: ["balanced", "following"],
    accent: "#ff5a9d",
  },
  {
    id: "rec-rag",
    title: "RAG 检索质量提升：阈值、融合与重排",
    author: "检索实验室",
    duration: "24:10",
    freshness: "6 天前",
    score: 0.9,
    source: ["知识库再发现", "近期兴趣"],
    concepts: ["RAG", "Reranker"],
    path: ["RAG", "related", "Reranker"],
    reason: "与你近期高强度 RAG 兴趣一致，并补充了相关的重排技术。",
    mode: ["balanced", "explore"],
    accent: "#2f7c78",
  },
  {
    id: "rec-python",
    title: "Python 异步任务队列的工程化设计",
    author: "代码之外",
    duration: "16:25",
    freshness: "12 天前",
    score: 0.84,
    source: ["长期兴趣", "多样性补位"],
    concepts: ["Python", "异步编程"],
    path: ["Python", "related", "异步编程"],
    reason: "来自长期稳定兴趣，用于保持推荐列表的主题多样性。",
    mode: ["balanced", "following"],
    accent: "#7566c5",
  },
  {
    id: "rec-vector",
    title: "向量数据库不只是 Top-K：索引与召回策略",
    author: "数据基础设施",
    duration: "21:07",
    freshness: "8 天前",
    score: 0.81,
    source: ["关联概念", "探索召回"],
    concepts: ["向量数据库", "信息检索"],
    path: ["RAG", "requires", "向量数据库"],
    reason: "从 RAG 的前置知识关系扩展而来，属于受控探索内容。",
    mode: ["balanced", "explore"],
    accent: "#d48a36",
  },
];

export const demoFolders = [
  { name: "AI 工程实践", count: 18, active: true },
  { name: "知识库与检索", count: 12, active: true },
  { name: "Python 长期学习", count: 9, active: false },
  { name: "稍后看 · 技术", count: 7, active: false },
];

export const demoMetrics = [
  { value: "233", label: "Active concepts" },
  { value: "2,199", label: "RDF triples" },
  { value: "98.0%", label: "RAG Recall@5" },
  { value: "2", label: "Mandatory LLM gates" },
];

export function resolveDemoAnswer(question: string): DemoAnswer | null {
  const normalized = question.toLocaleLowerCase();
  if (["rag", "幻觉", "检索", "引用"].some((token) => normalized.includes(token))) {
    return demoAnswers[0];
  }
  if (["langgraph", "agent", "智能体", "工作流"].some((token) => normalized.includes(token))) {
    return demoAnswers[1];
  }
  if (["cookie", "隐私", "安全", "删除"].some((token) => normalized.includes(token))) {
    return demoAnswers[2];
  }
  return null;
}
