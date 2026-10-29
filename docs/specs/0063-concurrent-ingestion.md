# Spec0063：更新与在途查询并行

RetrievalService.ingest(expected_revision,force=False)使用独立writer ApplicationRuntime和更新互斥锁，
不占查询执行槽位，不清除查询资源注册表。documents通过独立DocumentManager消费当前已提交版本。
当前IngestionPipeline已在新bundle/双索引完成后使用SQLite revision门禁发布，继续复用该流程。
旧bundle不可被更新流程原地修改；跨线程Chroma生命周期仍由已有原生锁保护。

验收：查询A在版本1编码阶段阻塞，更新独立完成版本2激活；查询B读取版本2；A完成证据仍版本1。
更新失败时新查询继续使用原活动版本。旧资源在A后台完成前不释放；同一服务更新串行，查询互不拒绝。
多个入口进程不构成本片多写保证，SQLite revision冲突仍明确返回。不新增自动修复/业务重试。
服务关闭时停止新的更新并等待已开始writer；关闭期限耗尽明确报错，不能同时关闭其Provider。

影响serving/engine.py、resources.py、service.py和原生更新/版本测试，存储格式与摄取公开API保持。
Git同步后续独立实现：本片提供其调用的更新入口，不预先填远端URL/分支/凭据/周期。

## 实施与验证

独立writer与查询执行槽位已接线，更新互斥不占查询槽位，关闭停止新更新并在期限内等待已开始的更新。
事件同步的替身集成及独立进程真实Chroma/BM25测试均验证：查询A固定revision1并阻塞；
更新激活revision2；查询B返回revision2；释放A后仍返回revision1。更新失败保留原active及证据。
共享资源按引用归还，取消但未退出的请求继续持有旧版。最终完整2424 passed in490.51s。
没有执行远端Git同步或创建定时任务；本片仅提供其将消费的安全更新入口。
