"""Check frozen fixture integrity and independent T01 business invariants.

This checks source/annotation assets, not production OCR accuracy or application behavior.
No model call, production import, Excel editing, or online lookup is performed.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[3]
PACK=ROOT/'tests/fixtures/private/t01-v1'
RESULTS=[]

def load(relative):return json.loads((PACK/relative).read_text(encoding='utf-8'))
def check(code,title,predicate,detail=''):
    RESULTS.append({'id':code,'title':title,'passed':bool(predicate),'detail':detail})
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    manifest=load('manifest.json')
    private_values=load('expected/private-validation-values.json')
    check('F01','One template and three quotation sources',len(manifest['sources'])==4 and sum(s['role']=='QUOTATION' for s in manifest['sources'])==3)
    for n,s in enumerate(manifest['sources'],2):
        frozen=PACK/s['fixture_path'];original=Path(s['original_path'])
        check(f'F{n:02}','Frozen hash '+s['source_id'],sha(frozen)==s['sha256'] and frozen.stat().st_size==s['bytes'])
        if original.exists():check(f'S{n:02}','Original unchanged '+s['source_id'],sha(original)==s['sha256'])
        if frozen.suffix=='.xlsx':
            with zipfile.ZipFile(frozen)as z:check(f'Z{n:02}','XLSX ZIP integrity '+s['source_id'],z.testzip() is None)
    private_paths=[str((PACK/s['fixture_path']).relative_to(ROOT)).replace('\\','/') for s in manifest['sources']]
    git=subprocess.run(['git','check-ignore','--stdin'],input='\n'.join(private_paths)+'\n',text=True,capture_output=True,cwd=ROOT)
    check('F06','All frozen business originals excluded by Git',git.returncode==0 and len(git.stdout.strip().splitlines())==4)
    json_paths=list(PACK.rglob('*.json'))
    for p in json_paths:json.loads(p.read_text(encoding='utf-8'))
    check('F07','All fixture JSON readable',len(json_paths)>=10)
    t=load('expected/template.expected.json')
    expected_names=['美洲航线','欧洲航线','美加航线','亚洲航线','非洲航线','中东印巴航线']
    expected_counts=[69,61,27,68,49,21]
    check('T01','Six sheets and exact order',[s['name']for s in t['sheets']]==expected_names)
    check('T02','295 destinations and per-sheet counts',len(t['destinations'])==295 and [s['destination_count']for s in t['sheets']]==expected_counts)
    expected_headers=['航线','国家英文名','国家中文名','英文港口名','中文港口名','船公司','20GP','40GP','40HQ','货币','船期','航程天数','途径路径','价格来源','备注（注意事项）','有效期起','有效期止','费用口径']
    check('T03','All 18 headers exact',all(s['headers']==expected_headers for s in t['sheets']))
    grid=load('extracted/template-v8.grid.json')
    price_cells=[];notes=[];sources=[]
    for s in grid['sheets']:
        for address,c in s['cells'].items():
            col=re.sub(r'\d','',address);row=int(re.sub(r'\D','',address))
            if row<3:continue
            if col in ['G','H','I']and c['value']is not None:price_cells.append(address)
            if col=='O'and c['value']:notes.append(address)
            if col=='N'and c['value']:sources.append(address)
    check('T04','Template contains no quotes, old remarks or source codes',not price_cells and not notes and not sources)
    destkeys=[(x['country_en'],re.sub(r'[^A-Z0-9]','',x['destination_en'].upper()))for x in t['destinations']]
    check('T05','No exact normalized country/name duplicates',len(destkeys)==len(set(destkeys)))
    check('T06','All destination contexts restored',all(x['route_group']and x['country_en']and x['country_zh']and x['destination_zh']for x in t['destinations']))
    e=load('expected/evergreen.expected.json');cs=e['candidates'];byrow={}
    for c in cs:byrow.setdefault(c['source_row'],[]).append(c)
    check('E01','51 Qingdao candidates / 47 raw codes / 45 physical rows',len(cs)==51 and len({c['destination_code_raw']for c in cs})==47 and len(byrow)==45)
    check('E02','One-cell multiple codes expanded',len(byrow[18])==6 and len(byrow[19])==2)
    check('E03','Three equal-price duplicate extras',len(e['same_price_duplicates'])==3 and {x['code']for x in e['same_price_duplicates']}=={'MYTIW','MYMJC','MYSVM'})
    check('E04','48 after merge; 45 historical matches plus 3 pending',len(e['deduplicated_candidate_keys'])==48 and e['counts']['historical_applied']+len(e['historical_pending_codes'])==48)
    check('E05','LABUAN different prices preserved',len(e['price_conflicts'])==1 and e['price_conflicts'][0]['code']=='MYLZZ' and {(c['prices']['20GP'],c['prices']['40GP'])for c in cs if c['destination_code_raw']=='MYLZZ'}=={tuple(x) for x in private_values['labuan_price_pairs']})
    check('E06','MYKOK source amounts never auto-corrected',all([c['prices']['20GP'],c['prices']['40GP']]==private_values['mykok_prices']for c in cs if c['destination_code_raw']=='MYKOK'))
    check('E07','40HQ provenance distinct from explicit source',all(c['prices']['40GP']==c['prices']['40HQ']and c['price_provenance']['40HQ']=='RULE_DERIVED_SHARED_40_FOOT'for c in cs))
    check('E08','Missing main currency and unspecified date basis preserved',all(c['currency']is None and c['validity_basis']=='UNSPECIFIED'for c in cs))
    check('E09','Six Rizhao destinations kept out of Qingdao',len(e['rizhao'])==6 and all(c['origin']=='RIZHAO'and not c['auto_sum_feeder']for c in e['rizhao']))
    check('E10','Six missing dictionary codes; four historical external mappings',set(e['codes_absent_from_source_dictionary'])=={'IDJBK','IDPJA','THSGZ','IDMKR','IDXID','JPNHA'}and len(e['historical_external_mappings'])==4)
    check('E11','VNHCM not auto-mapped to CAT LAI',e['historical_pending_codes']==['VNHCM','IDXID','JPNHA'])
    source=load('extracted/evergreen-20261018.grid.json')['sheets'][0]['cells']
    check('E12','All source amounts match raw OOXML cells',all(c['prices']['20GP']==source['B'+str(c['source_row'])]['value']and c['prices']['40GP']==source['C'+str(c['source_row'])]['value']for c in cs))
    m=load('expected/med.expected.json');mr=m['records'];priced=[r for r in mr if r['disposition']=='PRICED_CANDIDATE']
    check('M01','40 image rows / 39 priced / 1 excluded',len(mr)==40 and len(priced)==39 and mr[30]['destination_raw']=='Chornomorsk'and all(v is None for v in mr[30]['prices'].values()))
    check('M02','117 explicitly read container amounts retained',sum(v is not None for r in mr for v in r['prices'].values())==117)
    alex=[r for r in priced if r['destination_raw'].startswith('Alexandria')]
    check('M03','ABU QIR and TMT separate prices',[r['prices']['20GP']for r in alex]==private_values['alex_20gp']and [r['prices']['40GP']for r in alex]==private_values['alex_40gp'])
    check('M04','No inferred carrier/main currency',all(r['carrier']is None and r['currency']is None for r in priced))
    check('M05','Update date independent of validity',m['document_context']['source_updated_on']=='2026-09-30'and all(r['valid_from']=='2026-10-15'and r['valid_to']=='2026-10-31'for r in mr))
    exception=next(r for r in m['conditions']if r['id']=='MED_HWCS_EXCEPTION')
    check('M06','HWCS exception exactly first five ports',exception['destination_rows']==[1,2,3,4,5]and sum('MED_HWCS_EXCEPTION'in r['condition_refs']for r in priced)==5)
    unclear=next(r for r in m['conditions']if r['id']=='MED_ADDON_UNCLEAR')
    check('M07','Unclear add-on code not converted into a fact',unclear['charge_code']is None and unclear['scope']is None and not unclear['auto_total'])
    s=load('expected/sitc.expected.json');sr=s['rows'];exp=s['expanded_destination_service_records']
    check('C01','64 image rows / 75 expanded destination-service records',len(sr)==64 and len(exp)==75)
    check('C02','All four price profiles separate',all(set(r['profiles'])=={'LEFT_QUOTE','G_KEY_ACCOUNT_SETTLEMENT','R_QUOTE','R_SETTLEMENT'}for r in sr))
    check('C03','No invented Qingdao origin or main currency',all(r['origin']is None and r['currency_main']is None for r in sr))
    check('C04','ETD and cross-month dates from title context',all(r['validity_basis']=='ETD'and r['valid_from']=='2026-10-26'and r['valid_to']=='2026-11-01'for r in sr))
    check('C05','58 reference cells retained unevaluated',len(s['reference_expressions'])==58 and all(x['amount']is None and x['resolution']=='UNRESOLVED_DO_NOT_COMPUTE'for x in s['reference_expressions']))
    check('C06','Reference baseline and G values never substituted',sr[0]['profiles']['LEFT_QUOTE']['20GP']['amount']==private_values['sitc_baseline_and_g'][0]and sr[0]['profiles']['G_KEY_ACCOUNT_SETTLEMENT']['first']['amount']==private_values['sitc_baseline_and_g'][1])
    check('C07','OSAKA/KOBE and HAKATA/MOJI split, source shared',sr[0]['destination_tokens']==['OSAKA','KOBE']and sr[1]['destination_tokens']==['HAKATA','MOJI'])
    thai=[r for r in sr if r['destination_tokens']==['BANGKOK (PAT)']]
    check('C08','Two Thailand services must coexist',len(thai)==2 and {r['transit_days']for r in thai}=={14,9}and {r['mode_raw']for r in thai}=={'中转','直达'})
    hcm=[r for r in sr if '胡志明('in r['destination_raw']]
    check('C09','CAT LAI / PHUOC AN terminal distinction',len(hcm)==2 and hcm[0]['destination_tokens']!=hcm[1]['destination_tokens'])
    check('C10','YANGON AWPT / MITT terminal distinction',sr[53]['destination_tokens']==['YANGON (AWPT)']and sr[54]['destination_tokens']==['YANGON (MITT)']and sr[53]['profiles']['LEFT_QUOTE']['20GP']['amount']==private_values['sitc_yangon_20gp'][0]and sr[54]['profiles']['LEFT_QUOTE']['20GP']['amount']==private_values['sitc_yangon_20gp'][1])
    check('C11','Literal 1 values retained without zero conversion',sr[12]['profiles']['LEFT_QUOTE']['20GP']['amount']=='1'and sr[8]['profiles']['G_KEY_ACCOUNT_SETTLEMENT']['first']['amount']=='1')
    check('C12','Alternative transit 11/17 not coerced to promised range',sr[35]['transit_raw']=='11/17'and sr[35]['transit_days']is None and sr[35]['transit_kind']=='ALTERNATIVES_UNBOUND')
    check('C13','Pair strings do not assume container mapping',sr[10]['profiles']['R_QUOTE']['value']['kind']=='PAIR_UNASSIGNED'and sr[10]['profiles']['R_QUOTE']['value']['amount']is None)
    check('C14','Nepal in India source block explicitly flagged','COUNTRY_GROUP_CONFLICT_NEPAL_IN_INDIA_BLOCK'in sr[63]['issues'])
    check('C15','Dash missing price differs from zero',sr[63]['profiles']['R_QUOTE']['value']['kind']=='MISSING'and sr[63]['profiles']['R_QUOTE']['value']['amount']is None)
    check('C16','周三/六 shorthand includes Wednesday/Saturday',sr[11]['weekdays_suggested']==[3,6,7])
    check('C17','T01 does not grant SITC business approval',all(r['business_review']=='PENDING'for r in sr))
    check('C18','All referenced shared notes exist',all(ref in s['remarks']for r in sr for ref in r['remark_refs']))
    evidence_ids={x['source_id']for x in manifest['sources']}
    check('G01','Candidate evidence points to registered immutable originals',all(r['evidence']['source_id']in evidence_ids for r in cs+mr+sr))
    failed=[r for r in RESULTS if not r['passed']]
    report={'fixture_id':'t01-v1','validated_on':'2026-10-17','scope':'FIXTURE_INTEGRITY_AND_ANNOTATION_INVARIANTS_ONLY_NOT_PRODUCTION_MODEL_EVALUATION','checks_total':len(RESULTS),'checks_passed':len(RESULTS)-len(failed),'checks_failed':len(failed),'checks':RESULTS}
    (PACK/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items()if k!='checks'},ensure_ascii=False))
    if failed:
        print(json.dumps(failed,ensure_ascii=False,indent=2));raise SystemExit(1)

if __name__=='__main__':main()
