"""Independent controlled local HTTP capacity/rate/operational profile test."""
import asyncio,collections,datetime,json,os,statistics,subprocess,sys,threading,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import httpx
ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent/'poc/catalog.py').is_file());DIR=Path(__file__).resolve().parent;SNAP=ROOT;PY=sys.executable
state={'requests':0,'active':0,'max_active':0};lock=threading.Lock()
class KB(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  with lock:
   state['requests']+=1;state['active']+=1;state['max_active']=max(state['max_active'],state['active'])
  try:
   time.sleep(.8);data=b'{"results":[]}';self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  except (BrokenPipeError,ConnectionResetError):pass
  finally:
   with lock:state['active']-=1
kb=ThreadingHTTPServer(('127.0.0.1',8772),KB);threading.Thread(target=kb.serve_forever,daemon=True).start()
procs=[];logs=[];out={'reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Local controlled HTTP experiment only; not production throughput certification.','phases':[]}
def launch(port,**changes):
 env=os.environ.copy();env.pop('ARM_KB_API_TOKEN',None);env.update({'ARM_SEARCH_PUBLIC_ORIGIN':'https://dashboard.example','ARM_SEARCH_SERVE_STATIC':'false','ARM_KB_SEARCH_URL':'http://127.0.0.1:8772','ARM_SEARCH_MAX_INFLIGHT':'2','ARM_SEARCH_KB_MAX_INFLIGHT':'2','ARM_SEARCH_KB_DEADLINE':'0.15','ARM_SEARCH_REQUESTS_PER_MINUTE':'1000','PYTHONUNBUFFERED':'1'});env.update(changes)
 path=DIR/f'operations-{port}.log';f=path.open('w');logs.append((f,path))
 proc=subprocess.Popen([PY,'-m','poc.serve','--port',str(port)],cwd=SNAP,env=env,stdout=f,stderr=subprocess.STDOUT);procs.append(proc)
 for _ in range(100):
  try:
   r=httpx.get(f'http://127.0.0.1:{port}/api/ready',headers={'Host':'dashboard.example'},timeout=.2)
   if r.status_code==200:return
  except httpx.HTTPError:pass
  time.sleep(.05)
 raise RuntimeError('Local profile failed startup')
async def burst():
 async with httpx.AsyncClient(base_url='http://127.0.0.1:8773',headers={'Host':'dashboard.example','Origin':'https://dashboard.example'},limits=httpx.Limits(max_connections=50),timeout=10) as c:
  async def one(i):
   t=time.monotonic();r=await c.post('/api/search',json={'query':'vector databases'});data=r.json();return {'status':r.status_code,'seconds':round(time.monotonic()-t,4),'mode':data.get('mode'),'has_notice':bool(data.get('notices')),'retry_after':r.headers.get('retry-after')}
  rows=await asyncio.gather(*(one(i) for i in range(30)))
  out['phases'].append({'name':'30_simultaneous_requests_max_inflight_2','results':rows,'status_counts':dict(collections.Counter(r['status'] for r in rows)),'latency_p50':statistics.median(r['seconds'] for r in rows),'latency_p95':sorted(r['seconds'] for r in rows)[28],'max_provider_active':state['max_active']})
  await asyncio.sleep(1)
  r=await c.post('/api/search',json={'query':'Qdrant'});out['phases'].append({'name':'recovery_after_slow_provider','status':r.status_code,'mode':r.json().get('mode'),'titles':[p['title'] for p in r.json().get('results',[])]})
try:
 launch(8773);asyncio.run(burst())
 launch(8774,ARM_SEARCH_REQUESTS_PER_MINUTE='2',ARM_KB_SEARCH_URL='http://127.0.0.1:9')
 rate=[]
 with httpx.Client(base_url='http://127.0.0.1:8774',headers={'Host':'dashboard.example'},timeout=5) as c:
  for i in range(3):
   r=c.post('/api/search',headers={'X-Forwarded-For':f'198.51.100.{i+1}'},json={'query':'Qdrant'});rate.append({'status':r.status_code,'retry_after':r.headers.get('retry-after')})
  health=c.get('/api/ready');docs=c.get('/api/docs');out['phases'].append({'name':'rate_limit_ignores_untrusted_forwarded_ip','requests':rate,'readiness_after_limit':health.status_code,'production_docs_status':docs.status_code})
 out['provider_observations']=dict(state)
finally:
 for proc in procs:proc.terminate()
 for proc in procs:
  try:proc.wait(timeout=5)
  except subprocess.TimeoutExpired:proc.kill();proc.wait()
 for f,path in logs:f.close()
 kb.shutdown();kb.server_close()
 out['log_privacy']={path.name:{'raw_query_present':'Qdrant' in path.read_text() or 'vector database' in path.read_text(),'sample':path.read_text()[:1200]} for f,path in logs}
 (DIR/'operations-final.json').write_text(json.dumps(out,indent=2)+'\n')
 print(json.dumps(out,indent=2))
