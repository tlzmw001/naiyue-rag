# Spec0055：首版第4片／nyr入口与一个终端的chat

2026-10-28后续适配见[Spec0065](0065-nyr-shared-service-adapter.md)：nyr已启动共享检索服务，并补齐status/document/remove及query范围参数；本页保留首版生命周期合同与历史验收。

日期2026-10-26，依赖0054。产品范围已确认，本片不发布安装包。

## 命令与数据流

nyr [--config PATH]：按0052读取配置后前台运行0054服务。nyr chat [--config PATH]：以httpx直连配置回环地址（trust_env=False、不经代理、不跟随重定向），带服务Token检查protocol/config_identity/instance_id。无监听才用当前sys.executable -m naiyue_rag --config PATH创建服务，不使用shell；任何401/非本项目/配置不同/健康非法明确失败，不尝试占用者接管或换端口。

nyr documents、nyr ingest --expected-revision N [--force]、nyr query TEXT [--expected-revision N]：复用同一受控连接/启动机制，输出原JSON，退出清理仅本次子进程。首次摄取revision从documents所得active读取（无活动版本为0），不隐式摄取、不隐式force；用户可显式null初始化? 本版CLI要求非负整数，HTTP仍保留核心null语义。nyr models prepare ID显式调用既有prepare_local_model，仅允许cross_encoder；不启动服务，不默认下载模型。--help/--version无配置IO，默认配置路径只在实际命令执行初始化。

保留旧app.py库级main/execute及历史示例；python -m naiyue_rag切换到新CLI，旧例子改为python -m naiyue_rag.app（已有if main入口），旧多YAML不自动迁移。根帮助列明首版chat仅检索证据、不生成回答。

## 生命周期

LocalClient.health严格校验完整身份，连接拒绝可触发启动，超时/协议错误不作为无服务。ManagedConnection拥有自己创建的Popen及健康实例；启动等待使用monotonic截止、进程poll及有界状态轮询。启动stderr写临时文件，失败只显示固定安全码，不把模型/配置原文带到终端；不根据端口/PID查找杀进程。退出EOF、/exit、Ctrl+C或异常都关闭httpx及拥有的子进程；先通过关闭stdin通知本次子进程优雅停服，超shutdown_timeout后仅terminate/kill所持Popen并记录固定码，绝不影响复用服务。

子服务加内部--parent-watch选项，专用daemon线程读取父进程stdin管道；EOF置Uvicorn.should_exit。父进程异常结束也关闭管道避免孤儿服务；监视线程不读取用户终端，手动nyr不启用该选项。Windows无fork/Unix专用killpg假设；额外将SIGBREAK显式转换为Uvicorn.should_exit，结束时恢复原handler，以支持独立进程组CTRL_BREAK的优雅退出。服务有活动任务时遵循配置关闭超时，不能把强制关闭说成事务已完成；客户端不重试写操作。

chat逐行输入，/exit、EOF退出，Ctrl+C正常退出；每条调用query并打印context_text/状态，终端错误只显示安全码。UI输出须过滤终端控制序列（保留换行制表），不把文档内容当指令。无会话记忆、TUI或Agent回答。

## 影响和验收

cli.py、local_client.py、managed_service.py、__main__.py和service运行入口最小扩展；测试用临时HOME、临时配置/端口和合成材料。失败测试先覆盖parser/help不写HOME、错误选择、真实socket启动/复用/退出、已有服务退出仍存活、端口占用/认证失败不杀进程、就绪超时/启动退出、EOF/Ctrl+C/父管道EOF、CLI文档和模型准备路由。实际原生索引闭环在0056安装发行物再次执行。

L1命令模块存在；L2身份核对/进程所有权/安全输出；L3 subprocess实际进入新__main__并访问HTTP。模型Key不进入CLI参数、stdout/stderr或服务状态。既有HTTP结果保持原合同，CLI失败退出非0。实际命令结果实施后补充。

## 本片实测

先11 failed/1 passed（旧入口不支持version/chat/models，缺client/进程模块）；初次联合验证29 passed/1 failed（CLI文件错误码未按新统一配置入口归一），补齐后62 passed in9.82s。另补缺Key字段提示的失败测试，提供models_file默认models.json及api_key/api_key_env安全提示；相关67 passed in9.69s。真实新进程覆盖EOF清理、已有实例继续存活、父管道EOF、错误Token、非项目监听者不受影响；/exit和Ctrl+C处理有单元及安装入口验证，WindowsCTRL_BREAK实际结果待CI。L3安装入口原生闭环见0056。

收尾补充：客户端清理失败先2项红灯（掩盖原错误并外泄原异常），ManagedConnection对stdin/client/stderr统一安全关闭并始终尝试回收自己持有的子进程；有主要错误时保留，单独清理失败返回固定service_shutdown_failed。相关51 passed in7.00s；最终发行物在新的纯运行依赖环境实测通过，包括终端真实查询、父管道EOF及手动服务复用/退出，未升级当前开发环境既有SDK。
