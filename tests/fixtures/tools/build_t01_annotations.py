"""T01 annotation pack builder, not a production parser or approved import."""
from pathlib import Path
from collections import Counter, defaultdict
from decimal import Decimal
import json
import re

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / 'tests/fixtures/private/t01-v1'

def load(path):
    return json.loads((PACK / path).read_text(encoding='utf-8'))

def write(name, value):
    (PACK / 'expected' / name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def value(sheet, address):
    return sheet['cells'].get(address,{}).get('value')

def template():
    d=load('extracted/template-v8.grid.json')
    destinations=[]
    sheets=[]
    for sh in d['sheets']:
        route=country_en=country_zh=None
        for i in range(3,151):
            route=value(sh,f'A{i}') or route
            country_en=value(sh,f'B{i}') or country_en
            country_zh=value(sh,f'C{i}') or country_zh
            port=value(sh,f'D{i}')
            if not port:continue
            destinations.append({'fixture_key':f"template-v8:{sh['name']}:D{i}",'sheet':sh['name'],'row':i,'route_group':route,'country_en':country_en,'country_zh':country_zh,'destination_en':port,'destination_zh':value(sh,f'E{i}'),'evidence':{'source_id':'template-v8','sheet':sh['name'],'cell_range':f'A{i}:R{i}'}})
        sheets.append({'name':sh['name'],'title':value(sh,'A1'),'headers':[value(sh,f'{chr(65+i)}2') for i in range(18)],'destination_count':sum(x['sheet']==sh['name'] for x in destinations),'merges':sh['merges']})
    result={'source_id':'template-v8','role':'TEMPLATE_NOT_QUOTE','expected_sheet_count':6,'expected_destination_rows':295,'expected_priced_rows':0,'sheets':sheets,'destinations':destinations}
    write('template.expected.json',result)
    return result

def evergreen():
    d=load('extracted/evergreen-20261018.grid.json');sh,ds=d['sheets']
    lookup={}
    for n in range(2,80):
        code=value(ds,f'A{n}')
        if code:lookup[code]={'en':(value(ds,f'B{n}') or '').strip(),'zh':(value(ds,f'C{n}') or '').strip(),'country':value(ds,f'D{n}'),'dictionary_evidence':{'source_id':'evergreen-20261018','sheet':ds['name'],'cell_range':f'A{n}:F{n}'}}
    candidates=[]
    for n in range(3,49):
        if n==40:continue
        for part,code in enumerate(re.split(r'[\s/]+',value(sh,f'A{n}')),1):
            p20=value(sh,f'B{n}');p40=value(sh,f'C{n}')
            candidates.append({'fixture_key':f'evergreen:r{n}:{part}','source_id':'evergreen-20261018','source_row':n,'destination_code_raw':code,'code_namespace':'SOURCE:EVERGREEN:THIS_FILE','source_dictionary':lookup.get(code),'origin':'QINGDAO','carrier':'EMC','carrier_basis':'USER_PROVIDED_SOURCE_IDENTITY','prices':{'20GP':p20,'40GP':p40,'40HQ':p40},'price_provenance':{'20GP':'EXPLICIT_20_FOOT_HEADER','40GP':'TWO_RATE_RULE_PREVIOUSLY_CONFIRMED','40HQ':'RULE_DERIVED_SHARED_40_FOOT'},'currency':None,'valid_from':'2026-10-18','valid_to':'2026-10-24','validity_basis':'UNSPECIFIED','evidence':{'source_id':'evergreen-20261018','sheet':sh['name'],'cell_range':f'A{n}:C{n}','date_cell':'B1'},'business_review':'HISTORICAL_REPLAY_ONLY_NOT_NEW_APPROVAL','issues':[]})
    bycode=defaultdict(list)
    for c in candidates:bycode[c['destination_code_raw']].append(c)
    duplicates=[];conflicts=[];unique=[];seen={}
    for c in candidates:
        k=(c['destination_code_raw'],c['prices']['20GP'],c['prices']['40GP'])
        if k in seen:duplicates.append({'primary':seen[k]['fixture_key'],'duplicate':c['fixture_key'],'code':k[0]})
        else:unique.append(c);seen[k]=c
    for code,rs in bycode.items():
        if len({tuple(c['prices'].values()) for c in rs})>1:conflicts.append({'code':code,'candidate_keys':[c['fixture_key'] for c in rs],'expected':'PRESERVE_CONFLICT_REQUIRES_CHOICE','historical_choice':'KEEP_BOTH'})
    for c in candidates:
        if c['destination_code_raw']=='MYKOK':c['issues'].append(load('expected/private-validation-values.json')['large_gap_issue_code'])
        if not c['source_dictionary']:c['issues'].append('CODE_NOT_IN_SOURCE_DICTIONARY')
        c['issues'].extend(['CURRENCY_UNKNOWN','VALIDITY_BASIS_UNSPECIFIED'])
    notes=value(sh,'D40');rz=[]
    for n,port in enumerate(['宿霧','達沃','巴達燕','蘇比克','將軍港','卡嘉顏'],1):
        rz.append({'fixture_key':f'evergreen:rizhao:{n}','origin':'RIZHAO','destination_raw':port,'prices_raw':load('expected/private-validation-values.json')['rizhao_prices'],'currency':None,'scope':'OUT_OF_SCOPE_QINGDAO','evidence':{'source_id':'evergreen-20261018','sheet':sh['name'],'cell_range':'A40:D40'},'source_note':notes,'feeder_note':value(sh,'A51'),'auto_sum_feeder':False})
    missing=[c['destination_code_raw'] for c in unique if not c['source_dictionary']]
    historical_mappings=[{'code':'IDJBK','destination':'CIKARANG','basis':'PREVIOUS_SESSION_REVIEWED_MAPPING','not_from_source_dictionary':True},{'code':'IDPJA','destination':'PANJANG','basis':'PREVIOUS_SESSION_REVIEWED_MAPPING','not_from_source_dictionary':True},{'code':'THSGZ','destination':'SONGKHLA','basis':'PREVIOUS_SESSION_REVIEWED_MAPPING','not_from_source_dictionary':True},{'code':'IDMKR','destination':'MAKASSAR','basis':'PREVIOUS_SESSION_REVIEWED_MAPPING','not_from_source_dictionary':True}]
    result={'source_id':'evergreen-20261018','annotation_level':'EXPLICIT_VALUES_AND_LABELLED_HISTORICAL_REPLAY','counts':{'physical_price_rows':46,'qingdao_physical_rows':45,'qingdao_expanded':51,'distinct_codes':47,'duplicate_extras':3,'after_exact_duplicate_merge':48,'historical_applied':45,'historical_pending':3,'rizhao_expanded':6},'candidates':candidates,'deduplicated_candidate_keys':[c['fixture_key'] for c in unique],'same_price_duplicates':duplicates,'price_conflicts':conflicts,'codes_absent_from_source_dictionary':missing,'historical_external_mappings':historical_mappings,'historical_pending_codes':['VNHCM','IDXID','JPNHA'],'pending_reasons':{'VNHCM':'Generic HO CHI MINH does not establish CAT LAI terminal','IDXID':'No reliable source-specific mapping confirmed','JPNHA':'No reliable source-specific mapping confirmed'},'rizhao':rz,'source_dictionary':lookup}
    write('evergreen.expected.json',result)
    return result

def med():
    d=load('expected/med-transcription.json');records=[]
    for n,(region,port,p20,p40,phq) in enumerate(d['rows'],1):
        records.append({'fixture_key':f'med:visual-row:{n}','source_id':d['source_id'],'visual_row':n,'source_region_raw':region,'destination_raw':port,'prices':{k:str(v) if v is not None else None for k,v in zip(['20GP','40GP','40HQ'],[p20,p40,phq])},'currency':None,'carrier':None,'valid_from':d['valid_from'],'valid_to':d['valid_to'],'validity_basis':'UNSPECIFIED','origin_scope_raw':d['origin_scope_raw'],'disposition':'EXCLUDED_STRUCK_OUT_NO_PRICE' if n==31 else 'PRICED_CANDIDATE','requires_business_review':True,'condition_refs':['MED_EXCLUSIONS','MED_ADDON_UNCLEAR','MED_DG']+(['MED_HWCS_EXCEPTION'] if n<=5 else ['MED_HWCS_18_21','MED_HWCS_21_PLUS']),'evidence':{'source_id':d['source_id'],'image':'raw/med_20261015.png','location':f'目的地表第{n}行；顶部有效期；底部脚注','coordinate_precision':'ROW_DESCRIPTION_ONLY'}})
    result={'source_id':d['source_id'],'counts':{'physical_destination_rows':40,'priced_rows':39,'excluded_rows':1},'document_context':{k:d[k] for k in ['title_raw','origin_scope_raw','valid_from','valid_to','validity_basis','source_updated_on','carrier_code','currency_main']},'records':records,'conditions':d['conditions'],'review_state':'HISTORICAL_IMPORT_EXISTS_BUT_THIS_FIXTURE_IS_NOT_A_NEW_APPROVAL','special_expectations':['Keep ABU QIR and TMT as separate terminals','Naples source grouping differs from internal geographical grouping; do not replace master route','N/A is not blanket zero surcharge','Never infer carrier or main currency from surcharge information']}
    write('med.expected.json',result)
    return result

def parse_price(raw):
    if raw is None or raw=='--':return {'raw':raw,'kind':'MISSING','amount':None}
    expression=re.fullmatch(r'(.+?)\+(\d+)(?:/(\d+))?',raw)
    if expression:return {'raw':raw,'kind':'REFERENCE_PLUS_ADDON','amount':None,'base_reference_raw':expression[1],'increment_raw':expression[2] if expression[3] is None else expression[2]+'/'+expression[3],'resolution':'UNRESOLVED_DO_NOT_COMPUTE'}
    if re.fullmatch(r'\d+/\d+',raw):return {'raw':raw,'kind':'PAIR_UNASSIGNED','amount':None,'pair_raw':raw.split('/'),'resolution':'CONTAINER_MAPPING_NOT_EXPLICIT_IN_THIS_COLUMN'}
    literal=re.match(r'^(\d+)(.*)$',raw)
    if literal:return {'raw':raw,'kind':'LITERAL_COMPONENT','amount':literal[1],'inclusion_raw':literal[2] or None,'meaning_of_inclusion':'NEEDS_REVIEW' if literal[2] else None}
    return {'raw':raw,'kind':'UNPARSED','amount':None}

def weekday_suggestions(raw):
    # Expand the explicitly written 周三/六 shorthand; keep service/branch binding raw.
    expanded=re.sub(r'周([一二三四五六日])/(?=[一二三四五六日])',r'周\1/周',raw)
    return sorted(set({'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'日':7}[x] for x in re.findall(r'周([一二三四五六日])',expanded)))

def sitc():
    d=load('expected/sitc-transcription.json');rows=[];expanded=[];expressions=[]
    for n,r in enumerate(d['rows'],1):
        country,pod,p20,p40,schedule,mode,transit,lss,refs,g20,g40,rq,rs,dests=r
        baseline=[parse_price(p20),parse_price(p40)];g=[parse_price(g20),parse_price(g40)]
        issues=['ORIGIN_NOT_STATED','MAIN_CURRENCY_NOT_STATED','PRICE_PROFILE_SELECTION_REQUIRED']
        if any(x['kind']=='REFERENCE_PLUS_ADDON' for x in baseline):issues.append('REFERENCE_PRICE_UNRESOLVED')
        if '/' in transit:issues.append('TRANSIT_ALTERNATIVES_NOT_A_RANGE')
        if 'Nepal' in pod:issues.append('COUNTRY_GROUP_CONFLICT_NEPAL_IN_INDIA_BLOCK')
        if n in [9,13]:issues.append('LOW_OR_ONE_AMOUNT_PRESERVE_NOT_ZERO')
        if n in [49,50]:issues.append('DESTINATION_ABBREVIATION_NEEDS_SCOPED_MAPPING')
        if n in [25,28]:issues.append('TWO_DIFFERENT_DESTINATIONS_SHARE_SOURCE_ROW')
        row={'fixture_key':f'sitc:row:{n}','source_id':d['source_id'],'visual_row':n,'country_group_raw':country,'destination_raw':pod,'destination_tokens':dests,'carrier':'SITC','origin':None,'currency_main':None,'validity_raw':'10.26-11.1','valid_from':'2026-10-26','valid_to':'2026-11-01','year_basis':'DOCUMENT_TITLE_2026','validity_basis':'ETD','schedule_raw':schedule,'weekdays_suggested':sorted(set({'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'日':7}[x] for x in re.findall(r'周([一二三四五六日])',schedule))),'schedule_parse_status':'RAW_PRESERVED_BRANCH_BINDING_NOT_ASSUMED','mode_raw':mode,'transit_raw':transit,'transit_kind':'ALTERNATIVES_UNBOUND' if '/' in transit else 'SINGLE_DAYS','transit_days':int(transit) if transit.isdigit() else None,'lss_raw':lss,'remark_refs':refs,'profiles':{'LEFT_QUOTE':{'columns':['20GP','40GP/HC'],'20GP':baseline[0],'40GP_HC':baseline[1],'currency':None},'G_KEY_ACCOUNT_SETTLEMENT':{'header_raw':'G大客户结算','first':g[0],'second':g[1],'container_mapping':'BY_ALIGNMENT_NEEDS_CONFIRMATION','currency':None},'R_QUOTE':{'header_raw':'R报价','value':parse_price(rq),'container_mapping':'UNCONFIRMED','currency':None},'R_SETTLEMENT':{'header_raw':'R结算','value':parse_price(rs),'container_mapping':'UNCONFIRMED','currency':None}},'issues':issues,'business_review':'PENDING','evidence':{'source_id':d['source_id'],'image':'raw/sitc_20261026.png','location':f'主表第{n}条数据行（标题/表头不计入）','row_band_px_approx':[0,98+(n-1)*40,1539,min(2658,98+n*40)],'coordinate_precision':'APPROXIMATE_MANUAL_BAND_NOT_OCR_EXACT'}}
        row['weekdays_suggested']=weekday_suggestions(schedule)
        rows.append(row)
        for j,dest in enumerate(dests,1):expanded.append({'fixture_key':f'sitc:row:{n}:destination:{j}','source_row_key':row['fixture_key'],'destination_token_raw':dest,'country_group_raw':country,'service_context_raw':schedule,'review_state':'PENDING','inherits_row_fields':True})
        for profile,pairs in [('LEFT_QUOTE',{'20GP':p20,'40GP_HC':p40}),('G_KEY_ACCOUNT_SETTLEMENT',{'first':g20,'second':g40}),('R_QUOTE',{'value':rq}),('R_SETTLEMENT',{'value':rs})]:
            for field,raw in pairs.items():
                parsed=parse_price(raw)
                if parsed['kind']=='REFERENCE_PLUS_ADDON':expressions.append({'source_row_key':row['fixture_key'],'profile':profile,'field':field,**parsed})
    result={'source_id':d['source_id'],'annotation_level':'MANUAL_TRANSCRIPTION_NOT_BUSINESS_APPROVAL','counts':{'physical_price_rows':64,'expanded_destination_service_records':75,'profile_groups':4,'reference_expression_cells_all_profiles':len(expressions)},'document_context':{k:d[k] for k in ['header_raw','carrier_explicit','origin_raw','currency_main_explicit','validity_raw','year_context_raw','validity_basis_explicit']},'rows':rows,'expanded_destination_service_records':expanded,'reference_expressions':expressions,'remarks':d['remarks'],'global_issues':['ORIGIN_NOT_STATED','PRICE_PROFILE_SELECTION_REQUIRED','含/BY/不含的费用范围未定义，不可互相比较或自动合并','LSS的USD只适用LSS，不能推断主运价币种','G/R列身份、柜型含义和是否采购/对客价格待业务确认','参考价公式依赖相同价格口径、服务、有效期、币种和柜型，不自动挑基价','两条泰国服务同港不同航程，不属于应删除的重复价','最后一行Nepal(Birgunj)落在印度组，国家不能无条件继承印度']}
    write('sitc.expected.json',result)
    return result

def main():
    t,e,m,s=template(),evergreen(),med(),sitc()
    summary={'template':{'destinations':len(t['destinations'])},'evergreen':e['counts'],'med':m['counts'],'sitc':s['counts']}
    (PACK/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':main()
