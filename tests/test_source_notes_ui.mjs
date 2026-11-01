import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

class Element {
    constructor(tag) { this.tagName=tag.toUpperCase();this.children=[];this.style={};this.attributes={};this.hidden=false;this.isConnected=true;this._text=''; }
    append(child) { this.children.push(child);child.parentElement=this; }
    replaceChildren(...children) { this.children=[];this._text='';children.forEach(child=>this.append(child)); }
    setAttribute(name,value) { this.attributes[name]=value; }
    set textContent(value) { this._text=String(value);this.children=[]; }
    get textContent() { return this._text+this.children.map(child=>child.textContent).join(''); }
}
globalThis.document={createElement:tag=>new Element(tag)};
const path=new URL('../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/source_notes.js',import.meta.url);
const module=await import('data:text/javascript;base64,'+Buffer.from(await readFile(path,'utf8')).toString('base64'));
const nodes=host=>[host,...host.children.flatMap(nodes)];
const note={title:'示例法典',entry_title:'示例条目',note:'第一行\n<img src=x onerror=alert(1)>',url:'https://novelai.quicktagcloud.com/?c=suozhang&id=sample'};
const response=values=>({ok:true,json:async()=>({source_notes:values})});

test('notes render as read-only literal text, with preserved lines and no prompt pre element',()=>{
    const host=new Element('div');module.renderSourceNotes(host,[note]);
    assert.match(host.textContent,/来源说明/);assert.ok(host.textContent.includes(note.note));
    assert.equal(nodes(host).filter(n=>['PRE','TEXTAREA','INPUT','IMG','SCRIPT'].includes(n.tagName)).length,0);
    assert.ok(nodes(host).some(n=>n.style.whiteSpace==='pre-wrap'));
    const link=nodes(host).find(n=>n.tagName==='A');assert.equal(link.textContent,'查看原站');assert.equal(link.rel,'noopener noreferrer');
});

test('unsafe links and empty notes create no actionable link or stale description',()=>{
    const host=new Element('div');module.renderSourceNotes(host,[{...note,url:'javascript:alert(1)'}]);
    assert.equal(nodes(host).filter(n=>n.tagName==='A').length,0);
    module.renderSourceNotes(host,[]);assert.equal(host.textContent,'');assert.equal(host.hidden,true);
});

test('loader performs only fresh GET and keeps internal identity out of displayed text',async()=>{
    const host=new Element('div');let call;
    const handle=module.mountSourceNotes(host,'internal-resource-id',{request:async(...args)=>{call=args;return response([note]);}});
    await handle.ready;
    assert.equal(call[1].method,'GET');assert.equal(call[1].cache,'no-store');assert.equal(call[1].body,undefined);
    assert.equal(new URL('https://local.test'+call[0]).searchParams.get('resource_id'),'internal-resource-id');
    assert.ok(!host.textContent.includes('internal-resource-id'));assert.ok(!host.textContent.includes('/prompt_selector/'));
});

test('closing aborts an outstanding request and prevents late annotation rendering',async()=>{
    const host=new Element('div');let resolve,signal;
    const handle=module.mountSourceNotes(host,'sample',{request:(_url,options)=>{signal=options.signal;return new Promise(done=>{resolve=done;});}});
    handle.dispose();host.isConnected=false;resolve(response([note]));await handle.ready;
    assert.equal(signal.aborted,true);assert.ok(!host.textContent.includes(note.note));
});

test('lost detail version ignores a completed response without replacing the current host',async()=>{
    const host=new Element('div');let resolve,current=true;
    const handle=module.mountSourceNotes(host,'sample',{isCurrent:()=>current,request:()=>new Promise(done=>{resolve=done;})});
    current=false;host.textContent='新的详情';resolve(response([note]));await handle.ready;
    assert.equal(host.textContent,'新的详情');
});

test('read failure is generic and retry replaces it with fresh source content',async()=>{
    const host=new Element('div');let attempts=0;
    const handle=module.mountSourceNotes(host,'sample',{request:async()=>++attempts===1?{ok:false}:response([note])});
    await handle.ready;assert.equal(host.textContent,'来源说明暂不可读。重试');
    await handle.reload();assert.ok(host.textContent.includes(note.note));assert.ok(!host.textContent.includes('暂不可读'));
});
