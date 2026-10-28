# 标签发布与PyPI配置

发布入口是`.github/workflows/publish-pypi.yml`。推送版本标签后，GitHub Actions先验证版本与许可证、构建一次wheel/sdist、用同一wheel完成三平台安装验收和正式回归，再自动上传PyPI；上传后检查公开文件SHA256并从公共PyPI新建环境安装验证。

本页记录0.1.0首发的配置与验证步骤。版本号和项目 MIT 许可证已在源码确定；PyPI账户配置、发布标签和远端流水线仍须按本页逐项核对，不能把本地构建当作公开发布。

## 1. PyPI账户

在[PyPI](https://pypi.org/)注册或登录自己的账户，验证邮箱并启用[两步验证](https://docs.pypi.org/your-account/two-factor-authentication/)，妥善保存恢复码。GitHub用户名和PyPI用户名不必相同。

使用[Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)，无需创建或发送长期PyPI API Token，也无需在GitHub Secrets中保存PYPI_API_TOKEN。PyPI按GitHub工作流的OIDC身份授予短期发布凭据。

## 2. 首次项目：添加pending publisher

如果`naiyue-rag`尚未在你的PyPI账户下创建，进入[账户Publishing](https://pypi.org/manage/account/publishing/)，选择GitHub，填写：

| PyPI字段 | 本项目填写值 |
|---|---|
| PyPI Project Name | `naiyue-rag` |
| Owner | `tlzmw001` |
| Repository name | `naiyue-rag` |
| Workflow name | `publish-pypi.yml` |
| Environment name | `pypi` |

Workflow name只填写文件名，不填`.github/workflows/`前缀，不填页面显示的“Publish to PyPI”。所有字段必须和工作流/仓库实际值一致。

pending publisher会在首次成功上传时创建项目，并转为常规publisher；它不会提前创建项目或预留包名。项目名称是否能注册，以首次上传时PyPI的校验为准。若名称已被占用，需要另行决定包名，不能把404或pending记录当成占名成功。[官方首次建项目说明](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)

如果项目已经属于你，进入该项目的Manage → Publishing，添加相同的GitHub publisher即可，不再填pending项目名。[已有项目配置说明](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)

## 3. GitHub环境

在[仓库Settings → Environments](https://github.com/tlzmw001/naiyue-rag/settings/environments)创建名为`pypi`的环境。

将Deployment branches and tags设为Selected branches and tags，添加**Tag**规则`v*`。不添加普通分支规则。若希望推送标签后全自动发布，保持Required reviewers关闭；自行添加审核人后，发布会等待审批。

工作流只在publish job授予`id-token: write`，其他job仅有`contents: read`。发布job不checkout代码、不执行构建脚本，只下载已验收制品并调用固定提交版本的官方PyPA上传action。账号密码、模型Key和知识库材料都不进入发布配置。

`main`分支push、PR和手动Package validation只执行验证；它们不能触发PyPI上传。发布workflow只有`push.tags: v*`入口。标签流水线目前只负责PyPI；本地 Embedding 模型作为同标签的 GitHub Release 附件单独完成，不能把PyPI上传成功当作完整本地模型交付。

## 4. 首个标签之前

实际发布前需要确定正式版本和项目许可证：

1. `naiyue_rag/_version.py`是唯一版本来源。将其改为要发布的正式版本，标签必须精确对应`vX.Y.Z`，比如源码`0.1.0`对应`v0.1.0`。
2. 核对根目录`LICENSE`与pyproject.toml的`project.license="MIT"`、`project.license-files=["LICENSE"]`一致，并确认两种分发包都包含许可证。
3. 将本次源码、README、配置模板、Spec、测试和工作流一同提交，先让分支CI通过。标签所指commit须已包含在`origin/main`历史中。
4. 核对PyPI publisher与GitHub pypi环境字段，取得本次真实版本的发布授权后，再创建和推送标签。

首版只接受`vX.Y.Z`稳定版标签；预发布标签格式待需要时扩展，不通过重命名文件绕过版本检查。

以下仅演示假设已确定0.1.0、已提交所有修改且CI通过后的操作，不表示当前已经授权或执行：

```sh
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
```

仅在本地创建标签不会触发发布；需要把标签推到GitHub。不要覆盖或强推已有发布标签。

## 5. 标签触发后的流水线

```text
推送vX.Y.Z
  → guard：版本精确匹配、许可证存在、commit属于main历史
  → validate：构建一次、归档审计、Twine、三平台同一wheel验收、正式回归
  → publish：pypi环境 + OIDC，上传已验收的同一wheel/sdist
  → verify-public：核对PyPI文件名/SHA256，从公共PyPI安装并执行CLI/原生闭环
  → model-release：人工核对本地GGUF摘要与许可，创建同标签GitHub Release并附三个模型文件，核对公开下载
```

三平台矩阵为ubuntu-24.04/x86_64、windows-2022/x86_64和macos-15/arm64，Python3.12。只有全部验证job成功才进入publish；当前没有远端CI或OIDC执行证据，文件存在不算发布成功。

发布action固定为PyPA v1.14.3对应的提交`7245906fb61fa33a13554f9d5fb856fe61758086`。不配置password、不使用长期Token，不开启skip-existing。普通CI和标签发布复用同一验证工作流，具体制品名由源码版本生成，不写死候选版本。

## 6. 本地可执行的预检

在新的输出目录构建，避免把旧发行物或其他文件误当成当前发布内容：

```sh
python -m pip install -r requirements-dev.txt
python scripts/release_tools.py version
python -m build --outdir /新的临时目录/dist
```

将上一步输出的version/wheel/sdist字段用于检查：

```sh
python scripts/release_tools.py artifacts --dist /新的临时目录/dist --version 0.1.0
python scripts/inspect_distribution.py --expected-version 0.1.0 /新的临时目录/dist/naiyue_rag-0.1.0-py3-none-any.whl /新的临时目录/dist/naiyue_rag-0.1.0.tar.gz
python -m twine check --strict /新的临时目录/dist/*
```

上述0.1.0为说明参数关系的示例，必须换成`version`命令真实输出，不要求或自动改动当前候选版本。只有准备真实稳定版时才使用`version --tag vX.Y.Z`执行包括许可证在内的发布门禁。

## 7. 成功判据与失败处理

完成发布须同时看到：远端全部验证通过、publish成功、verify-public成功、PyPI准确版本的wheel/sdist与本地SHA256一致、公共pip准确版本安装成功。上传成功但验收失败时，已上传的版本可能已经对外可见，不能报告为“未发布”或假装自动撤回。

OIDC失败先核对owner、repo、workflow文件名、environment及job权限；缺少pending记录时不会自动回退长期Token。若PyPI已有部分或全部文件，先核对文件/摘要及实际发布状态，不删标签或反复覆盖同版本。若publish已成功而verify-public失败，在排查后仅重跑失败验收job；不要重跑上传job来覆盖已有文件。稳定版内容变更需使用新版本号。

TestPyPI是独立服务，账户publisher须另配；当前工作流目标只有正式PyPI，不自动向TestPyPI或其他镜像发布。

## 8. 同标签模型附件与交付完成条件

Python wheel 的 `Requires-Dist` 已声明正式功能所需的 Python 依赖；联网 `pip install naiyue-rag` 会由 pip 解析安装，wheel 不包含第三方依赖文件、Ollama 程序或模型权重。Linux 仍须另装 Ollama。模型附件为 `Qwen3-Embedding-0.6B-Q8_0.gguf`、`Qwen3-Embedding-0.6B-Q8_0.LICENSE.txt`、`qwen3-embedding-0.6b-q8_0.json`，来源、字节数和 SHA-256 见[模型清单](model-assets/qwen3-embedding-0.6b-q8_0.json)。GGUF 文件放在被 Git 忽略的 `dist/model-assets/`，不得加入普通 Git 历史或 Python 分发包。

在首个正式标签的 PyPI 发布和 `verify-public` 均成功后，检查本地附件候选与目标标签，再创建**草稿** GitHub Release。以下命令只作为执行清单；目标仓库、标签、三份附件和不可触碰项在实际上传前再次核对：

```sh
TAG="$(git describe --tags --exact-match HEAD)"
.venv/bin/python - <<'PY'
import hashlib, json
from pathlib import Path
manifest=json.loads(Path('docs/model-assets/qwen3-embedding-0.6b-q8_0.json').read_text())
root=Path('dist/model-assets')
model=root/manifest['asset_name']
assert model.stat().st_size==manifest['size_bytes']
with model.open('rb') as source:
    assert hashlib.file_digest(source,'sha256').hexdigest()==manifest['sha256']
for name in (manifest['license_file'],'qwen3-embedding-0.6b-q8_0.json'):
    assert (root/name).is_file()
print('model assets verified')
PY
gh release create "$TAG" \
  dist/model-assets/Qwen3-Embedding-0.6B-Q8_0.gguf \
  dist/model-assets/Qwen3-Embedding-0.6B-Q8_0.LICENSE.txt \
  dist/model-assets/qwen3-embedding-0.6b-q8_0.json \
  --repo tlzmw001/naiyue-rag --verify-tag --draft --generate-notes
```

检查草稿所指的提交、三份附件的大小与摘要后，再发布草稿并从公开下载地址复核 GGUF SHA-256。若缺失附件或摘要不符，保持草稿状态，不宣称发布完成；PyPI 上已上传的版本也不能撤回或覆盖。`gh release` 操作不会由当前 GitHub Actions 自动执行；标签本身只触发 PyPI 流水线。Linux 用户按[本地 Embedding 操作说明](local-embedding.md)从同标签 Release 下载模型，导入 Ollama 后再审计和摄取。
