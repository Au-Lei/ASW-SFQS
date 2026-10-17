# 青岛V1配置与种子资产

`quotation-columns-v1.json`由T02固化六sheet和18列。`enums-v1.generated.json`从T02领域模型生成，不手工修改。

T03新增：

| 文件 | 用途 |
|---|---|
| `template-qingdao-v1.json` | 六sheet标题、列宽、行高、字体、颜色、冻结、合并/国家空行策略、月日日期格式 |
| `seeds/qingdao-v1.json` | 青岛起运港、6区域、34航线分组、107国家/地区展示项、295目的地；无运价 |
| `migrations/v8-v12-directory-diff.json` | 21新增、1父港不再展示、纳闽双行及3个新增分组的差异 |
| `migrations/t03-inventory.json` | 行数与候选数量对账；不包含价格 |

真实v12副本及84条迁移报价放在Git忽略的 `tests/fixtures/private/t03-v1/`，不能搬进前端静态资源。无价原件复用T01冻结的v8文件，不额外生成一个xlsx副本。

T03资产生成命令（使用含Pydantic2.14.0的Python）：

```powershell
python tools/template_assets/build_t03.py --freeze-v12 "outputs/qingdao-template-v1/青岛港海运报价表_v12_已添加地中海报价.xlsx"
python tools/template_assets/build_t03.py --check
python -m unittest discover -s tests/template_assets -v
```

首次执行先按hash冻结v12，后续可直接运行不带参数的生成命令。冻结副本或锁定清单与来源不一致时拒绝覆盖；需要新版本时创建新资产版本，不能替换旧来源规避校验。`--check`不生成或修改资产；缺少私有原件时仍可运行公开目录及排版测试，私有回放测试会明确跳过。

种子目的地ID用固定namespace的UUIDv5从“国家英文展示名|港口英文展示名”产生，航线不参与目的地ID。只规范Unicode宽度、大小写和连续空格，不删除州省后缀、不模糊合并码头。该算法仅用于首次固定种子ID；目录上线后改名/移组必须保持原ID，不得重跑名称算法更换业务身份。namespace保存在种子文件。

种子不是国际港口代码库，没有自行补UNLOCODE。仅将用户明确的5个内陆点和原名含ICD的1个目的地填写类型；其余289项UNKNOWN表示类型尚未核定，原港名、国别和业务分组均已保留。尤其CAT LAI等明确港区后续需建立父目的地后再转换为TERMINAL，不能先设TERMINAL却没有父节点。码头拆分及类型确认在T08/T13落实，不能因UNKNOWN而合并到泛城市。

`source`是原件hash、sheet和行范围，不能用于生产坐标覆盖。每个目的地的国别数据在种子中完整保存；`baseline_layout`只用于原样排版回放，不是正式记录ID或固定写入坐标。动态导出应使用 `backend/app/domain/template_layout.py` 按实际报价行生成排版，同港多报价不会被删。

模板样式颜色保留OpenXML的8位ARGB；未来工作簿适配器应正确转换到其需要的颜色表示。列宽使用Excel字符单位，行高/字号使用pt。标题34pt行高、表头30pt行高、数据/分隔行23pt行高均来自v8；字号分别为15/10。日期统一设置真实数字日期加mm-dd；金额显示最多4位小数，以匹配T02最大精度，不复制旧文件中的年度日期格式和永久变化高亮。模板保留现有未指定纸张/方向的打印设置，不推测用户打印偏好。

`content_sha256`是去除自身字段后，对JSON按键排序、UTF-8、紧凑分隔序列化的SHA-256。模板还记录种子内容hash。业务数据集快照仍由后续数据库版本维护，不能用这些静态资产hash替代数据集版本。

迁移策略和完整差异解释见 `docs/T03-目录样式与迁移说明.md`。
