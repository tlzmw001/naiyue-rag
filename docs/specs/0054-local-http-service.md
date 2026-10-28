# Spec0054：首版第3片／本机HTTP服务

日期：2026-10-26。依赖0052、0053；按已确认本机首版目标实施。

## 数据流与接口

create_service(ApplicationSettings)→FastAPI lifespan拥有ApplicationRuntime→同步业务在线程池执行→原核心；健康检查不争业务锁。run_service只绑定配置的127.0.0.1，单worker、无reload，禁用文档/OpenAPI。依赖新增fastapi0.162.0、starlette1.10.0，保留现有uvicorn0.54.0；预解析无既有版本升级。

全部路由先显式校验Bearer服务Token（常量时间比较），再读取请求。只接受本机Host及无浏览器Origin的请求，首版不开放跨域；反向代理头不信任。无未经认证的健康接口。GET /v1/health返回protocol=1、随机instance_id、config_identity；identity是规范化主配置与严格读取模型注册表摘要的SHA256（包括访问Token/模型变化但只返回摘要，不含配置内容）；服务摘要来自运行时实际持有的注册表，客户端仅计算摘要，不解析模型环境变量凭据。相同路径及主配置须一致，配置改变不热加载。

POST /v1/documents接收expected_revision可选；POST /v1/ingest接收必填expected_revision、可选force；POST /v1/query接收必填query及可选scope_document_ids、exclude_document_ids、expected_revision。JSON仅允许对应字段，重复键、NaN、非对象、非JSON及超service.max_request_bytes预算拒绝；不回显用户输入。revision为非负整数或null，ingest必须提供；query为非空str，ID列表逐项非空字符串且去重由核心校验。返回原核心字典，不再包装证据，保留schema2、用量和activation状态。

明确错误{error:{code,...原核心结构化报告}}；未认证401，输入400/413/415，本机访问边界403，busy/revision冲突409，已知核心失败422，未知内部失败500。异常只记录固定安全代码，不记录原始请求、凭据、网络响应或traceback；不自动重试摄取或查询。错误报告沿现有to_dict，绝不把任意异常str送给客户端。健康可用于自动启动识别，远程停止接口不提供。

## 正常与异常验收

测试认证先于解析、错误脱敏、重复JSON/预算/未知字段、Host/Origin/代理边界、健康身份稳定且实例区分、摄取/重复摄取/列表/查询HTTP原链闭环、业务busy期间健康可用、关闭归属和错误脱敏。TestClient不替代真实socket证明；第4/5片用安装入口子进程验证原生HTTP和退出。无Agent、回答生成、文档ACL、上传或任意目录请求。

影响service.py、service_protocol.py、requirements-service.txt及对应测试，runtime核心不依赖FastAPI。失败回退只撤适配代码，不改旧快照和原文。L1模块和依赖；L2认证/预算/错误/lifespan；L3 HTTP请求真实调用0053运行时。实际测试结果实施后补充。

## 本片实测

测试先18 failed（service模块不存在），最小接线后18 passed in2.38s。新增模型表身份变化测试先1 failed，身份改为主配置加运行时实际Registry摘要；后续和CLI/运行时/Registry联合62 passed in9.82s。安装后的真实HTTP和原生双索引闭环见0056。Windows SIGBREAK分支补充先KeyError红灯，再显式注册/恢复handler；这是本机模拟分支验证，Windows实际信号结果仍待CI。
