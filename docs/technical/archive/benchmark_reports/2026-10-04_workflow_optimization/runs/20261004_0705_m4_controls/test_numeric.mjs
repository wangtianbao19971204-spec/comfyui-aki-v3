import fs from 'node:fs';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('./candidate/uap_daily_controls.js',import.meta.url),'utf8');
const body=source.slice(source.indexOf('    function bindField('),source.indexOf('    function prompt('));
class Element {
 constructor(tag,props={}){this.tagName=tag.toUpperCase();this.children=[];this.type='';this.value='';this.step='';this.min='';this.max='';this.attrs={};Object.assign(this,props);}
 setAttribute(k,v){this.attrs[k]=v;}
 removeAttribute(k){delete this.attrs[k];}
 reportValidity(){return this.checkValidity();}
 checkValidity(){const v=Number(this.value),min=this.min===''?-Infinity:Number(this.min),max=this.max===''?Infinity:Number(this.max);if(this.value===''||!Number.isFinite(v)||v<min||v>max)return false;return this.step==='any'||Math.abs((v-(Number.isFinite(min)?min:0))/Number(this.step)-Math.round((v-(Number.isFinite(min)?min:0))/Number(this.step)))<1e-8;}
}
const el=(tag,text,parent,props={})=>{const e=new Element(tag,props);parent?.children.push(e);return e;};
const commit=(node,w,value)=>{if(w.value===value)return;w.value=value;w.callback?.call(w,value);};
const bind=new Function('el','widgetSource','commitWidget','sync',body+';return bindField;')(el,(node,name)=>({node,widget:node.widgets.find(w=>w.name===name)}),commit,[]);
const cases=[];
function test(name,fn){fn();cases.push(name);}
function field(type,name,value,options,callback,label=name){const w={name,value,options:Object.freeze({...options}),callback};const n={type,widgets:[w]};const c=bind(new Element('div'),n,name,label);return {n,w,c};}
const floatCallback=function(value){if(this.options.round){const p=this.options.precision??0;this.value=Number((Math.round(value/this.options.round)*this.options.round).toFixed(p));}else this.value=value;};
const edit=(c,value)=>{c.value=String(value);c.oninput();c.onchange();};
test('PrimitiveFloat retains 0.35, 0.45, 0.37 and 0.005 without retaining option mutations',()=>{const {w,c}=field('PrimitiveFloat','value',1,{round:.1,precision:1,step2:1,min:-Infinity,max:Infinity},floatCallback,'遮罩降噪');const options={...w.options};assert.equal(c.step,'any');assert.equal(c.min,'');assert.equal(c.max,'');for(const v of [.35,.45,.37,.005,.35]){edit(c,v);assert.equal(w.value,v);assert.deepEqual(w.options,options);}});
test('Native denoise keeps 0.01 constraint and rejects unsupported 0.375',()=>{const {w,c}=field('KSampler','denoise',.35,{round:.01,precision:2,step2:.01,min:0,max:1},floatCallback);assert.equal(c.step,'0.01');edit(c,.37);assert.equal(w.value,.37);edit(c,.375);assert.equal(w.value,.37);assert.equal(c.attrs['aria-invalid'],'true');edit(c,.35);assert.equal(w.value,.35);assert(!c.attrs['aria-invalid']);});
test('Padding uses 8px step, accepts 136 and rejects 129 without silent rounding',()=>{const {w,c}=field('ImagePadForOutpaint','left',128,{step2:8,min:0,max:16384},function(v){this.value=Math.round(v/8)*8;});assert.equal(c.step,'8');edit(c,136);assert.equal(w.value,136);edit(c,129);assert.equal(w.value,136);assert.equal(c.attrs['aria-invalid'],'true');edit(c,128);assert.equal(w.value,128);});
test('Integer steps remain constrained',()=>{const {w,c}=field('KSampler','steps',28,{step2:1,min:1,max:10000},function(v){this.value=Math.round(v);});edit(c,29);assert.equal(w.value,29);edit(c,29.5);assert.equal(w.value,29);edit(c,0);assert.equal(w.value,29);});
test('Blank or nonfinite input cannot commit',()=>{const {w,c}=field('PrimitiveFloat','value',.35,{round:.1,precision:1,step2:1},floatCallback);for(const v of ['',NaN,Infinity]){edit(c,v);assert.equal(w.value,.35);}});
test('Native rounding option restored if callback throws',()=>{const {w,c}=field('PrimitiveFloat','value',.35,{round:.1,precision:1,step2:1},()=>{throw Error('fixture callback error');});c.value='.45';assert.throws(()=>c.oninput(),/fixture callback error/);assert.equal(w.options.round,.1);});
fs.writeFileSync(new URL('./tests.json',import.meta.url),JSON.stringify({passed:true,cases},null,2));console.log(`PASS ${cases.length} targeted numeric cases`);
