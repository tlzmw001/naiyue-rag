# Spec0050：优化分片7／移除路径、既有消费者与增量闭环验收

日期：2026-10-26。状态：已实现/接线/本地验收；提交前限额修复后最终完整2235项回归通过。

## 1. 范围与目标

同步适配使用同一构建链的remove_document；保持显式移除、源文件/历史版本保留、不级联其他文档、后续主动run可纳回原文档的既有语义。D3采用快照/汇总合同后，移除保留集可复用已有成对编码并完整建新版本；这属于文档级复用同一机制，不扩展物理擦除或GC。

本片还验证查询、补读、管理、CLI在v1/v2及新旧活动版本上的实质接线；用相同最终资料集合的全量重算作基线。禁止只比较单个API成功或把新旧bundle_id不同当结果错误。

## 2. 移除数据流与分支

remove_document(document_id,expected_revision=...)签名保持：选固定base→原profile/源限额/双索引审计→未命中沿原no-op→命中则排除文档→复用保留集chunks/records→完整重算关系与诊断→V2完整双索引→revision激活→RemovalReceipt+summary。

命中移除没有需要编码的文档，本次BatchProcessor/Dense/Sparse调用0，job_report=null，summary(encoded=0,reused=保留片段数)。移除最后一文档形成合法活动空库，summary三计数0；未命中和未激活维持原状态，不生成候选。

profile不匹配仍报ingestion_profile_mismatch，不借移除隐式迁移模型/策略。原文件不可读不阻止从已保存快照移除；保留现有构造路径边界，不顺便改变Loader初始化合同。源文件仍在时后续显式run将其视作新增并编码。

## 3. 增量与全量对照口径

在两个隔离存储根构造相同最终文档集合，一组按新增/修改/保留路径增量形成，一组force全量编码。固定策略、模型/表示、tokenizer、BM25配置、查询、scope、top_k和预算。确定性Embedding由输入文本产生相同向量，不能依赖调用批次/位置生成不同值。

比较documents、chunks正文/span/元数据、relations、编码输入/向量/词项、两路结果及最终证据的来源/正文；本次报告、origin、job_id、耗时、bundle/index/version_id因构建历史不同允许不同，分别记录，不做全JSON字节相等伪断言。

BM25对照词表/行映射/统计母体和同查询分数；浮点容差依据现有数值存储合同显式确定，不能放宽到掩盖错误。新旧版本的旧文档片段不得混入当前集合。若ANN并列分数顺序无稳定合同，比较可确定的分数/集合并单列并列组，不能假定任意同分顺序固定。

## 4. 失败与消费者矩阵

覆盖编码/Dense后Sparse/资料包/Chroma/BM25失败、坏基线、revision竞争、提交不确定、最终回执失败；按实际已知状态断言旧活动或胜者活动，未知时回读，不一律断言回滚。并发测试用事件/Barrier，不用紧sleep。

新进程分别消费旧v1、新v2及旧历史版本：DocumentManager列表详情、QueryPipeline固定准备、Dense/Sparse、global/scope、RRF、关闭重排、既有重排替身、ResponseBuilder、KnowledgeReader读片段/行/关系、独立CLI。模型服务由MockTransport、重排由既有确定性替身，真实模型请求0；不重复下载权重/调用付费模型证明接线。

失败不隐式全量重跑，不删除半成品或历史包，不回滚其他写者，不读取其他项目.env。所有测试对当前作用域严格，不能修改公共测试helpers放宽真实性断言。

## 5. 影响文件、验证与收尾

ingestion/pipeline.py、core/ingestion_types.py及真实发现遗漏的v2消费者；tests/test_document_removal.py、test_document_removal_wiring.py、test_incremental_ingestion.py、新增test_incremental_acceptance.py、既有query/evidence/core-app回归。只修本功能接线缺口，不顺便重构或调参。

计划命令：

