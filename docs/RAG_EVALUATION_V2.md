# Grounded RAG 评测 V2

## 范围

评测集包含 150 个确定性合成/编辑问题：126 个可回答问题和 24 个“主题相关但所问事实不存在”的无答案问题。题型覆盖直接问法、同义词、跨视频综合、否定问题、时间码和无答案拒答。126 个金标 chunk 均带 `bvid + chunk_index + start_time + end_time + concept_ids`。

运行时使用固定的本地词法得分索引补足到 10000 个 chunk，再调用生产 `GroundedRetriever` 的阈值、ontology 扩展、RRF 和 reranker。回答评测使用确定性抽取路径，因此可以验证引用和拒答合同，不依赖远程 LLM。

## 门槛

- Retrieval Recall@5 ≥ 0.85
- MRR@10 ≥ 0.75
- 引用正确率 ≥ 0.95
- Groundedness ≥ 0.90
- 无答案正确拒答率 ≥ 0.90
- 事实性幻觉率 ≤ 0.05
- 10000 chunk 本地检索 p95 ≤ 800ms

完整结果保存在 `reports/evaluation/rag.json`。脚本在任何门槛失败时返回非零状态。

## 结论边界

这套数据证明本地检索、证据选择、引用验证和拒答机制的工程回归，不代表真实收藏库分布，也不代表远程生成模型的回答质量。真实质量仍需用经人工审阅、脱敏的真实收藏问答集重复同一协议。

```bash
python scripts/generate_rag_eval.py
python scripts/validate_evaluation_data.py
python scripts/evaluate_rag.py
```
