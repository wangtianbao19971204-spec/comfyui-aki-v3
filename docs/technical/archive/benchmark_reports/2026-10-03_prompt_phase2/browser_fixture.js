(async () => {
    const {app} = await import('/scripts/app.js');
    if (app.graph._nodes.length) throw new Error('Create a blank unsaved QA workflow first');
    const node=LiteGraph.createNode('WeiLinPromptUI'); app.graph.add(node);
    node.title='QA neutral positive';
    const widget=node.widgets.find(w=>w.name==='positive');widget.value='mountain path';
    const branch={id:'phase2-qa',label:'中性隔离验收',nodeIds:[node.id],stages:[]};
    app.graph.extra.uap_workbench={activeBranch:branch.id,viewBranch:branch.id,branches:[branch]};
    const make=(id,name,tags,detail_tags='')=>({id,name,name_zh:name,tags,detail_tags,shared:true,post_count:0,source_category:'QA',source:'QA',copyright:'QA',
        _semantic:{binding:id+'-v1',disposition:'reviewed',manual_search_eligible:true,usage:'positive',content_type:'fragment'}});
    const items=[make('qa-traveler','QA 成年旅人','adult traveler, blue coat'),make('qa-hiker','QA 成年徒步者','adult hiker, green jacket'),make('qa-details','QA 附加特征','adult explorer','silver hair')];
    const real=window.fetch;
    window.__phase2={app,node,widget,branch,items,blocked:[],copied:[]};
    window.fetch=function(input,options){
        const url=String(input?.url||input),method=String(options?.method||input?.method||'GET').toUpperCase();
        const respond=data=>Promise.resolve(new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}}));
        if(!['GET','HEAD'].includes(method)){window.__phase2.blocked.push({method,url});return respond({success:true});}
        if(url.includes('/anima-tools/shared-prompts'))return respond({enabled:true,items,revision:'qa1'});
        if(url.includes('/anima-tools/favorites'))return respond({character:{groups:[],items:[]}});
        if(url.includes('/prompt_selector/library/index'))return respond({semantic_classes:{character:'角色'},filter_pool:{subcategory:{},subcategory_values:{}}});
        if(url.includes('/prompt_selector/library/revision'))return respond({revision:'qa1'});
        return real.call(this,input,options);
    };
    const open=XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open=function(method,url,...rest){if(!['GET','HEAD'].includes(String(method).toUpperCase())){window.__phase2.blocked.push({method,url});throw new Error('QA blocks writes');}return open.call(this,method,url,...rest);};
    navigator.clipboard.writeText=async text=>{window.__phase2.copied.push(text);};
    window.unifiedDailyControls.render(branch,true);window.unifiedDailyControls.show(true);
    return {isolated:true,nodes:app.graph._nodes.length};
})()
