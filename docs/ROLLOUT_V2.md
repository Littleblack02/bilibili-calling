# V2 灰度发布与回滚

## 前置门禁

每次发布前运行：

```bash
python scripts/check_release_gates.py
```

脚本要求 ontology/SHACL、实体链接、RAG、推荐、迁移、临时回填和本地排序性能报告全部存在且通过；任一失败时返回非零状态，部署流程必须保持所有 V2 flags 关闭，或立即把 `V2_ROLLOUT_PERCENTAGE` 调回 `0`。

## 灰度顺序

1. 打开所需的独立功能开关，但保持 `V2_ROLLOUT_PERCENTAGE=0`。
2. 把测试会话的 salted 16 字符 rollout hash 写入 `V2_TEST_SESSION_HASHES`；不得写原始 session ID。
3. 测试账号稳定后设为 `10`，观察至少一个完整同步/推荐周期。
4. 门禁仍通过且错误率、429、认证失败、RAG 无结果率、p95 延迟无回归后设为 `50`。
5. 再次检查同一组指标和真实反馈后设为 `100`。

会话桶由固定 SHA-256 派生，因此重启后不会漂移。推荐批次保存该会话的实际 flags，便于归因。

## 回滚

- 单功能异常：关闭对应 `*_ENABLED`。
- 系统性异常：立即将 `V2_ROLLOUT_PERCENTAGE=0`。
- 不执行破坏性数据库 downgrade；旧代码通过兼容 JSON/nullable 字段读取，数据库只在恢复迁移前备份时回退。
- 关闭 flag 后重新运行 smoke test，并保留失败报告与 request_id/batch_id 供排查。
