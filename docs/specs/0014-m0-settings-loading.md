# Spec0014：M0第二切片——YAML配置加载与现有资源装配

日期：2026-10-11。状态：用户在首期内部共享范围修订后授权“继续”，本片已实现/接线并完成本机离线验收：56新增/597总测试。M0–M9路线已确认；本片承接Spec0013，不恢复暂停的Spec0012。以下设计保留，实际实施见第9节；M0统一最小追踪仍待。

用户随后明确首期面向内部人员的共享知识库，暂不做按用户/文档授权。此范围已确认：新入口默认使用所加载知识库全部可检索文档，调用方不提供授权清单；scope/exclude仅是检索过滤。下文按此修订，旧底层权限接口只作兼容保留，不扩展权限系统。

## 1. 当前数据流与参考证据

当前调用方在Python中构造12字段config→load_snapshot(config, authorized_document_ids, tokenizer_cache_dir)→原文/向量身份检查→A2Snapshot→retrieve_once(request, resources, embed_query)。配置无统一文件入口；请求仍明确提供五字段。

参考URL：https://github.com/Jerry-ai-dev/MODULAR-RAG-MCP-SERVER。只读本地main，commit f658c5a4011c8b826707a65a3b11ce9301b0626f，核验日期2026-10-11，工作区干净。未刷新远程、运行参考setup/测试/服务或复制源码。

- src/core/settings.py：load_settings→yaml.safe_load→Settings.from_dict→validate_settings；各分组为dataclass，多数frozen=True。默认配置路径从源码文件定位仓库根，相对资源路径有resolve_path工具。
- config/settings.yaml：retrieval显式dense_top_k=20、sparse_top_k=20、fusion_top_k=10、rrf_k=60；含LLM/Embedding/向量库/重排/评测/观测/摄取等配置组。
- 本机PyYAML 6.0.3已安装，无需新增依赖。这里只核源码/配置，不证明参考全部字段已接线或有效。

本片沿参考YAML→分组dataclass→from_dict→显式validate→消费者，集中当前有消费者的字段，不建立未运行模块的全量配置类。现有A2Snapshot约束rrf_k=60、BM25S Lucene k1=1.5/b=.75、numpy及分词策略；Embedding身份须与既有向量一致。

## 2. 目标和范围

新增本机离线配置入口，把一份YAML装配成已有A2资源；核心settings模块不依赖experiments。原load_snapshot/retrieve_once签名、输入语义和输出保持；新增便利入口不取代旧入口。检索算法、五字段请求、旧缓存和业务源不变。

不实现实时Embedding/LLM/Reranker/Agent/Chroma产品入口，不加入Provider占位或自动.env读取。不创建或改动真实运行YAML/.env；测试仅在tmp_path构造合成配置文件。批准本设计不包含部署、删除、回滚、push或其他仓库修改。

## 3. 文件结构与接口

拟影响7个业务/测试文件：

1. 新增naiyue_rag/core/settings.py：Settings及SnapshotSettings/EmbeddingSettings/RetrievalSettings/SparseSettings/RuntimeSettings，显式from_dict/validate_settings/load_settings。
2. core/errors.py新增安全SettingsError(code)，保留原错误类身份。
3. core/__init__.py导出配置入口/类型及错误。
4. 新增naiyue_rag/bootstrap.py：load_snapshot_from_settings(settings_path)。
5. naiyue_rag/__init__.py新增该入口导出，不改变原三项。
6. 新增tests/test_settings.py：解析/类型/字段/路径/失败及安全日志。
7. 新增tests/test_settings_wiring.py：真实资源装配、默认全库/请求过滤、缓存身份/完整性及旧四题离线对照。

每源码≤500行；现有测试/helpers/依赖不改。README、Spec索引、project-plan、handoff和学习记录按事实同步。

load_settings(path)要求显式本地配置文件路径；Settings持有冻结分组对象，to_snapshot_config()产生隔离的旧12字段字典。runtime仅提供tokenizer_cache_dir。bootstrap从已有验证过的load_corpus结果取sorted(corpus['sources'])全部ID，将旧config、该ID列表与缓存路径传给原load_snapshot，返回A2Snapshot；不包办查询或模型调用。旧load_snapshot参数不变，已有授权测试保留，新入口不要求使用者维护清单。这是配置知识库内全部可检索源，不能扫描配置范围外文件、恢复摄取排除源或把不存在ID当合法范围。

兼容阶段会先load_corpus取ID，再由原load_snapshot加载并核对，存在一次额外原文/片段验证读取；为避免改公开语义或新增资源工厂，本片明确接受这项小型离线开销。源变化仍明确失败；通用Loader/资源装配进入M1–M5后沿模块Spec整理，不以此冒充查询性能优化。

## 4. 配置字段与实际消费者

所有组/字段必填，未知组/字段拒绝，不隐式补默认，不把字符串转换成数值。

