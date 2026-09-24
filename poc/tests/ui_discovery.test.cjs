const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.textContent = ''; this.value = 'all'; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, callback) { this[name] = callback; }
  set innerHTML(value) { throw new Error('Source text must not be assigned to innerHTML'); }
}
function setup() {
  const elements = new Map();
  const document = {createElement: tag => new Element(tag), getElementById: id => {
    if (!elements.has(id)) elements.set(id,new Element('div'));
    return elements.get(id);
  }};
  const context = vm.createContext({document, URL, setInterval: () => {}, fetch: async () => ({ok:true,json:async()=>({running:false,summary:null})})});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../discovery/web/app.js'),'utf8') + '\n globalThis.testApi = {safeLink,renderFindings};',context);
  return {api:context.testApi,elements,document};
}
function flatten(e) { return [e,...e.children.flatMap(flatten)]; }
function finding(overrides={}) { return {name:'sample/tool',source:'github',status:'supported',scope:'Release v1 only',reason:'Linux Arm64 artifact advertised',checked_at:'2026-09-24T10:00:00Z',next_check_at:'2026-10-01T10:00:00Z',selection_reason:'Example',recommended_action:'Human review',evidence:[], ...overrides}; }

test('evidence URLs reject ambiguous authority, javascript and unrelated hosts',()=>{
  const {api} = setup();
  for (const url of ['javascript:alert(1)','https://evil.example\\@github.com/a/b','https://github.com@evil.example/a/b','https://github.com:444/a/b','https://evil.example/a/b','http://github.com/a/b']) assert.equal(api.safeLink(url),false,url);
  for (const url of ['https://github.com/a/b','https://api.github.com/repos/a/b','https://hub.docker.com/_/redis']) assert.equal(api.safeLink(url),true,url);
});
test('untrusted source and AI text remain text, unsafe evidence gets no anchor',()=>{
  const {api,elements} = setup();
  const attack='<img src=x onerror=alert(1)>';
  api.renderFindings({findings:[finding({name:attack,evidence:[{kind:'release_notes',url:'javascript:alert(1)',excerpt:attack}],ai_review:{status:'completed',note:attack}})]});
  const nodes = flatten(elements.get('findings'));
  assert.ok(nodes.some(n=>n.textContent===attack));
  assert.equal(nodes.filter(n=>n.tagName==='a'||n.tagName==='img'||n.tagName==='script').length,0);
});
test('unknown filter retains historical date label and never calls it unsupported',()=>{
  const {api,elements,document} = setup();
  document.getElementById('filter').value='unknown';
  api.renderFindings({findings:[finding()],retained_findings:[finding({name:'saved/repo',status:'unknown',historical:true})]});
  const nodes = flatten(elements.get('findings'));
  assert.equal(elements.get('findings').children.length,1);
  assert.ok(nodes.some(n=>n.textContent==='Unclear / unknown'));
  assert.ok(nodes.some(n=>n.textContent.startsWith('Historical · last checked')));
  assert.equal(nodes.some(n=>n.textContent==='unsupported'),false);
});
test('gap scopes precede supported scopes without changing the finding',()=>{
  const {api,elements} = setup();
  api.renderFindings({findings:[finding(),finding({name:'sample/gap',status:'gap',scope:'image:v1 only'})]});
  const first=flatten(elements.get('findings').children[0]);
  assert.ok(first.some(n=>n.textContent==='sample/gap'));
  assert.ok(first.some(n=>n.textContent==='image:v1 only'));
});
test('empty filtered result is explicit instead of showing unrelated packages',()=>{
  const {api,elements,document} = setup();
  document.getElementById('filter').value='gap';
  api.renderFindings({findings:[finding()]});
  assert.match(elements.get('findings').children[0].textContent,/No findings in this view/);
});
