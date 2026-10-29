# Spec0059：服务查询复用已校验版本资源

用户确认：按版本缓存，查询检查版本及文件变化，变化后重新加载、解析和审计。

当前链路：HTTP→ApplicationRuntime.query→QueryPipeline→两路召回→证据组装。
合成回归确认第二次查询仍有17次BundleStore.load、34次完整语义重放和各3次索引审计。
根因是BundleStore.load反序列化及_materialize均重放切分，查询各层独立加载和审计。

实现：每个ApplicationRuntime持有一个当前版本资源缓存，仅query期间启用；核心库独立使用仍完整校验。
每次查询读取catalog，按revision及完整版本身份选择缓存；对该版本artifacts/vectors/bm25目录递归检查
文件路径、类型、设备/inode、大小、mtime_ns、ctime_ns。变化即丢弃缓存，按原路径重新验证，失败明确返回。
不扫描用户Markdown源目录。轻量文件状态检查不是每次重新计算内容哈希，服务目录应仅由受控写入流程修改。
冷加载完整审计成功后记录基线（Chroma首次打开可能维护原生文件）；热查询期间文件状态变化或查询失败丢弃缓存。
文件状态检查不提供对并发恶意写入的事务隔离；已发布目录不得由其他进程原地修改。

缓存对象：已验证Bundle、Chroma/BM25预备数据、DocumentManager审计结果、已加载并审计的BM25模型和Chroma客户端。
原生测试确认Chroma每次关闭会写SQLite/HNSW文件，故查询客户端随版本保留，在缓存失效/摄取/关闭时释放，
两路仍使用既有SDK生命周期锁。独立核心查询和摄取不保留客户端。
仅一个版本，关闭及版本切换释放；不缓存问题、向量请求、检索结果或错误。缓存对象只供内部只读查询链消费，
返回证据仍复制，不将缓存对象暴露给调用方。两路线程显式传递独立Context，缓存写入用锁串行化。
原存储格式、公开签名、配置字段不变；无TTL、新依赖、磁盘缓存或自动重建。

影响runtime.py、storage/query_cache.py、bundle_store.py、document_manager.py、chroma_index.py、bm25_store.py、
query/hybrid_search.py、storage/chroma_backend.py及测试。缓存装饰器仅在服务query上下文生效；摄取/激活/独立存储审计仍按原合同执行。

验收：连续查询不再重放全库、不重复加载BM25；结果一致、每次问题仍编码；外部文件修改/删除/软链接、
版本切换、失败和关闭正确失效；两路共享缓存；原生双索引验证；完整测试及构建通过。
回滚仅撤缓存接线，不改已发布知识库。首次进程查询仍完整校验，不承诺远端性能提升数值。

## 本机验收（2026-10-28）

- 初始回归确认第二次查询parse=34/load=17/vector_audit=3/sparse_audit=3；修复后热查询语义重放、
  资料包重建、Chroma全行审计、BM25原生加载均为0，证据相等。每次问题编码仍执行。
- `.venv/bin/python -m pytest -q tests/test_query_resource_reuse.py tests/test_query_resource_cache_native.py tests/test_application_runtime.py tests/test_local_service.py --tb=short`：36 passed in14.55s。
- 原生Chroma/BM25独立子进程验收包含首次与连续查询、相同证据及warm_corpus_replays=0；原生客户端按版本保留，关闭失败仍释放Provider。
- `.venv/bin/python -m pytest -q tests --tb=short`：2391 passed in463.62s。
- `.venv/bin/python -m build --outdir dist/query-cache-candidate`：wheel/sdist成功；inspect_distribution与Twine严格检查通过，compileall及pip check通过。
- 两份新增回归纳入`scripts/run_formal_tests.py`；分发与正式清单测试5 passed in0.70s。

L1：query_cache模块/回归/本Spec存在；L2：版本与文件状态检查、资源复用和释放有实质实现；
L3：ApplicationRuntime.query进入缓存上下文，两路线程复制上下文，摄取/关闭清理缓存，原生测试已实际调用。
未修改真实环境配置、模型或用户知识库；未提交、push或发布。候选制品沿现有0.1.0源码版本构建，仅供本地验证，
不能覆盖已发布的0.1.0。公司Linux真实材料及CPU耗时仍待升级后验收；完整重新联网安装smoke未完成，不以构建代替该证据。
