# Spec0045：优化分片2／切分策略身份与历史资料包读取

日期：2026-10-26。状态：已实现/接线/本地验收，本片完整回归2178项通过。本片验收时只启用v1；后续0046已启用新任务默认v2，旧持久化缺策略字段仍显式解释为v1。

## 1. 问题、依赖与范围

顺序上接0044，供0046和0047复用。当前DocumentChunker._profile已记录组件版本、分隔符、size/overlap及config_sha256；但IngestionSettings只有size/overlap，IndexBundle校验直接用当前DocumentChunker重做M2。因此直接修改全局SEPARATORS会影响历史资料包校验。

本片先让切分规则可按已保存身份重放，不改变当前实际切分结果。保留现有markdown-source-v1规则和真实组件版本检查，不重新编码、迁移、覆写旧资料包或升级依赖。

## 2. 推荐接口与身份

IngestionSettings保留两个既有位置参数，增加keyword-only chunking_policy=None；构造时把None规范成当前新建任务策略，本片仍为markdown-source-v1。持久化读取缺省策略必须显式解释为markdown-source-v1，不能依赖日后变更的新任务默认值。

DocumentChunker仍接受同一settings参数；按策略ID选实际分隔符、keep_separator及保护合同。未知策略明确失败，不降级到当前默认。策略解析可放core/chunking_policy.py，原因是分隔符定义/序列化/身份将被Chunker、Bundle校验及复用规划三处消费。

策略profile含policy、实际separators、keep_separator、strip_whitespace、parser/splitter版本、size/overlap及既有config_sha256。只添加版本标签不能替代实际参数比对。

## 3. 序列化与旧资料包字节身份

保存v1时，ingestion_settings继续输出原有两个字段；读取原有两个字段映射为显式v1。后续新策略输出三个字段，缺省/显式身份在对象比较中先规范化。

旧Chunk的component_metadata维持旧字段和值，不能为了新代码给旧记录增加字段后再声称相同。BundleStore.load中_materialize重新计算的旧manifest和bundle_id必须保持一致。两字段/三字段严格分支，其他未知字段拒绝。

IndexBundle重核M2时使用资料包保存的策略。默认策略改变不能改变既有v1包的to_dict或manifest。分词/表示/模型身份不因仅重放旧策略而变化。

实际安装组件版本与历史profile不符时仍明确失败；本片不引入跨依赖版本解释器或放松组件版本检查。未知历史策略也明确失败。

## 4. 复用接线

扩展profiles_match对有效切分策略及实际profile的检查。相同源字节但策略不同必须失效，不把相同size/overlap当作相同切分。文档原始ID/hash不改；Chunk ID仍沿现有源版本/kind/span机制，不为所有片段强行换ID，完整profile及bundle身份区分处理策略。

本片新增策略机制必须已接Bundle读取和现有规划，不能只创建未调用配置类。显式新策略在0046注册后才能使用；未知ID测试不提前返回占位规则。

## 5. 影响文件

core/ingestion_settings.py、core/settings.py、ingestion/document_chunker.py、core/chunking_policy.py、ingestion/file_integrity.py、storage/artifact_bundle.py、storage/bundle_store.py；检查所有asdict(ingestion_settings)消费者。对应test_settings.py、test_document_chunker.py、test_storage_bundle.py、test_storage_bundle_wiring.py、test_file_integrity.py、test_ingestion_pipeline.py。超过8文件，无服务/依赖/真实配置修改。

## 6. 验收、失败与回退

红灯先固定本片修改前生成的最小v1合成资料包及manifest摘要，再证明新实现仍能读回、源位置/profile/ID一致。旧夹具由当前生产链+模拟模型生成，不使用用户材料；测试记录生成方法，不用新实现重新生成期望来掩盖兼容问题。

覆盖旧构造、旧YAML、两种持久字段形状、未知策略、非法值、profile篡改、参数变化失效、加载后再物化身份不变、源目录离线及新进程读取。保留原有损坏/路径/限额检查。

L1新策略模块存在；L2实际参数解析与身份校验；L3旧资料包→新进程BundleStore→管理/准备消费者真实接线。本片正常切分与旧基线完全相同。

计划命令：

```sh
.venv/bin/python -m pytest -q tests/test_settings.py tests/test_document_chunker.py tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py tests/test_file_integrity.py tests/test_ingestion_pipeline.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag experiments tests
.venv/bin/python -m pip check
git diff --check
```

不写旧存储，代码层撤销不需要数据回滚；不执行自动撤销用户工作。构建不适用。完成后说明0046准备使用的分隔符次序、标点保留方式和固定对照样本。

## 实施前基线准备

2026-10-26，在切分策略源码变更前，以现有make_bundle合成材料与模拟编码生成tests/fixtures/chunking-v1-bundle.json，保存完整旧Bundle及生产_materialize得到的manifest，40135字节，bundle_id=97d101fb8fc6e4de0aceb96a859de7d69dca1191adeb09e900d0d2b30d1a1f03。测试不得用新实现重生成该期望。生成时socket连接被禁止，无真实模型/私有材料。

