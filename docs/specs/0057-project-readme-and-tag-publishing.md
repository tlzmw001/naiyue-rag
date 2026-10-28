# Spec0057：项目介绍与标签触发PyPI发布

日期2026-10-26。用户要求重写README为项目介绍，并采用Git标签触发PyPI发布。本轮完成文档、工作流和本地验证，不提交/push、创建标签或上传PyPI，不配置用户账户。

## 当前数据流与问题

0056已有wheel/sdist、安装验收和三平台CI，但每个平台分别构建，工作流/归档检查/installed_smoke写死0.1.0.dev0。README混合阶段流水、课程与历史命令，不适合作为GitHub/PyPI首页。版本唯一来源仍为naiyue_rag/_version.py；当前dev候选不擅改成正式版本。

## 目标合同

README改为用途/现有能力/安装与首次摄取/配置/命令/边界/文档入口；历史机制与验收由已有Spec、handoff、learning-roadmap承载，不删除历史源码/测试。首页不声称Agent、前端、MCP或未经CI的三平台已发布；PyPI复用的文档链接采用可访问的GitHub绝对URL。pyproject增加仓库/文档/issue链接，不选择许可证。

package-validation.yml成为可复用的验证工作流：构建一次→审计及Twine元数据检查→三个系统下载并安装完全相同的wheel→正式独立回归；上传的同一wheel/sdist供发布消费，验证步骤不得重新构建另一套文件。普通分支push/PR/手动触发只验证；tag事件由publish-pypi.yml唯一发起发布链，避免双重验证和发布入口扩散。

publish-pypi.yml仅由push的v*标签触发，先验证标签严格vX.Y.Z、与源码版本精确一致且位于origin/main已提交历史；正式发布须有明确project.license和实际license-files，否则失败。版本/许可证未定不妨碍分支候选构建，不自动改版本或选MIT。调用三平台验证全部成功后，独立Ubuntu发布job仅下载已验收制品，使用环境pypi及job级id-token:write调用官方PyPA action，不checkout/执行本项目构建脚本，不保存长期Token。随后只读验收job对照PyPI文件名/SHA256，并从公共PyPI新建venv安装准确版本，离开源码cwd验证nyr和原生闭环。

只授予发布job OIDC权限；其他job contents:read。不为PR、分支push或workflow_dispatch开放发布，不开启skip-existing，不自动删/重打标签。上传不是原子事务，失败先检查PyPI实际文件；发布后验证失败不能假装撤回，重跑失败验收job，不覆盖已有版本。

版本脚本严格读取当前版本，选择准确的wheel/sdist并核对双包元数据；检查工具/安装smoke改为接收或核对实际目标版本，不能用放宽旧断言消除版本门禁。所有CLI传值经参数或env安全传递，标签不直接插入shell程序文本。

## 影响与验证

README、pyproject URLs；package-validation/publish-pypi工作流；scripts/release_tools.py及现有inspect_distribution/validate_candidate/installed_smoke；requirements-dev增加Twine构建检查工具；新测试并纳入正式独立清单；docs/publishing.md给出账号与仓库的准确配置表。无运行时新依赖，无真实配置/密钥变更。

先失败测试覆盖标签/版本/许可证、制品版本/异常文件、registry哈希和错误、工作流权限/依赖/同一制品；README检查实际命令和本地/远程链接，build/Twine检查PyPI长描述；相关/正式回归与当前完整回归，当前dev候选新建安装环境或纯运行环境验证入口。真实OIDC、首次建项目、公共pip安装只在真正标签发布后成立，本轮不把本地测试说成PyPI已配置或已发布。

PyPI采用Trusted Publishing：GitHub owner=tlzmw001，repo=naiyue-rag，workflow=publish-pypi.yml，environment=pypi；首次项目用账户Publishing下pending publisher，名称naiyue-rag，非名称预留。账号须按PyPI要求验证邮箱/2FA。GitHub pypi环境限制v*标签，不新增必需人工审批以保留标签自动发布；若用户自行配置reviewer则会等待其审批。许可证/正式版本在首个真实标签前再确认。

来源：[PyPI pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)、[使用publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/)、[PyPA Actions指南](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)。官方发布action固定已核验v1.14.3的提交SHA，避免浮动引用；不运行第三方setup。

## 本地验收（2026-10-27）

- 首轮18项红灯（缺release_tools/发布工作流、旧验证不支持复用）；接线后相关23通过；补齐registry可见性重试/超时、GITHUB_OUTPUT仅门禁成功后写入、未来版本审计后，发布/打包27 passed in0.29s，与CLI联合43 passed in5.65s。正式回归job也下载同一制品，避免二次构建，额外门禁先KeyError再绿。
- `.venv/bin/python -m pytest -q tests --tb=short`：2375 passed in456.92s (0:07:36)。生产RAG实现/签名不变，已有测试断言不放宽、不skip。
- `.venv/bin/python -m build --outdir /tmp/nyr-tag-release-dist`退出0；wheel118文件/175408字节，SHA256 fcf28cb61c163c14f00638df3ea7e7ed5bf81cfc009c3ba4b3b7206da27288be；sdist125文件/128550字节，SHA256 2a8aeff227280e715ce8317eb2199ba33918ce7e20299f2f0450b2dea77482c8。新README与project URLs已进入UTF-8 Markdown METADATA，源码版本仍0.1.0.dev0。
- `.venv/bin/python -m twine check --strict`对上述两个发行物均PASSED；actionlint v1.7.12对两份工作流退出0（shellcheck/pyflakes未运行），compileall/pip check/diff检查通过。actionlint只证明本地工作流语法/表达式检查，不等于远端job已执行。
- `.venv/bin/python scripts/validate_candidate.py --wheel /tmp/nyr-tag-release-dist/naiyue_rag-0.1.0.dev0-py3-none-any.whl --expected-version 0.1.0.dev0 --venv /tmp/nyr-tag-preview-01a17887/venv`退出0。全新环境公开索引安装全部运行依赖，pip check无破损；离开源码cwd、-I执行nyr，macOS26.4/arm64/Python3.12.14，原生Chroma/BM25/SQLite，2份文档、revision1、2条证据、9次合成本机模型请求、真实厂商0、权重下载false、进程强杀后重开true。
- 当前执行`version --tag v0.1.0`按预期退出2、release_version_mismatch，不创建标签或上传。真实发布还需确定正式版本/许可证，以及用户配置PyPI/GitHub环境并授权实际发布。

L1：项目介绍、发布文档、Spec、版本工具和两份workflow存在；L2：版本/许可证/同制品/权限门禁是真实实现；L3：本地版本与制品审计、账户无关的安装闭环已运行。GitHub复用job、跨平台runner、真实OIDC、PyPI创建项目及公共安装准确新版本均待远端首发验收，不宣称账户已配置。未提交/push/打标签或上传PyPI；本轮新装Twine仅为构建检查工具，未升级当前开发环境原有SDK；未触碰真实.env/用户配置/知识库。
