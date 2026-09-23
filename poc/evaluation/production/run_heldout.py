import argparse, datetime, hashlib, importlib.util, json, sys, time
from pathlib import Path
import httpx
ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent/'poc/catalog.py').is_file())
sys.path.insert(0,str(ROOT))
from poc.catalog import Catalog
spec=importlib.util.spec_from_file_location('independent_cases',ROOT/'poc/evaluation/independent/run_cases.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:8765');p.add_argument('--output',default='heldout-http.json');p.add_argument('--source-root');a=p.parse_args()
folder=Path(__file__).parent
SOURCE=Path(a.source_root).resolve() if a.source_root else ROOT
catalog=Catalog(SOURCE/'.poc/public/poc-catalog.json')
cases=json.loads((folder/'heldout_cases.json').read_text())['cases']
paths=list((SOURCE/'poc').glob('*.py'))+[SOURCE/'.poc/public/poc-catalog.json']
def hashes():return {str(x.relative_to(SOURCE)):hashlib.sha256(x.read_bytes()).hexdigest() for x in paths}
before=hashes();rows=[]
with httpx.Client(timeout=35) as client:
 for case in cases:
  now=time.monotonic();entry={'id':case['id'],'family':case['family'],'request':case['request'],'expect':case['expect']}
  try:
   r=client.post(a.base_url+'/api/search',json=case['request']);entry['http_status']=r.status_code;r.raise_for_status();payload=r.json();entry['response']=payload
   check=mod.assess(case,payload,catalog)
   if payload.get('total')!=len(payload.get('results',[])):
    check['errors'].append('total does not equal returned result length')
   ids=[x['id'] for x in payload.get('results',[])]
   if len(set(ids))!=len(ids):check['errors'].append('duplicate result IDs')
   cat=case['expect'].get('category_or_parent')
   if cat and any(cat not in [catalog.by_id[x['id']]['category'],catalog.by_id[x['id']]['parent_category']] for x in payload.get('results',[])):check['errors'].append('category or parent constraint violated')
   check['scenario_check_passed']=not check['errors'];entry['assessment']=check
  except Exception as exc:entry['assessment']={'scenario_check_passed':False,'errors':[repr(exc)]}
  entry['seconds']=round(time.monotonic()-now,3);rows.append(entry)
  print(case['id'],'PASS' if entry['assessment']['scenario_check_passed'] else 'FLAG',entry['seconds'],[x['title'] for x in entry.get('response',{}).get('results',[])],entry['assessment'].get('errors'),flush=True)
  (folder/a.output).write_text(json.dumps({'started_source_sha256':before,'cases':rows},indent=2)+'\n')
after=hashes()
output={'reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'started_source_sha256':before,'finished_source_sha256':after,'sources_frozen':before==after,'catalog_count':len(catalog.packages),'case_sha256':hashlib.sha256((folder/'heldout_cases.json').read_bytes()).hexdigest(),'cases':rows}
(folder/a.output).write_text(json.dumps(output,indent=2)+'\n')
print('Passed',sum(x['assessment']['scenario_check_passed'] for x in rows),'/',len(rows),'source frozen',before==after)
