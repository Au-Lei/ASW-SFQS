"""Freeze supplied T01 sources byte-for-byte; never overwrite a different fixture."""
from pathlib import Path
import hashlib
import json
import shutil
import stat
import zipfile
import xml.etree.ElementTree as ET
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / 'tests/fixtures/private/t01-v1'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
SOURCES = [
    ('template-v8', 'TEMPLATE', '青岛港海运报价模板_v8_清理核对版.xlsx', 'qingdao_template_v8.xlsx'),
    ('evergreen-20261018', 'QUOTATION', '青岛-东南亚 (40).xlsx', 'evergreen_20261018.xlsx'),
    ('sitc-20261026', 'QUOTATION', '98773338c1395a98291ba7bc4f7e5ad0.png', 'sitc_20261026.png'),
    ('med-20261015', 'QUOTATION', '47b9f8f1d224a9b3e0f75dc240c7b1e0.png', 'med_20261015.png'),
]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_xlsx(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        ss = []
        if 'xl/sharedStrings.xml' in z.namelist():
            ss = [''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]
        rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        targets = {e.attrib['Id']: e.attrib['Target'] for e in rels}
        sheets = []
        book = ET.fromstring(z.read('xl/workbook.xml'))
        for sh in book.findall('m:sheets/m:sheet', NS):
            rid = sh.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            target = targets[rid]
            xml_path = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            root = ET.fromstring(z.read(xml_path))
            cells = {}
            for c in root.findall('m:sheetData/m:row/m:c', NS):
                val = c.find('m:v', NS)
                raw = val.text if val is not None else None
                if c.attrib.get('t') == 's' and raw is not None:
                    value = ss[int(raw)]
                elif c.attrib.get('t') == 'inlineStr':
                    node = c.find('m:is', NS)
                    value = ''.join(node.itertext()) if node is not None else None
                else:
                    value = raw
                formula = c.find('m:f', NS)
                if value is not None or formula is not None:
                    cells[c.attrib['r']] = {'value': value, 'type': c.attrib.get('t', 'n'), 'style_index': c.attrib.get('s'), 'formula': formula.text if formula is not None else None}
            sheets.append({'name': sh.attrib['name'], 'xml_path': xml_path, 'cells': cells, 'merges': [e.attrib['ref'] for e in root.findall('m:mergeCells/m:mergeCell', NS)]})
        return {'date1904': book.find('m:workbookPr', NS).attrib.get('date1904', '0') if book.find('m:workbookPr', NS) is not None else '0', 'sheets': sheets}

def main():
    raw = FIXTURE / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    (FIXTURE / 'extracted').mkdir(exist_ok=True)
    (FIXTURE / 'expected').mkdir(exist_ok=True)
    (FIXTURE / 'evidence').mkdir(exist_ok=True)
    manifest = {'fixture_id': 't01-v1', 'schema_version': 't01.fixture.1', 'frozen_on': '2026-10-17', 'timezone': 'Asia/Shanghai', 'annotation_method': 'assistant manual transcription + direct OOXML extraction; business approval tracked separately', 'sources': []}
    for source_id, role, name, target in SOURCES:
        source = Path.home() / 'Desktop' / name
        before = sha(source)
        dest = raw / target
        if dest.exists():
            assert sha(dest) == before, f'Refusing to overwrite changed fixture: {dest}'
        else:
            shutil.copy2(source, dest)
        assert before == sha(dest) == sha(source), f'Copy/source checksum mismatch: {name}'
        dest.chmod(stat.S_IREAD)
        item = {'source_id': source_id, 'role': role, 'original_name': name, 'original_path': str(source), 'fixture_path': 'raw/' + target, 'bytes': dest.stat().st_size, 'sha256': before}
        if dest.suffix == '.xlsx':
            grid = read_xlsx(dest)
            (FIXTURE / 'extracted' / (source_id + '.grid.json')).write_text(json.dumps(grid, ensure_ascii=False, indent=2), encoding='utf-8')
            item['sheets'] = [s['name'] for s in grid['sheets']]
        else:
            with Image.open(dest) as im:
                item['dimensions_px'] = list(im.size)
                if source_id.startswith('sitc'):
                    w, h = im.size
                    for i in range(5):
                        top = max(0, int(h*i/5)-60)
                        bottom = min(h, int(h*(i+1)/5)+60)
                        crop = im.crop((0, top, w, bottom))
                        crop.save(FIXTURE / 'evidence' / f'sitc-band-{i+1}.png')
                        item.setdefault('inspection_crops', []).append({'path': f'evidence/sitc-band-{i+1}.png', 'box_px': [0, top, w, bottom]})
        manifest['sources'].append(item)
    (FIXTURE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'fixture': str(FIXTURE), 'sources': [{k:v for k,v in s.items() if k in ['source_id','bytes','sheets','dimensions_px','sha256']} for s in manifest['sources']]}, ensure_ascii=False))

if __name__ == '__main__':
    main()
