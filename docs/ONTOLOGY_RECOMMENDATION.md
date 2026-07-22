# 本体、时序画像与推荐集成

## 本体在项目中实际产生的作用

本体不是一份只供展示的词表，而是接入了四条运行链路：

1. **内容入库**：标题、字幕、摘要和提纲通过确定性实体链接映射到 SKOS 概念，结果写入 `video_concepts`，Chroma 文档也携带概念 ID、标签和本体版本。
2. **知识问答**：查询先解析别名，再沿 `broader`、`related`、`requires` 做有界扩展；多个检索查询用 Reciprocal Rank Fusion 合并。比如“知识库问答”能归一到 RAG，并召回“检索增强生成”。
3. **用户画像**：每条收藏、观看、稍后看、课程等行为按来源语义和发生时间衰减，再聚合为规范概念亲和度、近期概念亲和度和多个兴趣簇。
4. **推荐与反馈**：排序计算本体匹配、多兴趣簇匹配和可审计的关系路径；屏蔽主题只向其 SKOS 子概念传播，不会反向误伤父概念或兄弟概念。

本体文件位于 `ontology/bilibili.ttl`，约束位于 `ontology/shapes.ttl`。运行时实现位于 `app/services/ontology/`。当前版本是 `bili-ontology-1.0.0`。

## 数据流

```text
B站只读通道 ──> UserContentSignal ──> 来源权重 × 时间衰减
                                           │
视频正文/标题 ──> SKOS 实体链接 ────────────┤
                                           v
                   概念亲和度 + 近期亲和度 + 多兴趣簇
                                           │
     多路候选（搜索/关注动态/热榜/追更/知识库）
                                           v
    过滤 -> 可解释特征排序 -> MMR 多样性 -> 可选 LLM 辅助
                                           │
                                           v
                         推荐批次快照 + 行为反馈
```

## 旧收藏和旧追番为什么不会再长期主导

使用指数半衰期，并为持久行为保留很小的下限。时间未知的数据使用保守先验，绝不当作刚发生。

| 信号 | 基础权重 | 半衰期 | 下限 | 语义 |
|---|---:|---:|---:|---|
| 观看历史 | 1.00 | 10 天 | 0 | 已消费 |
| 直播历史 | 0.85 | 7 天 | 0 | 已消费 |
| 稍后再看 | 0.82 | 30 天 | 0.05 | 明确意图 |
| 收藏 | 0.90 | 150 天 | 0.10 | 持久兴趣 |
| 追番 | 0.78 | 120 天 | 0.08 | 持久兴趣 |
| 影视收藏 | 0.68 | 180 天 | 0.08 | 持久兴趣 |
| 课程 | 0.88 | 240 天 | 0.12 | 学习意图 |
| 关注动态曝光 | 0.10 | 2 天 | 0 | 只作曝光/候选，不作正偏好 |

公式：`effective_weight = base × (floor + (1-floor) × 2^(-age/half_life)) × strength`。

## 推荐排序

默认权重（总和为 1）：

| 特征 | 权重 |
|---|---:|
| 关键词内容匹配 | 0.18 |
| 本体语义匹配 | 0.17 |
| 近期兴趣 | 0.16 |
| 多兴趣簇匹配 | 0.10 |
| UP 亲和度 | 0.10 |
| 视频新鲜度 | 0.09 |
| 播放速度质量 | 0.08 |
| 探索 | 0.07 |
| 当前意图 | 0.05 |

排序结果包含 `feature_scores`、`matched_concepts`、`ontology_path` 和 `matched_interest_cluster`，会写入推荐批次快照。旧版环境变量只配置七个特征时会自动与新默认值合并并归一化，不会因缺字段中断。

随后使用 MMR、每 UP 上限、召回源覆盖和视频时长覆盖做多样性重排。LLM 默认关闭；打开后也只作为 Top-N 辅助分，统一或无效的 LLM 分数不会改变规则顺序。

## 算法依据与工程取舍

- [MIND, KDD 2019](https://arxiv.org/abs/1904.08030) 和 [ComiRec, KDD 2020](https://arxiv.org/abs/2005.09347) 支持“一个用户有多个兴趣表示”，对应这里的多兴趣簇与候选对簇的最大匹配。
- [SASRec, ICDM 2018](https://arxiv.org/abs/1808.09781)、[Déjà vu, WWW 2020](https://arxiv.org/abs/2002.00741) 和 [MTAM, CIKM 2020](https://arxiv.org/abs/2005.08598) 支持序列近期意图、时间变化和长短期结合，对应来源相关半衰期与近期概念亲和度。
- [X Algorithm](https://github.com/xai-org/x-algorithm) 的候选源分层、过滤、多行为加权评分和多样性思想，对应这里的关注网络候选、非关注候选、统一过滤、特征混合和 MMR。

当前实现是这些机制的**可解释、无需训练数据的工程化桥接**，没有声称复现论文中的神经网络训练或 X 的生产模型。

## B站画像通道覆盖

已接入的登录态只读信号包括：收藏视频、追番、影视收藏、视频历史、稍后再看、普通/特别/悄悄关注、订阅标签、收藏合集/话题/专栏/课程/笔记、已购课程、粉丝勋章、追漫、直播历史和关注动态。

没有稳定的账号全量“点赞历史”和“投币历史”读取接口，也无法通过有限历史窗口还原完整生命周期完播序列。系统会在 `GET /recommendations/profile-sources/{session_id}` 中明确报告这些不可用项，不伪造数据。相关端点属于 B站非官方公开文档范围，可能变更；每个通道都有超时和失败隔离。

## API 与运维

- `GET /ontology/health`：SHACL 校验、本体版本和计数。
- `GET /ontology/concepts`：浏览规范概念。
- `POST /ontology/resolve`：实体链接、关系扩展和查询变体。
- `GET /ontology/videos/{bvid}`：查看视频概念证据。
- `GET /recommendations/profile-sources/{session_id}`：画像通道能力、实际采集数和新鲜度。
- `GET /recommendations/preferences/{session_id}`：兴趣标签、本体版本、多兴趣簇和来源新鲜度。

历史视频回填：

```bash
python scripts/backfill_ontology.py --batch-size 100
```

验证：

```bash
python -m compileall -q app scripts
python -m pytest -q
```

## 扩充本体

新增概念时优先使用 `skos:prefLabel`、`skos:altLabel`、`skos:broader` 和 `skos:related`；技能前置依赖使用 `bili:requires`。提交前必须通过 `/ontology/health` 或测试中的 SHACL 校验。避免把容易误匹配的短英文串作为别名；两到三个字符的 ASCII 别名会使用单词边界匹配。

本体数据模型遵循 [W3C SKOS](https://www.w3.org/TR/skos-reference/)；结构约束遵循 [W3C SHACL](https://www.w3.org/TR/shacl/)；RDF 处理使用 [RDFLib](https://rdflib.readthedocs.io/en/stable/apidocs/rdflib.graph/)。