| 分组 | 字段 | 实际消费者 |
|---|---|---|
| snapshot | dataset、corpus_run、vector_run | 原load_corpus/load_index和verify_current |
| embedding | endpoint、model、dimensions | 原identity/load_index/_embedding；endpoint仅声明旧缓存身份，本片不访问网络 |
| retrieval | rrf_k | retrieve_once→fuse |
| sparse | bm25_k1、bm25_b、bm25_method、backend、tokenizer_policy | 原parameters/Tokenizer/build_index |
| runtime | tokenizer_cache_dir | 原Tokenizer初始化 |

值要求：各字符串非空合法Unicode；dimensions为非bool正整数；rrf_k非bool整数且当前兼容60；k1/b为有限非bool数值且当前分别1.5/.75；bm25_method=lucene、backend=numpy、tokenizer_policy=zh-search-ascii-ident-v1。这些冻结值用于现有资产兼容，不承诺通用参数调优。模型/维度/endpoints可表达其他身份，但旧索引不匹配时原load_index拒绝，无自动重建、转换或降级。

candidate_k/max_context_chars继续由QueryRequest提供并校验；三路top-k独立配置在M5形成消费者时接入，不能在本片新增不起作用的参考字段。首期无用户/角色/文档ACL配置，默认知识库全量可检索；scope_document_ids/exclude_document_ids只按任务筛选，未知ID仍明确报错。

## 5. 路径、解析和错误

- 显式配置path由调用方提供，相对path先基于本次调用的cwd解析成绝对路径。配置里的四个资源/缓存路径相对配置文件所在目录解析；绝对路径保留规范化。部署目录变化无需硬编码本机路径。
- 这是受信任本机管理员配置入口，不是远程用户文件入口；允许管理员配置../data等相对路径，规范化不当作路径沙箱。加载范围由已配置知识库及其验证结果决定；不增加公网入口或用户/文档授权系统。
- 文件读取上限64KiB，UTF-8严格解码；空文件、非mapping、重复键、YAML自定义对象标签、alias/merge key及递归结构拒绝。基于已装PyYAML SafeLoader加必要限制，无eval/通用插件。
- load_settings本身只读文件，无目录创建、网络或.env副作用；bootstrap进入Tokenizer会创建新缓存目录，沿旧接口fresh cache要求，路径已存在明确失败，不清空或复用旧缓存。本片不自动生成随机缓存目录。
- 配置读取/解码/解析/字段失败使用固定code：settings_file_error、settings_too_large、invalid_settings_yaml、invalid_settings。错误与日志不含路径、原文、输入值、凭证或parser原异常；日志仅阶段settings和code，异常链from None。
- bootstrap读取源ID以及加载既有源/索引/Tokenizer时保留原RetrievalError及安全日志；取源阶段ProbeError映射为resources及原category，只记录固定stage/code，不暴露原异常。旧内部授权参数自动取全库合法ID；不吞错，不隐式换资源或单路降级。配置失败必须在Tokenizer、模型及索引写操作之前发生。

## 6. 相对参考的必要差异（确认后实施）

| 参考做法 | 本片建议 | 原因 |
|---|---|---|
| 全量运行模块配置 | 先配置当前已有消费者；随模块增加分组 | 避免能填写却不起作用的字段，保证L3接线 |
| 相对路径统一仓库根 | 资源路径以配置文件目录为基准 | 同一配置换cwd含义稳定，便于独立目录及另一机器迁移 |
| YAML有api_key字段 | 本片无凭证字段/不读.env；M3另定api_key_env引用 | 当前仅离线身份，无模型消费者，避免配置与Git记录泄漏 |
| 基础类型/非空校验与safe_load | 严格字段/非bool数值/重复键/alias/容量及安全异常 | 避免字段误拼、隐式覆盖与错误原文泄漏；不引入另一配置框架 |
| 参考检索20/20/10 | 保持现有请求统一k及冻结A2结果 | 本片只装配，独立top-k/调参归M5，历史对照不变 |

用户已确认本片采用内部共享全库使用方式，无按人员/角色/文档权限治理；配置设计不会增加权限分组、身份目录、登录或ACL功能。未来确有隔离需求时再单独讨论，不作为当前模块退出条件。

前提：当前消费者仍为冻结A2兼容资源。若需要马上索引任意真实文档或动态模型，这片不能完成该目标，须继续M1–M5而非移除现有检查。

## 7. 正常、异常和验收（待执行）

正常：tmp_path YAML→Settings→12字段无损桥→已校验源ID自动取全库→真实load_snapshot→11源/52片段→现有四题缓存retrieve_once，各路候选/最终证据/文本/预算与旧A2逐字段一致。scope=None/exclude=[]覆盖所加载全库；显式scope/exclude能筛选两路召回，未知ID明确失败；更换cwd不改变配置内路径语义。调用方无需传授权清单。