策略模块放core/chunking_policy.py：IngestionSettings在core内，避免它导入ingestion包时触发包初始化、Chunker再反向导入Settings的循环。规则内容与已确认行为不变；只调整模块放置。

## 7. 2026-10-26实施与定向验证

本轮先运行既有tests/test_chunking_policy.py，复现11 failed in0.42s，缺策略字段、严格序列化与历史重放入口。最小接线后11 passed in1.75s。扩展实际profile篡改、依赖版本不符、两种输入字段形状及参数副本隔离，现共17项。

实施期间一次补丁因settings.py上下文不匹配未应用；续补接线时新策略模块尚未创建，出现一次ModuleNotFoundError收集失败。立即补齐策略模块及配置实现后原11项通过，未通过修改测试消除该导入错误。

新增core/chunking_policy.py集中定义现有v1分隔符、保留方式、实际依赖版本和规范profile指纹；不注册v2占位规则。IngestionSettings保留两个既有位置参数，新增keyword-only策略；运行构造缺省走当前新任务默认，持久化from_dict缺省固定v1。v1的to_dict仍只输出size/overlap，旧包物化字节不变。Settings的运行配置入口允许显式策略并沿现有validate_settings固定错误渠道验证；未改真实YAML/.env。

DocumentChunker实际消费profile参数，IndexBundle实际按持久化策略恢复和重核M2；profiles_match同时核设置与每个片段实际profile。profile比较使用规范摘要区分True与1，避免Python容器相等把类型篡改当作一致。未知策略不回退，旧profile或组件版本不符仍失败。

影响文件落实为core/chunking_policy.py、core/ingestion_settings.py、core/settings.py、ingestion/document_chunker.py、ingestion/file_integrity.py、storage/artifact_bundle.py；新增tests/test_chunking_policy.py及原先已冻结的tests/fixtures/chunking-v1-bundle.json。BundleStore源码无须修改：它既有load→IndexBundle.from_dict→_materialize调用已消费新的严格策略读写，固定manifest和新进程回归验证该接线；不为符合影响文件列表而空改源码。

实际命令及输出：

```sh
.venv/bin/python -m pytest -q tests/test_chunking_policy.py tests/test_settings.py tests/test_document_chunker.py tests/test_storage_bundle.py tests/test_storage_bundle_wiring.py tests/test_file_integrity.py tests/test_ingestion_pipeline.py tests/test_document_removal.py --tb=short
# 297 passed in 29.02s
.venv/bin/python -m pytest -q tests/test_chunking_policy.py --tb=short
# 17 passed in 1.67s（进一步加入冻结旧包→真实Chroma/BM25→管理/查询准备消费）
```

后一次验证在独立进程中使用冻结旧包及真实本机索引，源目录不存在、网络连接被禁止，文档列表/详情、活动版本及空范围QueryPipeline.prepare正常，编码调用0。另一进程完整Bundle JSON回读与固定manifest相等；不是用新生成数据替换旧夹具。

L1：上述6源码/测试/冻结夹具存在；L2：真实参数解析、严格策略读写、profile核验实质执行；L3：配置→Chunker、旧包→新进程→真实双索引→管理/查询准备、现有run/remove复用门禁均有消费证据。compileall退出0，pip check为No broken requirements found.，工作区/暂存区diff检查退出0。打包构建不适用；完整回归已通过，结果见下节。


## 8. 最终本地验收与下一片

实际完整命令`.venv/bin/python -m pytest -q tests --tb=short`：**2178 passed in444.57s（0:07:24）**，无失败或跳过；覆盖本轮17项策略测试及第1片等现有测试。`.venv/bin/python -m compileall -q naiyue_rag experiments tests`退出0；`.venv/bin/python -m pip check`输出`No broken requirements found.`；`git diff --check`和`git diff --cached --check`退出0。未设打包构建命令，构建不适用，compileall仅语法检查。

本片完成L1/L2/L3及本机工程验收，当前切分仍为v1；没有真实模型/真实资料质量或跨依赖版本历史读取的通过声明。保留旧组件版本不匹配即失败，不重新编码、覆写、迁移或删除已有用户知识库，未改真实配置或依赖，未提交/push。

唯一下一步为Spec0046：沿本策略入口注册markdown-source-zh-v2，加入独立字面量“。”“，”，keep_separator=end；新任务默认切到v2，旧持久化仍固定v1。先写失败测试，再固定size/overlap比较中英文正文边界、句末标点、重复文本与真实来源位置，并回归代码/表格/完整用例保护；验证策略变化使旧编码复用失效。结构/边界对照不直接声明检索质量提升。本轮按用户要求仅说明下一片，不进入第3片实现。
