# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## M8 合规下架裁决

- `GET/POST /api/takedowns`：GET用仓内 `sample_data/takedown.json`，POST接收工单对象，仅计算不落库，返回每个“文档×入口”单元的探针裁决、迟到旧写处置与结论。
- `GET/POST /api/takedowns/settle`：形成并持久化唯一结论；POST无正文时按仓内样例裁决。终局（已下架/已超时）后重试返回原记录且 `new_conclusion=false`，不新增结论或凭据。
- `GET /api/takedowns/history`：已形成结论的工单清单。
- `GET /api/takedowns/<ticket_id>`：定位原记录、范围摘要与单元裁决。
- `GET /api/takedowns/<ticket_id>/credential`：仅“已下架”工单可导出凭据CSV（含单元、被拦截/升级旧写、凭据封条）；其余状态返回409。凭据与工作台共用同一份持久判定，重复导出内容一致。
- 页面入口 `/takedowns`。工单字段：`ticket_no,issued_at,deadline_seconds,as_of,entrances,documents[{doc_id,tombstone_version,body_sha256}],probes[{doc_id,entrance,observed_at,returns_body}],receipts[{doc_id,entrance}],late_writes[{doc_id,version,arrived_at,entrance?}]`。
