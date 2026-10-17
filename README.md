# ASW-SFQS 海运报价整理工具

面向国际海运物流业务的报价维护与检索网页系统，第一版维护青岛港六区域报价。

当前完成 **T01—T07：样本、合同、目录与样式、前后端、数据库、领域规则、私有存储与独立Worker**。网页可查看预置目录，任务状态/取消/重试接口可用；目前可运行文件完整性核验。正式报价数据、上传识别、审核业务接口及导出仍在后续实现。下一步是T08的受控数据迁移。

## 开发入口

- [开发文档](海运报价整理工具-开发文档.md)
- [编码任务计划](海运报价整理工具-V1编码任务计划.md)
- [数据合同与字段字典](docs/T02-数据合同与字段字典.md)
- [目录、样式与迁移说明](docs/T03-目录样式与迁移说明.md)
- [配置与种子维护](config/README.md)
- [安装、启动与验证](docs/T04-工程启动与验证说明.md)
- [数据库设计与迁移](docs/T05-数据库设计与迁移说明.md)
- [T05完成报告](docs/T05-数据层与数据库迁移完成报告.md)
- [领域规则与审核状态](docs/T06-领域规则与状态校验说明.md)
- [T06完成报告](docs/T06-领域校验与状态机完成报告.md)
- [文件存储与Worker](docs/T07-文件存储与后台任务说明.md)
- [T07完成报告](docs/T07-存储与Worker完成报告.md)

## 目录

| 位置 | 内容 |
|---|---|
| `backend/app/domain/` | 共用字段模型、金额日期规则和动态排版 |
| `backend/app/repositories/`、`backend/migrations/` | 数据实体、精确存储、事务、版本快照及显式迁移 |
| `backend/app/storage/`、`backend/workers/` | 私有原件、不可覆盖发布、持久任务、租约和恢复 |
| `backend/app/api/`、`backend/app/core/` | 实际运行的系统接口、本机访问边界和配置 |
| `frontend/` | React + TypeScript + Vite基础工作台 |
| `contracts/` | JSON Schema、OpenAPI、共用TypeScript类型及合成示例 |
| `config/` | 六sheet、18列、295目的地目录、样式与版本差异 |
| `tests/contracts/` | 可公开运行的合成数据合同测试 |
| `tests/template_assets/` | 公开目录排版测试和可选私有样本回放 |
| `tests/fixtures/` | 样本管理说明及工具；真实资料不在Git中 |
| `tools/template_assets/` | 冻结资产的只读提取和配置生成 |
| `scripts/` | Windows安装、开发启动、构建、单地址启动和冒烟检查 |

## 安装与启动

准备Python 3.12或3.13、Node.js 22.12+（推荐24 LTS）和uv。未安装uv时先执行 `python -m pip install uv==0.11.23`。在项目根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1
```

打开 **http://127.0.0.1:5173**。Ctrl+C停止前后端。安装脚本按 `uv.lock` 和 `frontend/package-lock.json`安装，不覆盖已有.env，不重置或导入报价。

构建后由一个地址同时提供网页与API：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-local.ps1
```

打开 **http://127.0.0.1:8000**。两种模式都只监听本机，切换前先停止前一种。MODEL_API_KEY等配置可留空；当前识别尚未启用，不伪造成功结果。

## 运行检查

首次显式初始化数据库结构（不会导入目录或报价）：

```powershell
uv run --frozen python -m backend.app.repositories.cli upgrade
uv run --frozen python -m backend.app.repositories.cli status
uv run --frozen python -m backend.app.repositories.cli check
```

网页启动不自动升级；已有已知版本升级先备份。操作方式与恢复步骤见[迁移说明](docs/T05-数据库设计与迁移说明.md)。

T07起升级到0003_jobs后，在另一个终端启动独立Worker：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/worker.ps1
```

Worker不自动建库。文件核验演示、任务接口、取消和恢复方式见[Worker说明](docs/T07-文件存储与后台任务说明.md)；当前未注册OCR或正式报价写入处理器。

```powershell
uv run --frozen python -m unittest discover -s tests/system -v
uv run --frozen python -m unittest discover -s tests/database -v
uv run --frozen python -m unittest discover -s tests/domain -v
uv run --frozen python -m unittest discover -s tests/workers -v
uv run --frozen python -m unittest discover -s tests/contracts -v
uv run --frozen python -m unittest discover -s tests/template_assets -v
uv run --frozen python contracts/generate.py --check
npm run format:check --prefix frontend
```

单地址服务运行时可验证实际页面和API：

```powershell
uv run --frozen python scripts/smoke.py --expect-frontend
```

公开克隆不需要真实费率即可运行合同和目录测试。没有私有样本时，私有回放测试明确标记为跳过；不能把跳过写成真实样本验证成功。

## 数据与公开版本

本仓库公开内容包括代码、无价目录、样式配置、合成测试数据和脱敏开发文档。公开文档中的金额仅为说明示例，不可当作实际报价或真实样本的金额金标准。

真实报价Excel、来源图片、OCR转录、精确校验值、迁移候选及脱敏前文档保留在本地私有目录，已被Git忽略。`outputs/`包含历史文件与临时脚本，也不上传。需要回放私有样本的开发者应另行取得受控样本包，说明见 [测试资料](tests/fixtures/README.md)。

正式Excel始终保持六个区域sheet及18列；价格来源未编码留空，有效期保留完整年份并显示月日，同港不同船司/服务/码头或有效期允许存在多个报价。