异常：缺/无法读取/超限文件、非法UTF-8/语法/标签/重复键/alias/merge/根类型、缺字段/未知字段、bool/错误数值/无效Unicode/NaN、未知或不属于所加载知识库的ID、身份不匹配、源变更、缓存目录已存在均明确失败。非法配置不调用Tokenizer或模型；失败日志/异常/repr不泄漏合成敏感哨兵。原返回/错误身份/所有既有测试保持，不为取消首期权限规划而删除旧兼容测试。

先新增测试确认缺模块或缺行为红灯，再最小实现；不得修改旧断言/helpers让结果通过。接线spy只能补充证据，须有真实装配及离线四题回归。测试阻断Python网络，不使用真实Key/模型，不把服务使用量记成零费用收益。

计划验证命令，当前未运行，不能填成功数量：

```sh
.venv/bin/python -m pytest -q tests/test_settings.py tests/test_settings_wiring.py
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

compileall为语法检查，不冒充发布构建。当前无打包构建入口，构建不适用。

L1检查7文件；L2确认真实加载/校验/兼容桥而非空类；L3确认新增入口确实传递配置→原资源→真实retrieve_once，四题对照与非法路径失败。全量工程通过不代表真实知识库/业务质量/通用产品/生产通过。

## 8. 回滚边界与唯一下一步

旧函数保留，调用方可继续旧字典入口；无源文件、索引、锁文件或配置格式迁移。失败可留下新建分词缓存目录，报告路径给受信任调用方核对，不自动删除；本片不执行回滚动作。代码回退需按用户规则授权，不能清理他人工作区。

设计时下一步为确认后TDD，现已按用户“继续”完成；当前唯一下一步为配置装配小课。

## 9. 实际实施与验证（2026-10-11）

已按7文件范围实施，无新依赖、算法/缓存/旧API修改或真实运行配置变更；只在测试tmp_path构造合成YAML及未使用的合成.env哨兵，证明加载器不读取.env。未发真实模型请求、复制第三方源码或修改其他仓库，无提交/push。

TDD：两份新增测试首次实际2收集错误，缺core.settings及load_snapshot_from_settings。最小实现后56新增通过，全量旧541+新增56=597。没有放宽断言/skip/修改旧测试或helpers。Settings.from_dict构造冻结分组，validate_settings显式检查，to_snapshot_config重新校验；SafeLoader派生拒绝alias/merge/重复/非字符串键，读取上限64KiB，错误日志安全。

实际最终命令与结果：

```sh
.venv/bin/python -m pytest -q tests/test_settings.py tests/test_settings_wiring.py
# 56 passed in 1.61s
.venv/bin/python -m pytest -q tests
# 597 passed in 52.89s
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0，无输出；仅语法检查，打包构建不适用
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0，无输出
```

L1：7文件存在；settings180行/bootstrap26/errors19，两新测试185/137，均≤500。L2：真实读取/冻结分组/校验/路径解析/安全错误/旧格式桥，无占位；core不导入experiments。L3：公共load_snapshot_from_settings→load_settings→to_snapshot_config→已校验全库ID→真实原load_snapshot→11源/52片段及实际jieba缓存→retrieve_once。spy观察到旧12字段、11 ID和指定缓存路径传给原加载器；另一个缓存路径的实际文件证明配置真正消费。scope=None默认全部，scope/exclude实际过滤两路，未知ID在Embedding前拒绝；无授权清单，旧接口/权限测试保留兼容。

旧四题各路candidates/selected/budget_excluded/context_text/context_characters/max_context_chars/status/answerability及union_candidates逐字段等于原A2。四次Embedding回调读取旧真实向量缓存，source_kind=cached，无新服务调用；不把缓存回放当真实新问题效果。非法配置在任何资源加载前失败，模型身份/维度不符在Tokenizer前失败；源加载错误安全映射，索引变更在Embedding前失败；缓存目录已存在时明确失败且哨兵保持。load_settings仅打开指定配置文件，不创建目录/读.env/网络。

保护证据data/research/spec0014-evidence：85既有源码/测试/Mock/依赖文件hash未变，3允许修改文件另存前状态；135已装分发版本一致，core实验依赖0。原staged/untracked工作保持。保护检查不替代业务验证。

限制：仍仅冻结合成Mock/旧索引，bootstrap及旧资源仍依赖experiments，额外一次源验证读取，fresh cache不能重用；不是真实材料、通用摄取、动态模型、全配置体系或生产验收。仅本机离线库入口，无HTTP/MCP入口声明。M0统一最小追踪待，模型配置扩展归M3。

学习状态：QueryRequest引导题已记Lesson6；新Settings代码尚未逐行课堂或本人复写，不预填Lesson7。

唯一下一步：讲配置装配一条真实链，随后准备M0最小追踪Spec。
