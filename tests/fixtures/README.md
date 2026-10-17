# 开发测试资料

T01于2026-10-17建立第一版样本包：`private/t01-v1/`。

这里的资料用于开发、回归测试和原文核对，不是正式报价数据库。冻结原件和标注答案不会自动获得审核通过状态，也不会写入业务报价表。

## 目录

```text
tests/fixtures/
  README.md
  tools/
    freeze_t01.py              # 原件逐字节复制、hash登记和只读副本
    build_t01_annotations.py   # 整理来源网格、初版结构标注及数量对账
    validate_t01.py            # 校验原件完整性与固定业务不变量
  private/                    # 已加入.gitignore
    t01-v1/
      manifest.json           # 原始路径、原名、SHA-256、大小、图片尺寸
      raw/                    # 一份模板、三份来源；不编辑
      extracted/              # Excel单元格、类型、坐标和合并关系
      evidence/               # SITC人工核读裁片，原图仍在raw
      expected/
        template.expected.json
        evergreen.expected.json
        med-transcription.json
        med.expected.json
        sitc-transcription.json
        sitc.expected.json
      summary.json
      review-items.json       # 来源缺失/歧义及其对未来动作的影响
      validation-report.json
      样本核对预览.md
```

## 使用方式

从项目根目录运行：

```powershell
python tests/fixtures/tools/validate_t01.py
```

校验器只需Python标准库和Git；不需要模型密钥，不发起网络请求，不写正式报价。当前校验数量记录在本机私有包的`validation-report.json`，不能当作生产识别准确率。

重新建立来源副本仅在四份用户指定原件可访问时运行：

```powershell
python tests/fixtures/tools/freeze_t01.py
python tests/fixtures/tools/build_t01_annotations.py
python tests/fixtures/tools/validate_t01.py
```

冻结脚本使用Pillow生成核读裁片；有同名但hash不同的冻结原件时拒绝覆盖。标注构建器依赖已保存的人工核读转录文件，不代表已实现通用OCR或通用报价解析器。

## 冻结与修订规则

- `raw/`是只读副本；原桌面文件未修改。用SHA-256检查复制前后内容一致。
- `*-transcription.json`是逐行核读标注；`*.expected.json`是结构化回放答案。价格口径、费用代码和港口未定时，正确答案可以是明确的未知和待确认状态。
- `fixture_key`是测试记录的稳定定位符，不是正式业务数据库ID；插入网页行、排序或改Excel版式不能改变该定位符的含义。
- 每个价格和共用条件需能回到源单元格或源图行；图片裁片和近似行框不是精确OCR坐标。
- 业务人员后续确认G/R含义、起运港或代码映射时，新建标注修订并保留旧版本。不能为使模型测试通过而删掉疑难样本或偷偷改标准答案。
- 这些文件包含真实报价，整个`private/`被Git忽略。项目协作者需通过受控方式取得本机样本包；公共仓库中的校验器不会包含完整原件或费率答案。
- 精确金额断言另外保存于私有包的 `expected/private-validation-values.json`，公开校验脚本通过读取该文件进行独立固定值校验，不内嵌真实费率。它随私有样本受控交付，不能从合成示例或公开开发文档重建。
- T01没有导入任何正式报价、没有修改模板，也没有实现T02以后的应用功能。

## 后续测试读取约定

先加载`manifest.json`并检查hash，再读取对应expected文件。模型契约与正式数据库模型在T02定义；不要将本阶段的测试辅助结构当作未经评审的生产Schema。

详细完成情况见项目根目录`docs/T01-样本冻结与验收基准完成报告.md`。
