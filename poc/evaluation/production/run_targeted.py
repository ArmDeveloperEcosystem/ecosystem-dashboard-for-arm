"""Controlled provider fixtures over real catalog records; not live claims."""
import argparse,datetime,json,socket,sys,time
from pathlib import Path
ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent/'poc/catalog.py').is_file())
p=argparse.ArgumentParser();p.add_argument('--source-root',default=str(ROOT));p.add_argument('--slow-body-port',type=int);p.add_argument('--output',default='targeted-final.json');a=p.parse_args();SRC=Path(a.source_root).resolve();sys.path.insert(0,str(SRC))
from poc.catalog import Catalog
from poc.search_service import SearchService
from poc.server import create_app
from poc.runtime import RuntimeConfig
from fastapi.testclient import TestClient
catalog=Catalog(SRC/'.poc/public/poc-catalog.json');rows=[]
def run(id,q,title,snippet,required=(),forbidden=()):
 hit={'title':title,'url':('https://developer.arm.com/ecosystem-dashboard/linux/?package=redis' if title.startswith('Redis ') else 'https://learn.arm.com/reviewer-controlled-fixture/'),'snippet':snippet}
 payload=SearchService(catalog,transport=lambda _: {'results':[hit]}).search(q)
 names={x['title'] for x in payload['results']};errors=[f'missing {n}' for n in required if n not in names]+[f'unexpected {n}' for n in forbidden if n in names]
 rows.append({'id':id,'query':q,'controlled_hit':hit,'required_titles':required,'forbidden_titles':forbidden,'response':payload,'errors':errors,'passed':not errors});print(id,'PASS' if not errors else 'FLAG',sorted(names),errors)
run('trailing-negation','encryption tools','RabbitMQ security','Encryption is not supported by RabbitMQ.',forbidden=['RabbitMQ'])
run('contracted-negation','encryption tools','RabbitMQ security',"RabbitMQ doesn't support encryption.",forbidden=['RabbitMQ'])
run('positive-evidence','encryption tools','RabbitMQ security','RabbitMQ has encryption enabled.',required=['RabbitMQ'])
run('compound-false','multi-tenant databases','Redis architecture','Redis supports multiple engines and tenant metadata.',forbidden=['Redis'])
run('compound-positive','multi-tenant databases','Redis architecture','Redis is a multi-tenant in-memory database.',required=['Redis'])
run('protocol-operational-mention','load balancer for TCP and HTTP applications','Install NGINX','Allow HTTP traffic through the VM firewall. Run sudo ufw allow 80/tcp.',required=['Haproxy'],forbidden=['NGINX'])
run('protocol-positive','load balancer for TCP and HTTP applications','NGINX networking','NGINX provides TCP and HTTP load balancing.',required=['NGINX','Haproxy'])
hit={'title':'Qdrant vector database','url':'https://learn.arm.com/qdrant/\ud800','snippet':'Qdrant is a vector database.'};service=SearchService(catalog,transport=lambda _: {'results':[hit]})
with TestClient(create_app(service=service,config=RuntimeConfig(site_dir=SRC/'.poc/public',serve_static=False)),base_url='http://127.0.0.1',raise_server_exceptions=False) as client:
 r=client.post('/api/search',json={'query':'vector databases'});rows.append({'id':'malformed-provider-url-serialization','http_status':r.status_code,'response':r.json(),'passed':r.status_code==503 and r.json()=={'detail':'Search is temporarily unavailable.'}})
if a.slow_body_port:
 started=time.monotonic()
 with socket.create_connection(('127.0.0.1',a.slow_body_port),timeout=10) as conn:
  conn.sendall(b'POST /api/search HTTP/1.1\r\nHost: dashboard.example\r\nContent-Type: application/json\r\nContent-Length: 18\r\nConnection: close\r\n\r\n{"query":')
  reply=conn.recv(4096).decode();status=reply.splitlines()[0];rows.append({'id':'slow-actual-http-body','status_line':status,'seconds':round(time.monotonic()-started,3),'passed':'408' in status})
out={'reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Synthetic controlled KB fixtures establish parser and attribution behavior, not facts about the named projects. ActualHTTP slow body and ASGI provider serialization separate.','cases':rows};Path(__file__).with_name(a.output).write_text(json.dumps(out,indent=2)+'\n');print('Passed',sum(x['passed'] for x in rows),'/',len(rows))
