# Spec0010：可调用的一次A2查询与证据契约

日期：2026-10-10。上位目标见[ADR0004](../decisions/0004-knowledge-agent-goal-and-boundaries.md)。用户“可以继续”后本切片进入机制讲解与TDD实施；仍不发真实请求或安装Agent依赖。重点是补上固定实验与知识库Agent调用之间的缺口，实施结果按实际记录。

## 1. 当前数据流与问题

`hybrid_probe.run`→load_corpus/load_queries/load_index→核固定query_hash与原A1结果→vector_index.search→keyword_index.search→rank_fusion.fuse→pack_evidence→检索后加载labels/evaluate。现成范围、分词、召回、融合、完整预算与源位置检查都有实现。

新查询会因固定任务/向量缓存身份无法直接进入现入口。知识库Agent需要独立的一次查询调用，不能每次先重跑四题实验/业务评分，也不能让检索过程读取金标签。先搜后写已检查上述低层函数与现测试；复用这些实现，不重写BM25/RRF或升级依赖。

## 2. 切片目标

在既有冻结语料/索引上接收一条新查询，依照显式范围及返回预算返回结构化原文证据；查询向量通过一个明确注入的适配入口提供，首轮用缓存真实向量与明确标记的模拟服务做离线验证。任意新问题真实Embedding接入是下一切片，不把模拟向量当语义质量或真实服务证明。

本切片不实现知识库Agent循环/Self-RAG语义评分、重排、数据库迁移、索引更新、HTTP/MCP/Dashboard或测试Agent改动。现有实验公开入口/签名与历史结果保持；本地离线库接口不是外部API服务。

## 3. 调用契约

新入口`retrieve_once(request, resources, embed_query)`：

- request：query非空文本、scope_document_ids（None表示资源已授权全集）、exclude_document_ids、candidate_k、max_context_chars。query保存原文本；输入必须真实类型，bool不能冒充整数，重复/未知文档ID拒绝。query UTF-8不超过既有接口允许的3072字节。
- resources：由`load_snapshot(config, authorized_document_ids, tokenizer_cache_dir)`构造的A2Snapshot，配置只接收dataset/corpus_run/vector_run/endpoint/model/dimensions/BM25参数/backend/tokenizer_policy/rrf_k，来源范围是显式授权文档列表。参数沿已测A2：candidate_k≤20、rrf_k=60、max_context_chars≤8000、jieba/BM25S固定版本与当前Lucene参数；值经资源配置提供，不隐藏Default替代实际输入。每次查询前重新核源与向量快照身份，拒绝源变化；本片为串行本机兼容层，不声明并发安全或性能优化。
- embed_query：受控回调`embed_query(query, embedding_identity)`，返回query_sha256/embedding_identity/vector与source_kind（cached/simulated/service/unknown）及可选usage。入口在调用前校验输入/范围，输出必须匹配查询hash、原索引endpoint/model/dimensions/表示策略且向量有限/非零；异常向调用者传播，不能自动用旧问题向量或静默只跑BM25。source_kind只是提供方声明，真实请求证据由适配层另外记录；callback次数不是HTTP次数。
- result：query与实际scope/exclude、index/corpus身份、dense/sparse/hybrid candidates诊断、selected、budget_excluded、context_text/字符预算、状态、answerability=unknown以及最小阶段追踪。原Evidence字段/正文/版本/位置不改，查询成功不自动代表充分回答。

资源可读集合由调用方服务层准备并在入口校验，不能把request声明当权限；超出资源范围拒绝且不调用Embedding。None不代表任意路径/整个机器。局部范围仍按A2在允许集合内计算BM25统计，不能悄悄换成全库统计。

## 4. 最小数据流与路径

输入/资源/范围检查→一次query向量适配及身份校验→范围内Dense→范围内BM25→RRF→完整证据组装→返回结果。读取/分词/索引/向量错误均有阶段及非敏感错误码，错误不是empty；原文/Key不进诊断。

空允许候选返回empty；候选全部放不下返回no_evidence_fits并列预算排除；否则retrieved。完整用例/原文不被截断。任何预算/状态都不推导整个知识库不存在答案。此切片无重试、无隐式网络fallback，模型请求由注入入口边界控制。

入口置于`naiyue_rag/retrieval.py`，既有实验资源兼容置于`naiyue_rag/a2_snapshot.py`，避免Agent工具直接依赖实验CLI。首切片兼容层可以调用已测低层函数，需记录其实验资产依赖；尚不是独立构建/全库产品。后续移除实验依赖按Spec逐项提取并保持原入口回归，不本轮迁移整个目录。

新增公共错误`RetrievalError(stage, code)`，调用失败记录安全阶段/错误码，不输出原异常正文。request字段明确且不接收任意额外参数；返回对象深拷贝，外部改结果不能污染后续查询。语料已排除文档可继续出现在exclude列表中，但不能作为可读scope；授权范围内排除全部文档是合法empty路径。

## 5. 影响文件（实际实施见第8节）

