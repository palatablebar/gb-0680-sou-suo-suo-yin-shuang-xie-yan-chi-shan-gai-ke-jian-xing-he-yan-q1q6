# 深度登记 搜索索引双写延迟与删改可见性核验

规模：中型。使用者：搜索数据同步值班工程师。核心规则：按源版本重建目标可见状态，删除墓碑拦截迟到旧写入；延迟与缺失分开定责。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 双端采信 | 查看并运行双端采信 | `/api/streams` | `app/modules/m1_streams/rules.py` | `tests/test_m1.py` |
| M2 字段契约 | 查看并运行字段契约 | `/api/schema` | `app/modules/m2_schema/rules.py` | `tests/test_m2.py` |
| M3 版本裁决 | 查看并运行版本裁决 | `/api/versions` | `app/modules/m3_versions/rules.py` | `tests/test_m3.py` |
| M4 可见性重建 | 查看并运行可见性重建 | `/api/visibility` | `app/modules/m4_visibility/rules.py` | `tests/test_m4.py` |
| M5 延迟闸门 | 查看并运行延迟闸门 | `/api/latency` | `app/modules/m5_latency/rules.py` | `tests/test_m5.py` |
| M6 双写对账 | 查看并运行双写对账 | `/api/parity` | `app/modules/m6_parity/rules.py` | `tests/test_m6.py` |
| M7 回补归档 | 查看并运行回补归档 | `/api/backfills` | `app/modules/m7_backfills/rules.py` | `tests/test_m7.py` |
| M8 合规下架裁决 | 形成下架唯一结论并导出凭据 | `/api/takedowns` | `app/modules/m8_takedowns/rules.py` | `tests/test_m8.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码 | 默认解码失败 | 回退GB18030 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_legacy_encoding_real_sample` |
| TRAP-02 | BOM | 首列名多字符 | utf-8-sig | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_bom_real_sample` |
| TRAP-03 | 带引号换行 | 拆成两条 | csv逻辑行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_quoted_newline_is_one_record` |
| TRAP-05 | 列数不匹配 | 静默错列 | 隔离原行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_bad_columns_real_sample` |
| TRAP-08 | 前导零ID | 编码变形 | 全程字符串 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_identifier_preserved_real_sample` |
| TRAP-14 | 重复键冲突 | 后写覆盖 | 保留首条并隔离冲突行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_duplicate_conflict_real_sample` |
| TRAP-18 | 空态三态 | 一律成功 | 分别错误码 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_three_empty_states` |
| TRAP-26 | 旧版本提交 | 覆盖新结果 | 版本条件更新 | `app/store.py` | `tests/test_e2e.py::test_stale_review_409` |
| TRAP-06 | 全角版本 | 解析失败 | Decimal归一 | `app/values.py` | `tests/test_m2.py::test_fullwidth_version` |
| TRAP-07 | 缺版本 | 当零处理 | 空值隔离 | `app/values.py` | `tests/test_m2.py::test_real_sentinel_isolated` |
| TRAP-09 | 超大版本 | JSON精度损失 | 文本序列化 | `app/values.py` | `tests/test_m2.py::test_large_version_precise` |
| TRAP-13 | 删除后迟到旧写 | 文档复活 | 最大版本墓碑 | `app/modules/m3_versions/rules.py` | `tests/test_m3.py::test_tombstone_beats_late_old_write` |
| TRAP-23 | 延迟阈值边界 | 多判延迟 | 等于阈值通过 | `app/modules/m5_latency/rules.py` | `tests/test_m5.py::test_threshold_equal_pass` |
| TRAP-30 | 等全部回执再遮蔽 | 正文持续暴露错过15分钟 | 先遮蔽，回执不阻断结论 | `app/modules/m8_takedowns/rules.py` | `tests/test_m8.py::test_conclusion_does_not_wait_for_all_receipts` |
| TRAP-31 | 清除全部内容留证 | 审计无法证明处理范围 | 只落遮蔽标记与正文sha256摘要，不落正文 | `app/modules/m8_takedowns/rules.py` | `tests/test_m8.py::test_body_never_stored_only_hash_and_redaction` |
| TRAP-32 | 历史曾暴露即永久暴露 | 已遮蔽入口仍判失败 | 以最新探针定当前状态，历史暴露留痕ever_exposed | `app/modules/m8_takedowns/rules.py` | `tests/test_m8.py` |
| TRAP-33 | 重试生成新结论/凭据 | 结论与凭据漂移 | 终局不可变，同工单确定性ID与credential_id | `app/takedown_store.py` | `tests/test_m8.py::test_settle_idempotent_no_new_conclusion_or_credential` |
| TRAP-34 | 迟到旧写复活正文 | 下架内容回潮 | 版本不高于墓碑即BLOCKED，更高版本ESCALATE不自动复活 | `app/modules/m8_takedowns/rules.py` | `tests/test_m8.py::test_late_old_write_blocked_by_tombstone_and_never_revives` |
| TRAP-35 | 截止后遮蔽仍判成功 | 超时限工单被放行 | 截止时刻仍有暴露/未探测/未遮蔽即超时，不发凭据 | `app/modules/m8_takedowns/rules.py` | `tests/test_m8.py::test_redaction_after_cutoff_is_breach` |

## 对账规则

输入原始逻辑行=最终采纳来源行+隔离来源行+重复行+空白行+分段表头。派生记录用_sources保存完整来源，因此分组不丢行。业务预期合计与上游申报合计之差等于逐行差异之和。结果按输入摘要、规则版本及参数产生唯一批次，事务写入；同源重跑只复用已有批次。

## 已知不覆盖

4MB以上文件需预先按业务键分批；不模拟生产支付与外部回调。人工复核只变更批次状态，不改写原始记录。

## M8 合规下架裁决口径

工单何时形成唯一完成结论：对范围文档×检索入口的每个单元，以**最新探针**判定当前是否仍返回正文；当全部单元在下发后 `deadline_seconds`（默认900秒）内首次达到无正文，才形成唯一结论“已下架”并签发一份凭据。回执只作留痕，不作为完成前置；截止时刻仍有单元暴露、未探测或未在时限内遮蔽，结论为“已超时”且不发凭据；时限内证据未齐为“处置中”。

裁决不变量：①正文不落库，仅保留 `body_sha256` 摘要、墓碑版本与遮蔽标记，可定位原记录与下架范围；②迟到写入版本不高于墓碑即 `BLOCKED`，更高版本 `ESCALATE` 转人工，均不自动复活正文；③`ticket_id` 由工单范围与时限确定性派生，`credential_id` 由终局判定依据派生，重试同工单不新增结论或凭据，终局记录对迟到证据不可变；④工作台页面与导出凭据读取同一份持久判定。
