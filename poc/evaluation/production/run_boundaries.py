"""Read-only local HTTP boundary probes; no public load or access tokens."""
import argparse,datetime,json,time
from pathlib import Path
import httpx
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:8765');p.add_argument('--host');p.add_argument('--output',default='boundary-http.json');a=p.parse_args()
headers={'Host':a.host} if a.host else {}
rows=[]
def check(label,method,path,expected,**kw):
 started=time.monotonic()
 try:
  h=dict(headers);h.update(kw.pop('headers',{}))
  r=httpx.request(method,a.base_url+path,headers=h,timeout=20,**kw)
  # Save only response/status metadata, never submitted bodies or credentials.
  rows.append({'id':label,'http_status':r.status_code,'expected_statuses':expected,'passed':r.status_code in expected,'response':r.text[:600],'cache_control':r.headers.get('cache-control'),'content_type':r.headers.get('content-type'),'request_id':r.headers.get('x-request-id'),'seconds':round(time.monotonic()-started,3)})
 except Exception as e:rows.append({'id':label,'passed':False,'exception':repr(e),'seconds':round(time.monotonic()-started,3)})
 print(rows[-1],flush=True)
check('health','GET','/api/health',[200])
check('readiness','GET','/api/ready',[200])
check('host-rejected','POST','/api/search',[400],headers={'Host':'attacker.invalid'},json={'query':'Qdrant'})
check('origin-rejected','POST','/api/search',[403],headers={'Origin':'https://attacker.invalid'},json={'query':'Qdrant'})
check('declared-large-body','POST','/api/search',[413],content=b' '*9000,headers={'Content-Type':'application/json'})
def chunks():
 for _ in range(10):yield b' '*1000
check('chunked-large-body','POST','/api/search',[413],content=chunks(),headers={'Content-Type':'application/json'})
check('malformed-json','POST','/api/search',[400,422],content=b'{"query":',headers={'Content-Type':'application/json'})
check('invalid-utf8','POST','/api/search',[400,422],content=b'{"query":"\xff"}',headers={'Content-Type':'application/json'})
check('deep-json','POST','/api/search',[400,422],content=('['*1100+'0'+']'*1100).encode(),headers={'Content-Type':'application/json'})
check('oversized-query','POST','/api/search',[422],json={'query':'x'*501})
check('object-query','POST','/api/search',[422],json={'query':{'nested':'value'}})
check('invalid-license','POST','/api/search',[422],json={'query':'database','filters':{'license':'magic'}})
check('array-root','POST','/api/search',[422],json=[{'query':'Qdrant'}])
check('null-root','POST','/api/search',[422],content=b'null',headers={'Content-Type':'application/json'})
check('unknown-api','GET','/api/does-not-exist',[404])
check('server-file-inaccessible','GET','/poc/server.py',[404])
check('dotfile-inaccessible','GET','/.env',[404])
(folder:=Path(__file__).parent).joinpath(a.output).write_text(json.dumps({'reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'base_url':a.base_url,'cases':rows},indent=2)+'\n')
print('Expected status observed:',sum(r['passed'] for r in rows),'/',len(rows))