- `naiyue_rag/__init__.py`：只导出真实入口，不生成其他空模块。
- `naiyue_rag/retrieval.py`：请求/返回/错误与最小追踪编排。
- `naiyue_rag/a2_snapshot.py`：已核验冻结资源与既有低层实现兼容，注入查询向量入口。
- `tests/test_retrieval_once.py`：正常/异常/范围/预算/新查询回归。
- `tests/test_a2_snapshot.py`：旧查询结果一致性与资源/身份验证。
- 新实现后的README/handoff/学习入口同步实际函数和命令。原experiments函数/参数/锁与旧tests不因新切片顺手改动。

## 6. TDD与验收

先写入口不存在的预期红灯，再最小实现，记录真实输出；准备阶段没有填完成记录，随后实际红灯/绿灯见第8节。

1. 新查询不在原tasks/query_hash列表仍能通过明确适配取得向量并进入A2，两路及融合实际被调用；模拟调用明确标为测试。
2. 无效query、未知/重复/越权scope/exclude、向量identity/hash/维度/NaN/零向量错误拒绝；Embedding spy证明范围拒绝发生在任何模型调用前。
3. 同查询、真实旧向量、原范围/参数下，原四题candidate/selected/预算内容与A2逐字段相同；计时单列，不能放宽排序/正文断言。
4. 完整用例/来源/预算排除、empty/no_evidence_fits、单文档限制及排除当前任务材料有回归；Embedding/IO失败不是空成功。
5. 测试不传gold标签给查询入口；评价在得到结果后执行。新模块不读tasks金标签、别仓.env或自动发送网络请求。
6. 全量旧测试通过、源码每文件≤500行、无新依赖与运行配置变更；无应用构建时写不适用，compileall仅语法。

实施验证命令：

```sh
.venv/bin/python -m pytest -q tests/test_retrieval_once.py tests/test_a2_snapshot.py
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q naiyue_rag experiments tests
git diff --check
```

准备阶段上述新测试/源码路径尚不存在，随后执行结果见第8节。离线成功后，真实新查询Embedding须使用本项目专用凭证/显式端点/请求数/截止及公开或合成输入，另记真实调用，不能用本切片假服务冒充。

## 7. 教学与停止边界

第一机制：同一查询的两路候选怎样按RRF排序，以及为什么进入候选仍可能没返回；用现有Q01 E01 dense19/sparse4→RRF9作具体例子。开始实现前讲清request→向量→两个排序→证据返回，再写红灯。实现后逐行读新入口及fuse/pack_evidence，安排本人手算或修改范围练习，未练习前不登记独立实现。

连续三次同类失败按AGENTS停止报告。可停止使用新入口，旧实验/索引/结果保留；不自动删除/回滚。真实材料验证、吞吐、更新、最终后端和上下文隔离不在本切片验收，已有合成成绩不作生产承诺。

## 8. 2026-10-10实际实施与验证

用户“可以继续”后，已按明确输入输出机制开展TDD：新测试46项因naiyue_rag缺失报ModuleNotFoundError（预期红灯），随后3个实质源码与2个新测试文件完成；首次实现验收46 passed in8.25s，无修改/放宽测试。错误类/范围/快照/查询hash与模型身份/有限非零向量/安全日志/完整证据/深拷贝返回有实际路径。

实际新入口：`naiyue_rag.load_snapshot`→A2Snapshot构造并核源/向量/授权/分词配置；`retrieve_once`→请求与实际范围校验→源/向量快照再核→一次注入Embedding适配及身份校验→旧dense search→范围内BM25 build/search→旧fuse→旧pack_evidence→完整结果与7阶段trace。不加载tasks或gold、不自动读Key/联网，不隐式单路降级。诊断adapter_calls=1不是HTTP次数，usage可为unknown。

当前资源配置明确来源于调用方，授权范围未知/越界在回调前拒绝；源或向量资产变化也在回调前拒绝。每次再核快照有IO开销，当前只支持本机串行实验资产兼容，不作生产鉴权/并发/吞吐声明。完整实际缓存四题的dense/sparse/hybrid候选、selected、budget_excluded、context_text/预算/status/answerability及union均逐字段精确匹配旧A2。

实际命令：

```text
.venv/bin/python -m pytest -q tests/test_retrieval_once.py tests/test_a2_snapshot.py
46 passed in 8.25s
.venv/bin/python -m pytest -q tests
456 passed in 48.26s
.venv/bin/python -m compileall -q naiyue_rag experiments tests
exit 0，无输出（仅语法）
.venv/bin/python -m pip check
No broken requirements found.
git diff --check
exit 0，无输出
```

3源码为5/127/103行，均≤500；55份旧experiments/tests/锁文件SHA不变，记录data/research/spec0010-evidence/unchanged-before.json与final-checks.json。无新依赖、.env/运行配置/其他仓库变动、真实新模型请求、Agent运行或发布。应用构建不适用；工程测试与旧缓存一致性不证明新问题Embedding质量、四场景业务质量或上下文收益。

L1文件存在；L2实质请求/源/向量/权限范围/错误/预算及现成算法接法；L3包导出→真实函数调用→完整A2四题回归。数据流已简述，逐行代码课堂、用户复述/复写与独立实现尚未完成。下一步先讲retrieve_once主链路并做范围/证据小练习，再制定真实新查询向量适配切片；Agent底座建议另见[选型记录](../research/knowledge-agent-runtime-options.md)，未因本片安装Agent框架。
