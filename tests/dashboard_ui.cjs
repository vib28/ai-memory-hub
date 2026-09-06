// Dependency-free JavaScript unit tests. No browser automation or runtime dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.children=[];this.value='';this.checked=false;this.dataset={};this.textContent='';this.innerHTML='';this.classList={toggle(){}}; }
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children=nodes;this.textContent='';}
  setAttribute() {}
  addEventListener() {}
  showModal() {this.open=true;}
  close() {this.open=false;}
  focus() {this.focused=true;}
}
const elements=new Map();
const document={
  documentElement:{dataset:{}},
  getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},
  createElement(){return new Element();},
  createTextNode(text){return {textContent:text};},
  querySelectorAll(){return [];},
  addEventListener(){},
};
const stored=new Map();
const context=vm.createContext({document,window:{matchMedia:()=>({matches:false})},
  localStorage:{getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value)},
  Option:class {},console});
const code=fs.readFileSync('memory_hub/static/app.js','utf8').replace(/safe\(refresh\);\s*$/,'');
vm.runInContext(code+'\nthis.ui={state,editRelations,markdown,pendingBody,applyTheme};',context);
const {ui}=context;
ui.state.rows=[
  {memory_id:'self',subject:'current',text:'current memory',tags:['work'],kind:'session'},
  {memory_id:'target',subject:'release-plan',text:'Check the launch checklist',tags:['release'],kind:'project',writer:'codex'},
  {memory_id:'second',subject:'writing-style',text:'Prefer short paragraphs',tags:[],kind:'preference',writer:'user'},
];
const element=id=>document.getElementById(id);
(async()=>{
  ui.editRelations({memory_id:'self',tags:[],links:[],source_tags:['claude'],metadata_revision:'rev'});
  assert.equal(element('link-results').children.length,2,'Opening lookup must immediately offer other memories');
  assert.equal(element('tag-results').children.length,3,'Existing tags, including source tags, are discoverable');
  element('link-lookup').value='checklist';
  element('link-lookup').oninput();
  assert.equal(element('link-results').children.length,1);
  assert.match(element('link-results').children[0].innerHTML,/Check the launch checklist/);
  assert.equal(element('link-results').children[0].type,'button','Lookup choices must not submit the dialog');
  await element('link-results').children[0].onclick();
  assert.equal(element('chosen-links').children.length,1);
  assert.equal(element('link-results').children.length,0,'Selected memories are omitted from lookup choices');
  element('tag-lookup').value='new-tag';
  element('tag-lookup').oninput();
  assert.match(element('tag-results').children[0].textContent,/Create tag #new-tag/);
  await element('tag-results').children[0].onclick();
  assert.match(element('chosen-tags').children[0].textContent,/#new-tag/);
  assert.ok(element('editor').open,'Selecting a lookup option must leave the dialog open');
  element('tag-lookup').value='<script>';
  element('tag-lookup').oninput();
  assert.match(element('tag-results').children[0].textContent,/Use letters/);
  const rendered=ui.markdown('### Learned\n- <img src=x onerror=alert(1)>\n- **Readable**');
  assert.ok(!rendered.includes('<img'));
  assert.match(rendered,/<h3>Learned<\/h3><ul>/);
  assert.match(rendered,/<strong>Readable<\/strong>/);
  assert.match(ui.pendingBody({payload:{type:'session',data:{investigated:['Read files'],next_steps:['Test']}}}),/<li>Read files<\/li>/);
  assert.match(ui.pendingBody({payload:{type:'pattern',project_fact_text:'Fact',preference_rule_text:'Rule'}}),/Project fact/);
  for(const dark of [false,true])for(const accessible of [false,true]){
    element('dark-mode').checked=dark;element('colorblind-mode').checked=accessible;ui.applyTheme();
    assert.equal(document.documentElement.dataset.theme,(accessible?'colorblind-':'')+(dark?'dark':'light'));
    assert.deepEqual(JSON.parse(stored.get('memory-hub-appearance')),{dark,accessible});
  }
  console.log('Dashboard JavaScript unit tests passed: lookups, renderer, dialog choices, four themes.');
})().catch(error=>{console.error(error);process.exitCode=1;});