```sh
.venv/bin/python -m pytest -q tests/test_incremental_acceptance.py tests/test_incremental_ingestion.py tests/test_document_removal.py tests/test_document_removal_wiring.py tests/test_query_preparation_wiring.py tests/test_knowledge_reader.py tests/test_core_app.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

L1检查全部新增合同/实现/测试；L2检查无占位及严格来源/账务；L3给出真实run/remove→保存→新进程查询/补读/CLI证据。打包构建不适用，compileall不冒充运行验证。完整全量必须实际运行，不能把历史2151与新增数相加当结果。

更新README、handoff、project-plan、future-work与spec索引的当前状态；历史证据保留，功能实现/本机验证/真实资料质量/本人学习分开。记录实际命令/输出、已知限制及唯一下一步；不自动进入Agent/MCP或发起真实资料/模型实验。七片完成后由用户选择继续6.5练习或另行验收真实资料，不自行扩大范围。

## 2026-10-26实施记录

新增test_incremental_acceptance.py：移除禁止重准备/重编码、两种切分策略下的原生增量/全量对照，先3 failed in6.65s，均复现移除仍重编码保留集。移除入口沿已验收构建函数传入固定基线和空编码文档集合；原移除/错误测试的模型调用和本次报告断言按已确认零编码合同同步，并保留失败、冲突、提交不确定和来源断言。

首次对照发现新验收测试的模拟Embedding把倒序响应按顺序配到输入，导致同文跨批次向量不同。核验既有payload明确返回倒序index后，新测试按响应index取对应输入；未更改既有公共helper或一致性/浮点断言。移除中断传播测试原注入编码器，因零编码已不执行，改为注入仍执行的向量索引构建；继续严格断言KeyboardInterrupt传播和旧活动版本保持。修正后原生对照及移除回归59 passed in55.68s。真实网络连接在子进程显式禁止，SDK走MockTransport，索引使用真实本机Chroma/BM25。

本Spec计划的7个相关文件扩展回归：96 passed in92.60s（0:01:32）。进一步对原生BM25词表、行映射、avgdl、统计母体、参数及全部词项权重作语义对照，不以内部列号/文件字节偶然一致为前提；完整集合/元数据精确相等，原生float64权重采用既有审计容差rel=1e-12、abs=1e-15，两路检索分数采用既有rel/abs=1e-6。补齐后新增闭环3 passed in21.52s，两种切分策略均通过。

最终验证命令与结果：

```sh
.venv/bin/python -m pytest -q tests --tb=short
# 2230 passed in 469.24s (0:07:49)
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
git diff --cached --check
# exit 0
```

L1：7份Spec、6个新源码模块及冻结旧包样本已存在，Markdown代码围栏配对；L2：新增源码非占位，全部修改Python文件均不超过500行，严格来源/配对/账务及错误边界通过运行验证；L3：正式run/remove→V2自包含快照→真实本机Chroma/BM25→revision激活→新进程管理/查询/补读与既有CLI消费者已验证。仓库未设独立打包构建命令，构建不适用，compileall只作语法证据。

全部7片收口，无新增未决设计。真实配置、依赖和用户知识库未改，未提交/push；本地测试使用合成材料及SDK MockTransport，不声明真实业务质量、模型服务账单或大库性能收益。完整资料包仍核验M2/输入、全量关系及新双索引；旧程序不能读V2格式。README、计划、待办、交接与Spec索引已同步。下一步按原路线回到阶段B本人6.5定位练习，不自动开始Agent/MCP。

## 提交前追加验证

用户随后明确授权提交与push。安全复核无新增高置信问题；架构复核发现并修复两条零编码路径误用作业数量限额，复现、修复与严格回归见0049追加记录。131项相关回归通过；原完整2230项结果为追加修复前历史证据，不能替代修复后完整回归。发布、标签和部署不在本轮范围，提交/远端状态以Git实际结果为准。

提交前修复后重新完整验证：`.venv/bin/python -m pytest -q tests --tb=short` → **2235 passed in437.84s（0:07:17）**。compileall与pip check退出0，工作区/暂存区diff检查通过。安全复核无高置信问题；架构发现1项、修复并复审关闭1项，未决阻塞0。提交范围限定62个源码/测试/Spec/文档文件，不含真实配置、依赖或用户数据。未配置GitHub Actions工作流；本轮只提交并push源码，不创建标签或发布包。
