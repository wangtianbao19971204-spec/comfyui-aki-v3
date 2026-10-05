import fs from 'node:fs';
import vm from 'node:vm';
const base = new URL('./', import.meta.url);
const index = JSON.parse(fs.readFileSync(new URL('index.json', base), 'utf8'));
const items = JSON.parse(fs.readFileSync(new URL('clothing.json', base), 'utf8')).items;
const nodes = JSON.parse(fs.readFileSync(new URL('dom_categories.json', base), 'utf8'));
const source = fs.readFileSync('G:/ComfyUI-aki-v3/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-anima-tools/js/anima_shared_prompt_data.js', 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const context = vm.createContext({items, nodes, fetch: async () => ({ok: true, json: async () => index})});
vm.runInContext(source, context);
await vm.runInContext('loadSharedLibraryTaxonomy()', context);
const result = vm.runInContext(`(() => {
  const rows = nodes.map(node => ({...node, expected: Number(node.label.match(/(\\d+)$/)[1]), actual: items.filter(item => itemMatchesCategoryFilters(item, new Set([node.key]))).length}));
  const navigation = new Set();
  const sequence = nodes.map(node => {
    activateSharedCategoryNavigationFilter(navigation, node.key);
    return {key:node.key, filters:[...navigation], expected:Number(node.label.match(/(\\d+)$/)[1]), actual:items.filter(item=>itemMatchesCategoryFilters(item,navigation)).length};
  });
  const traits = new Map();
  for (const item of items) {
    const names = new Set([item.source_category,...(item.shared_category_paths||[]).map(p=>p.source_full)].filter(v=>typeof v==='string').flatMap(v=>[v.trim(),...v.split('/').map(p=>p.trim())]));
    for(const trait of item.traits||[]) if(typeof trait==='string' && trait.trim() && !names.has(trait.trim())) traits.set(trait,(traits.get(trait)||0)+1);
  }
  return {total:rows.length,mismatches:rows.filter(x=>x.expected!==x.actual),sequentialMismatches:sequence.filter(x=>x.expected!==x.actual),additionalTraitCount:traits.size,additionalTraits:[...traits].slice(0,12),sourceOptions:buildSharedSourceOptions(items)};
})()`, context);
fs.writeFileSync(new URL('navigation_probe.json', base), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
