# ASW-SFQS 海运报价整理工具

面向国际海运物流业务的报价维护与检索网页系统，第一版维护青岛港六区域报价。

当前完成 **T01—T03：样本基准、数据合同、港口目录和模板配置**。前后端应用骨架、数据库、识别服务和导出接口尚未实现；下一步是T04。

## 开发入口

- [开发文档](海运报价整理工具-开发文档.md)
- [编码任务计划](海运报价整理工具-V1编码任务计划.md)
- [数据合同与字段字典](docs/T02-数据合同与字段字典.md)
- [目录、样式与迁移说明](docs/T03-目录样式与迁移说明.md)
- [配置与种子维护](config/README.md)

## 目录

| 位置 | 内容 |
|---|---|
| `backend/app/domain/` | 共用字段模型、金额日期规则和动态排版 |
| `contracts/` | JSON Schema、OpenAPI、共用TypeScript类型及合成示例 |
| `config/` | 六sheet、18列、295目的地目录、样式与版本差异 |
| `tests/contracts/` | 可公开运行的合成数据合同测试 |
| `tests/template_assets/` | 公开目录排版测试和可选私有样本回放 |
| `tests/fixtures/` | 样本管理说明及工具；真实资料不在Git中 |
| `tools/template_assets/` | 冻结资产的只读提取和配置生成 |

## 运行当前检查

使用Python 3.11或更新版本，在虚拟环境中安装当前合同依赖：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements-contracts.txt
.venv/Scripts/python contracts/generate.py --check
.venv/Scripts/python -m unittest discover -s tests/contracts -v
.venv/Scripts/python -m unittest discover -s tests/template_assets -v
```

公开克隆不需要真实费率即可运行合同和目录测试。没有私有样本时，私有回放测试明确标记为跳过；不能把跳过写成真实样本验证成功。

## 数据与公开版本

本仓库公开内容包括代码、无价目录、样式配置、合成测试数据和脱敏开发文档。公开文档中的金额仅为说明示例，不可当作实际报价或真实样本的金额金标准。

真实报价Excel、来源图片、OCR转录、精确校验值、迁移候选及脱敏前文档保留在本地私有目录，已被Git忽略。`outputs/`包含历史文件与临时脚本，也不上传。需要回放私有样本的开发者应另行取得受控样本包，说明见 [测试资料](tests/fixtures/README.md)。

正式Excel始终保持六个区域sheet及18列；价格来源未编码留空，有效期保留完整年份并显示月日，同港不同船司/服务/码头或有效期允许存在多个报价。
