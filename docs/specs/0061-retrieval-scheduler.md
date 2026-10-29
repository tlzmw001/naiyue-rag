# Spec0061：有界调度与请求生命周期

按0060和用户“直接做，一直到做完”实施，无新产品决策。
当前业务全程持ApplicationRuntime锁。新模块独立拥有队列/执行槽位，不用HTTP线程池充当业务调度器。

接口：RetrievalSettings(max_concurrent_queries=2,max_queued_queries=20,request_timeout_seconds=180,
shutdown_timeout_seconds=10)；主配置可选retrieval节，缺省回填，旧配置继续可读。
180/10沿当前模板已有请求/关闭默认秒数；与HTTP客户端等待分别配置。
Scheduler(execute,settings,on_worker_exit=None)；submit(*args,timeout_seconds=None,**kwargs)返回QueryHandle。
handle.request_id/result(timeout=None)/cancel()/status()；result返回原证据或RetrievalError(code)。
status报告state、backend_finished；queued/running/succeeded/failed/timed_out/cancelled，调用方终态与后台完成分开。
execute(slot,control,*args,**kwargs)；控制对象持取消Event和monotonic期限。
状态/队列/槽位变更由同一Condition保护；默认2个长存执行线程+1个期限监控线程，均由服务拥有。
准入直接预留空闲槽位，否则进入20条FIFO等待；第21条等待明确retrieval_overloaded。
取消/超时移除排队项；运行项仅终结调用方Future并设信号，执行返回前保留槽位。
过期任务不能执行模型；完成/取消/超时竞争只有一个Future终态。无服务重试、无强杀线程。
关闭停止准入、取消队列并请求运行项收尾，在配置关闭期内等待；未结束明确retrieval_shutdown_timeout。
重入关闭可再次等待，不能把仍运行误当成功；不从工作线程等待自身。

影响core/retrieval_settings.py、core/application_settings.py、resources/config.yaml、serving/control.py、
serving/scheduler.py、serving/__init__.py、pyproject.toml及测试/正式清单。
先失败测试：10条受理且两条重叠、22条容量边界、FIFO、队列取消/超时、运行取消保槽位、重试容量、
唯一终态、错误透传、关闭与配置严格校验。事件/条件同步，不以紧sleep断言时序。
回退只撤新接口，不改旧数据。L3先替身executor，0062接原生链。

## 实施与验证

调度器、控制上下文、配置和模板已实现；旧配置缺retrieval节回填默认值。
handle补充wait_backend(timeout)以及elapsed/queue/execution_seconds聚合计时，result(timeout)只限制调用方等待。
最初调度11项红灯后绿灯；后续增加关闭失败重试回归。最终完整命令
`.venv/bin/python -m pytest -q tests --tb=short`：2424 passed in490.51s。
两执行槽位/二十等待、超时不提前归还槽位、取消/完成唯一终态均有事件同步验证，正式CI清单已包含本片。
生产模块使用serving命名空间，因为原retrieval.py是已有历史实验适配，未覆盖或删除旧资产。
