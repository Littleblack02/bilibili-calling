# 推荐离线评测 V2

## 评测协议

- 截止时间固定为 `2026-06-01T00:00:00Z`，截止点前事件构建画像，之后的正向行为只作为标签。
- 候选目录固定且所有内容均在截止点前发布；评估器会拒绝含未来内容的目录。
- 固定随机种子为 `20260721`，候选集 SHA-256、数据集 SHA-256 和生成参数记录在 `evaluation/recommendation.lock.json`。
- 主指标为 Recall@20、NDCG@10、MRR@10、HitRate@10、Catalog Coverage、Novelty、ILD 和相关主题覆盖率。
- 按活跃度、画像新鲜度和目标内容领域分桶；均值同时输出 95% bootstrap 置信区间。
- 消融项包括：无时间衰减、无本体、无多兴趣簇、无 Hydration、无关注动态，以及相关性/多样性权重组合。

## 数据范围和结论边界

当前数据是 84 个去标识化合成会话、1008 个候选和 1328 个事件组成的确定性编辑回归集。它专门覆盖旧收藏、近期兴趣迁移、别名、第二兴趣、内容质量和创作者信号等情形，用于发现时间泄漏、功能退化和权重冲突。

该结果只能说明 V2 在上述离线工程场景达到门槛，不能说明真实 B 站用户的线上提升。线上结论仍需经过真实匿名日志的同协议回放和 A/B 测试。

## 运行

```bash
python scripts/generate_recommendation_eval.py
python scripts/validate_evaluation_data.py
python scripts/evaluate_recommendation.py
```

JSON 完整结果位于 `reports/evaluation/recommendation.json`，同目录 Markdown 文件提供摘要。评估命令在任一硬门槛失败时返回非零退出码，适合纳入 CI。
