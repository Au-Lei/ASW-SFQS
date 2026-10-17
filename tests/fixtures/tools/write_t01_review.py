"""Build a readable private review and an explicit unresolved-information register."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[3]
PACK=ROOT/'tests/fixtures/private/t01-v1'
def load(p):return json.loads((PACK/p).read_text(encoding='utf-8'))
def cell(v):return str(v if v is not None else '—').replace('|','\\|').replace('\n',' ')

def main():
    issues=[]
    def issue(key,source,description,blocks,resolution,evidence):
        issues.append({'id':key,'source_id':source,'state':'UNRESOLVED_OR_LABELLED_HISTORICAL_REPLAY','description':description,'affected_actions':blocks,'expected_handling':resolution,'evidence':evidence,'business_confirmed_by_this_task':False})
    issue('EG-CURRENCY','evergreen-20261018','主价币种未注明',['PRICE_COMPARISON_AS_KNOWN_CURRENCY'],'保留null；局部驳船USD不向主价扩展','POL青岛!B2:C48、D40、A51')
    issue('EG-LABUAN','evergreen-20261018','MYLZZ两组不同报价',['AUTO_OVERWRITE'],'保留冲突；历史选择为两价并存，不默取最低/最后一条','POL青岛!A18:C21')
    issue('EG-GAP','evergreen-20261018','MYKOK价差较大',['AUTO_CORRECTION'],load('expected/private-validation-values.json')['mykok_resolution'],'POL青岛!A16:C16')
    issue('EG-UNMAPPED','evergreen-20261018','IDXID、JPNHA未可靠映射',['AUTO_DESTINATION_MATCH'],'代码保留；不猜港口；不能当标准UNLOCODE硬配','POL青岛!A47:C48')
    issue('EG-TERMINAL','evergreen-20261018','VNHCM仅泛胡志明，未明确CAT LAI',['AUTO_TERMINAL_MATCH'],'维持历史待匹配，可后续人工指定港区','POL青岛!A30:C30、代码表A18:D18')
    issue('EG-RIZHAO','evergreen-20261018','日照起运及驳船费与青岛不等价',['APPLY_TO_QINGDAO','AUTO_TOTAL'],'独立保存6目的地，不能自动加驳船费成为青岛价','POL青岛!A40:D40、A51')
    issue('MED-IDENTITY','med-20261015','船公司、主价币种未注明',['AUTO_CARRIER_MATCH','PRICE_COMPARISON_AS_KNOWN_CURRENCY'],'均保存null；不由FAK或附加费美元推定','原图标题/价格表/脚注')
    issue('MED-ADDON','med-20261015','add-on费用代码5SH/SSH字形及适用范围不明',['AUTO_CHARGE_CALCULATION'],load('expected/private-validation-values.json')['med_addon_resolution'],'图下第二条脚注')
    issue('MED-HWCS','med-20261015','五港HWCS N/A与全表超重规则需保留适用关系',['AUTO_CHARGE_CALCULATION'],'按五港例外保存，不将N/A解释成所有附加费全免','右上合并备注和底部HWCS脚注')
    issue('SITC-ORIGIN','sitc-20261026','图上未明确青岛起运',['APPLY_TO_QINGDAO'],'起运港null；等待明确人工上下文或来源补充','图标题与表头')
    issue('SITC-PROFILE','sitc-20261026','四个价格口径的业务用途未确定',['AUTO_PRICE_SELECTION','AUTO_DEDUPLICATION'],'保留LEFT/G/R报价/R结算；不替用户挑成本价或客户价','四组价格列的表头')
    issue('SITC-CURRENCY','sitc-20261026','LSS有USD，主价未明确币种',['PRICE_COMPARISON_AS_KNOWN_CURRENCY'],'主价null，LSS独立；不自动加LSS','主价列与LSS列')
    issue('SITC-EXPRESSION','sitc-20261026','58个基价引用单元格',['AUTO_PRICE_CALCULATION'],'金额null；保留引用和增量，确认同口径/服务/币种/柜型后才可解算','参考价清单reference_expressions')
    issue('SITC-INCLUSION','sitc-20261026','含、含BY、含LSS、不含的费用范围不统一',['ALL_IN_PRICE_LABEL'],'保留原文，不编BY含义，不标统一全包价','全表价格值后缀及备注')
    issue('SITC-CONTAINERS','sitc-20261026','黄色列柜型及R双值含义未显式标明',['AUTO_CONTAINER_MAPPING_YELLOW_COLUMNS'],'左侧40GP/HC有明确列名；G/R列保持原始位置和待确认对应','主表和黄色价格区表头')
    issue('SITC-SCHEDULE','sitc-20261026','多服务、多目的地与备选航程未完全绑定',['PROMISED_SAILING_OR_TRANSIT'],'2/3、1/4、11/17保留备选；没有证据不逐项配对','第1、2、36行')
    issue('SITC-LOW','sitc-20261026','釜山和仙台G列出现1',['AUTO_CORRECTION'],'保留1并提示，不能改0/空白或补1000','第9、13行')
    issue('SITC-NEPAL','sitc-20261026','Nepal(Birgunj)位于印度块',['AUTO_COUNTRY_INHERITANCE'],'国别继承冲突；国家和业务分组分别确认','第64行及左侧印度合并国家块')
    issue('SITC-WEIGHT','sitc-20261026','重量阈值/双金额/含皮口径不完全明示',['AUTO_CHARGE_CALCULATION'],'保留原文，不自行把24/26或27/32绑定柜型或推断包含端点','LSS/备注列相关合并块')
    (PACK/'review-items.json').write_text(json.dumps({'fixture_id':'t01-v1','items':issues,'note':'T01 freezes facts and unknowns; it does not ask for or grant a new production import approval.'},ensure_ascii=False,indent=2),encoding='utf-8')
    e=load('expected/evergreen.expected.json');m=load('expected/med.expected.json');s=load('expected/sitc.expected.json')
    lines=['# T01 私有样本核对预览','','以下是原件核读与初版标准答案，不是正式报价表。T01没有导入价格。未知、冲突与表达式保持可见。','','## 长荣：51条青岛展开记录','','| 原行 | 原代码 | 源字典目的地 | 20GP | 40GP | 40HQ（规则补齐） | 提示 |','|---|---|---|---:|---:|---:|---|']
    for r in e['candidates']:
        lines.append('| '+' | '.join(map(cell,[r['source_row'],r['destination_code_raw'],(r['source_dictionary']or{}).get('en'),r['prices']['20GP'],r['prices']['40GP'],r['prices']['40HQ'],'；'.join(r['issues'])]))+' |')
    lines+=['','数量：51展开，3条同价重复，48个报价版本；历史45已应用+3待匹配。日照另6条，不加驳船费。','','### 日照原文目的地','','| 目的地原文 | 20尺原价 | 40尺原价 | 起运港 |','|---|---:|---:|---|']
    for r in e['rizhao']:lines.append('| '+' | '.join(map(cell,[r['destination_raw'],r['prices_raw']['20_foot'],r['prices_raw']['40_foot'],'RIZHAO']))+' |')
    lines+=['','## 地中海：40行/39条有价','','币种和船公司均未明确；有效期10-15—10-31，底层年份2026。','','| 图行 | 原分区 | 目的地 | 20GP | 40GP | 40HQ | 处理 |','|---|---|---|---:|---:|---:|---|']
    for r in m['records']:lines.append('| '+' | '.join(map(cell,[r['visual_row'],r['source_region_raw'],r['destination_raw'],r['prices']['20GP'],r['prices']['40GP'],r['prices']['40HQ'],r['disposition']]))+' |')
    lines+=['','## SITC：64行，四口径分别保留','','有效期原文10.26—11.1，标题2026，依据ETD。未明确起运港和主价币种。下表为原始价格文字；G/R用途和柜型未替用户选择。含、BY及参考价增量均不展开为确定含费总价。','','| 图行 | 国家/服务组 | 目的地原文 | 左20GP | 左40GP/HC | G第一列 | G第二列 | R报价 | R结算 | 班期 | 方式 | 航程 |','|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in s['rows']:
        pf=r['profiles'];vals=[r['visual_row'],r['country_group_raw'],r['destination_raw'],pf['LEFT_QUOTE']['20GP']['raw'],pf['LEFT_QUOTE']['40GP_HC']['raw'],pf['G_KEY_ACCOUNT_SETTLEMENT']['first']['raw'],pf['G_KEY_ACCOUNT_SETTLEMENT']['second']['raw'],pf['R_QUOTE']['value']['raw'],pf['R_SETTLEMENT']['value']['raw'],r['schedule_raw'],r['mode_raw'],r['transit_raw']]
        lines.append('| '+' | '.join(map(cell,vals))+' |')
    lines+=['','### SITC共用说明（保持原文）','','| 标记 | 原文 |','|---|---|']
    for key,raw in s['remarks'].items():lines.append('| '+cell(key)+' | '+cell(raw)+' |')
    lines+=['','## 待确认事项','','| ID | 来源 | 问题 | 保存/处理方式 |','|---|---|---|---|']
    for r in issues:lines.append('| '+' | '.join(map(cell,[r['id'],r['source_id'],r['description'],r['expected_handling']]))+' |')
    (PACK/'样本核对预览.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'review_items':len(issues),'preview_lines':len(lines)},ensure_ascii=False))

if __name__=='__main__':main()
