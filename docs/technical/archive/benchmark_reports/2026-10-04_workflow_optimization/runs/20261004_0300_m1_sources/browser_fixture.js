(async()=>{
    if(app.graph._nodes.length)throw Error('Create a blank acceptance workflow first');
    const kinds=['character','clothing','pose','background','artist','style_quality'];
    const texts={character:'adult traveler',clothing:'blue coat',pose:'standing',background:'quiet forest',artist:'watercolor artist',style_quality:'watercolor'};
    const labels={character:'验收角色',clothing:'验收服装',pose:'验收姿势',background:'验收背景',artist:'验收画师',style_quality:'验收画风'};
    const records=Object.fromEntries(kinds.map(kind=>[kind,[{id:'m1b-'+kind,name:labels[kind],name_zh:labels[kind],tags:texts[kind],detail_tags:'',shared:true,post_count:0,source_category:'QA',source:'QA',copyright:'QA',category:'QA',
        _semantic:{binding:kind+'-v1',disposition:'reviewed',manual_search_eligible:true,usage:'positive',content_type:'fragment'}}]]));
    const local=Object.fromEntries(Object.keys(localStorage).filter(k=>/^(anima-|uw-)/.test(k)).map(k=>[k,localStorage.getItem(k)]));
    const draft=sessionStorage.getItem('uw-pending-draft');sessionStorage.removeItem('uw-pending-draft');
    for(const k of Object.keys(localStorage).filter(k=>/^anima-/.test(k)))localStorage.removeItem(k);
    const originalFetch=window.fetch;
    window.__m1b={originalFetch,local,draft,records,requests:[],blocked:[],library:{mix:{prompt:'adult traveler, blur',_semantic:{manual_search_eligible:true,usage:'mixed'}}}};
    const response=data=>new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json','ETag':'m1b-fixture'}});
    window.fetch=async(input,init)=>{
        const u=new URL(typeof input==='string'?input:input.url,location.href),method=String(init?.method||input?.method||'GET').toUpperCase();
        if(u.pathname==='/anima-tools/shared-prompts'){__m1b.requests.push({path:u.pathname,kind:u.searchParams.get('kind')});return response({enabled:true,items:records[u.searchParams.get('kind')]||[],revision:'m1b'});}
        if(u.pathname==='/anima-tools/artist-page'){const body=JSON.parse(init?.body||'{}');return response({success:true,items:body.limit===0?[]:records.artist,lookup:records.artist,total:records.artist.length,catalog_count:records.artist.length,revision:'m1b',tree:[],source_options:[]});}
        if(u.pathname==='/anima-tools/favorites')return response(Object.fromEntries(kinds.map(k=>[k,{groups:[],items:[]}])));
        if(u.pathname==='/prompt_selector/library/prompt'&&__m1b.library[u.searchParams.get('prompt_id')])return response({prompt:__m1b.library[u.searchParams.get('prompt_id')]});
        if(u.pathname==='/prompt_selector/library/index')return response({revision:'m1b',semantic_classes:{},filter_pool:{subcategory:{},subcategory_values:{}}});
        if(u.pathname==='/prompt_selector/library/revision')return response({revision:'m1b'});
        if(u.pathname==='/prompt_selector/prompts/mark_used'){__m1b.requests.push({path:u.pathname,synthetic:true});return response({revision:'m1b'});}
        if(!['GET','HEAD'].includes(method)){__m1b.blocked.push({path:u.pathname,method});return new Response(JSON.stringify({error:'Acceptance blocks mutations'}),{status:403});}
        return originalFetch(input,init);
    };
    const node=LiteGraph.createNode('WeiLinPromptUI');app.graph.add(node);node.title='M1b 验收提示词';
    node.widgets.find(w=>w.name==='positive').value='mountain path';
    const negative=LiteGraph.createNode('CLIPTextEncode');negative.title='M1b 负向';negative.widgets.find(w=>w.name==='text').value='blur';app.graph.add(negative);
    const branch={id:'m1b',label:'中性隔离验收',nodeIds:[node.id,negative.id],stages:[]};
    app.graph.extra.uap_workbench={activeBranch:branch.id,viewBranch:branch.id,branches:[branch]};
    __m1b.node=node;__m1b.branch=branch;
    window.unifiedDailyControls.render(branch,true);window.unifiedDailyControls.show(true);
    return {ready:true,nodes:app.graph._nodes.length};
})()
