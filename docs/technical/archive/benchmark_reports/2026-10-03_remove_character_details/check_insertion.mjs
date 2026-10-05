import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const run = new URL('./', import.meta.url);
const source = name => fs.readFileSync(new URL('candidate/' + name, run), 'utf8');
const character = source('anima_character_selector.js');
const start = character.indexOf('    async function buildValidatedSelection()');
const end = character.indexOf("    footer.style.flexWrap = 'wrap';", start);
const original = '(character:1.2), blue hair,\n ribbon, ';
const item = {id:'qa-character',shared:true,tags:original,detail_tags:'EXTRA_MUST_NOT_BE_INSERTED'};
const target = {value:'original target'};
let changed = false;
const context = vm.createContext({isClosed:false, getSelectedCharacterItems:()=>[item], selectedCharacters:new Set([item.id]),
    tagsWidget:target,structuredClone,assertPromptTarget(){},fetchOfficialCharacterData(){},
    async validateSharedPromptSelection(kind,items){assert.equal(kind,'character');assert.equal(items.length,1);if(changed)target.value='edited while validating';}});
vm.runInContext(character.slice(start,end),context);
assert.equal(await vm.runInContext('buildValidatedSelection()',context),original);
changed=true;
await assert.rejects(vm.runInContext('buildValidatedSelection()',context),/目标正文已变化/);

const pending = source('pending_prompts.js');
const readStart = pending.indexOf('    async function read(item,sharedReads,selected)');
const readEnd = pending.indexOf('    const included=',readStart);
const kinds=['character','clothing','pose','background','artist','style_quality'];
const fresh = {...item,_semantic:{binding:'qa-binding',disposition:'reviewed',manual_search_eligible:true,usage:'positive',content_type:'fragment'}};
const queueContext=vm.createContext({animaKinds:new Set(kinds),URLSearchParams,fetch:async()=>({ok:true,json:async()=>({success:true,items:[fresh],lookup:[fresh]})})});
vm.runInContext(pending.slice(readStart,readEnd),queueContext);
for(const kind of kinds){
    queueContext.entry={provider:'anima',kind,sourceId:item.id,details:true};
    const result=await vm.runInContext('read(entry,new Map(),[entry])',queueContext);
    assert.equal(result.text,original,kind);
    assert.equal(result.binding,'qa-binding');
}
const result={passed:true,checks:['direct character insertion preserves main prompt bytes and ignores extras',
    'changed-target guard still rejects stale writes','all six pending source types preserve main prompt bytes',
    'old character pending details flag no longer appends extras'],production_data_writes:0};
fs.writeFileSync(new URL('insertion_checks.json',run),JSON.stringify(result,null,2));
console.log(JSON.stringify(result));
