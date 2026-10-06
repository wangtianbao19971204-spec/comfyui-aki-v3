import {app} from '../../scripts/app.js';
import {openTagManager, closeTagManager} from './tag_manager.js';
import {createWidgetInserter, captureSelection, mountInsertionActions} from './prompt_target.js';
import {installResourceActions, listPromptTargets, sourceForTarget} from './resource_actions.js';
import {getReferenceCollections, openReferenceCollections} from './shared_collections.js';
import {mountWorkspace} from './workspace.js';
import {createPendingPrompts} from './pending_prompts.js';
import {installBrowserImportReceiver} from './browser_import.js';
import {mountResourceResults} from './resource_results.js';
import {openNativeSettings} from './native_settings.js';
import {installUiTheme, mountThemeToggle} from './ui_theme.js';
import {installCanvasTheme, mountCanvasThemeSetting} from './canvas_theme.js';
import {toolIdentity, mountFunctionCard, mountFunctionIcon} from './ui_identity.js';
import {mountSelectorTools, openPromptSelector} from './selector_tools.js';

const pages={workspace:'工作区',library:'资料库',models:'模型',gallery:'图库'};
const providers={loras:'LoRA',checkpoints:'基础模型',embeddings:'Embedding','loras/recipes':'模型组合',statistics:'统计'};
// 「Anima 画师」与「基础 Tag」同级：整区入口，条目正文是 @画师名（Anima 插件的写法）。
// 这一区在资料库里是以分类前缀「Anima 画师风格 / 分档」存在的，所以入口用区域名做筛选。
const ANIMA_ARTIST_AREA='Anima 画师风格';
// Krea2 情绪版与 Anima 画师同级：整区入口，条目正文是情绪/风格长句，带 ray_style 预览图。
const KREA2_MOOD_AREA='Krea2 情绪版';
// 画师串与上面两区同级：整区入口，收的是 artist: 词占一半以上、或别名形如 画师串N 的条目。
const ARTIST_STRING_AREA='画师串';
// 共享资料管理器的加载器：旧浮动入口文件已下线，这里成为 window.weilinOpenSharedPresets 的唯一所有者。
let sharedPresetManagerLoad;
async function ensureSharedPresetManagerLoaded() {
    if (typeof window.tbOpenSharedPresetManager === 'function') return true;
    if (!sharedPresetManagerLoad) sharedPresetManagerLoad = (async () => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 8000);
        try {
            const response = await fetch('/weilin/prompt_ui/file/javascript/zz_tb_shared_preset_manager.js', {cache: 'no-store', signal: controller.signal});
            if (!response.ok) throw new Error(`资料库加载失败（HTTP ${response.status}）`);
            const source = await response.text();
            if (typeof window.tbOpenSharedPresetManager !== 'function') {
                window.__tbSharedPresetManagerLoaded = false;
                const script = document.createElement('script');
                script.textContent = source;
                document.head.appendChild(script);
            }
            if (typeof window.tbOpenSharedPresetManager !== 'function') throw new Error('资料库初始化失败，请重试。');
            return true;
        } catch (error) {
            if (controller.signal.aborted) throw new Error('资料库加载超时，请重试。');
            throw error;
        } finally { clearTimeout(timeout); }
    })().finally(() => { sharedPresetManagerLoad = null; });
    return sharedPresetManagerLoad;
}
export async function openSharedPresets(options = {}) {
    await ensureSharedPresetManagerLoaded();
    return window.tbOpenSharedPresetManager(options);
}
const themeShortcuts=['person_count','clothing_accessory','pose_action','background_environment','identity','artist_style','style_medium'];
function element(tag,text,parent,props={}){const node=Object.assign(document.createElement(tag),props);if(text!=null)node.textContent=text;parent?.append(node);return node;}
let current;
let lastPage=localStorage.getItem('uw-last-page')||'';if(!pages[lastPage])lastPage='';
const pendingDraft=[];

export async function openWorkbench(options={}) {
    if(current?.root.isConnected){current.root.hidden=false;await current.open(options);return current;}
    const previousFocus=document.activeElement;
    const root=element('section',null,document.body,{id:'unified-workbench'});
    root.setAttribute('role','dialog');root.setAttribute('aria-label','统一工作台');
    const header=element('header',null,root,{className:'uw-header'});element('strong','统一工作台',header);
    const search=element('input',null,header,{type:'search',placeholder:'跨来源搜索：资料、Tag、模型…'});search.setAttribute('aria-label','跨来源搜索资料、Tag 和模型');search.title='同时搜索资料、基础 Tag 和本机模型；当前页搜索只作用于所在列表。';
    const nav=element('nav',null,root,{className:'uw-nav'});nav.setAttribute('aria-label','主要功能');
    const body=element('div',null,root,{className:'uw-body'});
    const side=element('aside',null,body,{className:'uw-sidebar'}),main=element('main',null,body,{className:'uw-main'});
    const animeIntro=element('div',null,main,{className:'uw-anime-intro'});
    const animeCopy=element('div',null,animeIntro,{className:'uw-anime-copy'});
    const animeEyebrow=element('small','',animeCopy),animeTitle=element('h2','',animeCopy),animeDescription=element('p','',animeCopy);
    const selectorToolHost=element('section',null,main,{className:'uw-selector-tools',hidden:true});
    selectorToolHost.setAttribute('aria-label','六类提示词选择器');
    const sections=Object.fromEntries(Object.keys(pages).map(key=>[key,element('section',null,main,{className:'uw-page',hidden:true})]));
    const utility=element('section',null,main,{className:'uw-page',hidden:true});
    const footer=element('footer',null,root,{className:'uw-footer'});
    element('span','写入目标',footer);
    const targetPicker=element('select',null,footer);targetPicker.setAttribute('aria-label','提示词目标');targetPicker.dataset.uw='prompt-target';
    const direction=element('select',null,footer);direction.setAttribute('aria-label','提示词方向');
    for(const [value,label]of [['unknown','确认正负向'],['positive','正向'],['negative','负向']])element('option',label,direction,{value});
    const status=element('span','',footer,{className:'uw-status'});status.setAttribute('role','status');
    let page='',group='',type='prompts',view='all',theme='',sourceCategory='',subcategory='',query='',provider='loras',modelQuery='',modelFile='',modelFavorites=false,promptId='',tagId='';
    let target=null,targetGraph=null,writer=null,targetSignature='',browseOnlyReason='',closed=false,mounted='',frame=null,restoreGallery=null,galleryNode=null,allowedTargets=null;
    let sidebarVersion=0,searchVersion=0,searchTimer,searchComposing=false,tagState={},results=null,selector=null,restoreSelector=null,utilityCleanup=null,browseReturn=null;
    let themes=[],selectedThemes=[],themeHost=null,updateTargetActions=null,galleryIntent=null,galleryNodes=[],galleryVersion=0,utilityReturnFocus=null,browseState=null;
    let returnTo=null;
    let selectorToolbar;
    // 资料库的筛选池是累积式的：侧边栏点主题是「再加一条」，只有明确取消（点第二次）或点「全部」
    // 才会要求资料库移除/清空，避免切换主题时把池子里已有的条件顶掉。
    let removePoolThemeOnce='',clearPoolOnce=false;
    // 面板回报的“来源/细分类”跟着主题一起存在外壳里，侧边栏再切换时原样带回去，
    // 这样边栏与「更多筛选」不会互相清空对方的选中项。
    root.addEventListener('shared-library-view',event=>{if(page==='library'&&type==='prompts'){group=event.detail.collection||'';theme=event.detail.theme||'';selectedThemes=event.detail.selectedThemes||[];sourceCategory=event.detail.source||'';subcategory=event.detail.subcategory||'';query=event.detail.query||'';view=event.detail.view||'all';themes=event.detail.themes||[];renderThemes();side.querySelectorAll('[data-uw^="group-"]').forEach(item=>item.setAttribute('aria-pressed',String(item.dataset.uw==='group-'+group)));}});
    let feedbackOwner=null;
    const report=(error,owner=null)=>{const text=typeof error==='string'?error:error.message;feedbackOwner=owner;status.textContent=/fetch|network|load failed/i.test(text)?'无法连接服务，请检查 ComfyUI 是否运行后重试；当前草稿保留。':text;};
    report.clear=owner=>{if(feedbackOwner!==owner)return false;feedbackOwner=null;status.textContent='';return true;};
    const componentNotice=element('p','',root,{className:'uw-component-notice',hidden:true});componentNotice.setAttribute('role','status');header.after(componentNotice);
    const componentMessage=element('span','',componentNotice);
    const componentRetryButton=element('button','重新检查',componentNotice,{type:'button'});componentRetryButton.dataset.uw='retry-components';
    componentRetryButton.style.marginLeft='12px';componentRetryButton.onclick=()=>checkComponents(false);
    let componentRequest=null,componentRetryTimer;
    let unavailable=new Map();
    async function checkComponents(autoRetry=true){
        if(closed)return;
        clearTimeout(componentRetryTimer);componentRequest?.abort();
        const request=new AbortController();componentRequest=request;componentRetryButton.disabled=true;
        const timeout=setTimeout(()=>request.abort(),8000);let data;
        try{const response=await fetch('/unified-workbench/status',{cache:'no-store',signal:request.signal});if(!response.ok)throw new Error(`服务返回 ${response.status}`);data=await response.json();if(!Array.isArray(data.modules))throw new Error('状态数据格式异常');if(closed||componentRequest!==request)return;
            unavailable=new Map(data.modules.filter(item=>!item.ready).map(item=>[item.key,item]));
            componentNotice.hidden=!unavailable.size;componentMessage.textContent=[...unavailable.values()].map(item=>item.label+'暂不可用：'+item.error).join(' · ');
        }catch(error){if(closed||componentRequest!==request)return;data=null;componentNotice.hidden=false;
            const reason=request.signal.aborted?'请求超过 8 秒':/服务返回|状态数据/.test(error.message)?error.message:'连接或响应异常';
            componentMessage.textContent=`组件状态暂未确认（${reason}），不代表组件加载失败。可继续使用；${autoRetry?'稍后自动重试，也可立即重新检查。':'请点击“重新检查”。'}`;
            if(autoRetry)componentRetryTimer=setTimeout(()=>void checkComponents(false),2000);
        }
        finally{clearTimeout(timeout);if(!closed&&componentRequest===request)componentRetryButton.disabled=false;}
        const dependencies={fragments:'weilin',tags:'weilin',plans:'weilin','page-models':'lora_manager','page-gallery':'gallery','manage-groups':'weilin',organize:'weilin'};
        for(const [action,key]of Object.entries(dependencies))for(const control of root.querySelectorAll('[data-uw="'+action+'"]')){control.disabled=unavailable.has(key);control.title=unavailable.has(key)?unavailable.get(key).error:'';}
        return data;
    }
    function requireComponent(key){const item=unavailable.get(key);if(item)throw new Error(item.label+'暂不可用：'+item.error);}
    const run=(callback,owner=null)=>async(...args)=>{try{return await callback(...args);}catch(error){report(error,owner);}};
    const button=(label,key,callback,parent=side)=>{const b=element('button',label,parent,{type:'button'});b.dataset.uw=key;b.onclick=run(callback,key==='run'?'run-controls':null);return b;};
    const undoResource=button('撤销本次写入','undo-resource',()=>{const success=writer?.undoLast?.();undoResource.hidden=true;report(success?'已撤销本次写入。':'目标已变化，无法撤销旧操作。');},footer);undoResource.hidden=true;
    const contextBack=button('返回浏览结果','context-back',()=>{if(!canLeave())return;contextBack.hidden=true;return browseReturn?.();},main);contextBack.hidden=true;main.prepend(contextBack);
    const canLeave=()=>{if(document.querySelector('#tb-shared-preset-editor, #unified-tag-manager .ut-dialog, #uw-reference-groups, #uw-replacement-review, .danbooru-settings-dialog, .danbooru-tag-catalog-dialog')){report('请先保存或关闭当前编辑。');return false;}try{if(!sections.models.hidden&&frame?.contentWindow?.modalManager?.isAnyModalOpen()){report('请先关闭模型详情或设置，再切换页面。');return false;}}catch{}return true;};
    const pendingButton=button('待用列表 · 0','pending',()=>{if(utilityPage('待用列表')){pending.render(element('div',null,utility));updateTargetActions=pending.refreshTarget;}},header);
    const pending=createPendingPrompts({element,button,insertionOptions,report,draft:pendingDraft,onCount:count=>{pendingButton.textContent='待用列表 · '+count;},openSource:item=>{
        if(item.provider==='library'){promptId=item.id;return chooseLibrary('prompts','all');}
        if(item.provider==='tag'){tagId=item.id;return chooseLibrary('tags','all');}
        if(item.provider==='gallery')return navigate('gallery');
        if(item.provider==='anima'){promptId=item.sourceId;return chooseLibrary('prompts','all');}
        modelFile=item.id;return navigate('models',{provider:item.provider});
    }});
    function availableTargets(){const all=listPromptTargets(app);return allowedTargets?allowedTargets.filter(t=>all.some(item=>item.node===t.node&&item.widget===t.widget)&&(!t.validateTarget||t.validateTarget())):all;}
    function refreshTargets(){
        const targets=availableTargets();
        let invalidated=false;
        if(target&&(targetGraph!==app.graph||!targets.some(t=>t.node===target.node&&t.widget===target.widget))){
            const node=target.node,state=app.graph?.extra?.uap_workbench;
            const branch=state?.branches?.find(item=>item.nodeIds?.some(id=>String(id)===String(node.id)));
            browseOnlyReason='原目标已失效，请选择当前目标；待用内容保留。';
            if(targetGraph===app.graph&&app.graph.getNodeById(node.id)===node){
                const label=`${node.title||node.type} #${node.id}`,disabled=node.mode!=null&&node.mode!==0;
                if(branch&&branch.id!==state.activeBranch)browseOnlyReason=`仅浏览资料：目标“${label}”属于“${branch.label||branch.id}”分支。请先切换到该分支${disabled?'并启用节点':''}，再从该节点打开资料库。`;
                else if(disabled)browseOnlyReason=`仅浏览资料：目标“${label}”未启用。请先启用节点，再从该节点打开资料库。`;
            }
            writer?.dispose();writer=null;undoResource.hidden=true;target=null;direction.value='unknown';invalidated=true;report(browseOnlyReason);
        }
        const signature=targets.map(t=>`${t.node.id}:${t.widget.name}:${t.label}`).join('|');
        if(signature!==targetSignature||!targetPicker.options.length){targetSignature=signature;targetPicker.replaceChildren();element('option','浏览资料 · 未选择写入目标',targetPicker,{value:''});targets.forEach((t,i)=>element('option',t.label,targetPicker,{value:String(i)}));}
        targetPicker.value=target?String(targets.findIndex(t=>t.node===target.node&&t.widget===target.widget)):'';
        const hideDirection=!target||target.direction!=='unknown';if(direction.hidden!==hideDirection)direction.hidden=hideDirection;
        if(invalidated)updateTargetActions?.();
        selectorToolbar?.refresh();
    }
    function selectTarget(next,inputElement){const same=targetGraph===app.graph&&target?.node===next?.node&&target?.widget===next?.widget;const previousDirection=direction.value;writer?.dispose();writer=null;undoResource.hidden=true;browseOnlyReason='';const boundInput=inputElement||window.unifiedDailyControls?.getPromptInput?.(next?.node,next?.widget);target=next?{...next,inputElement,boundInputElement:boundInput}:null;targetGraph=target?app.graph:null;direction.value=same?previousDirection:target?.direction||'unknown';refreshTargets();}
    function insertionOptions(){
        refreshTargets();writer?.dispose();writer=null;undoResource.hidden=true;
        if(!target||direction.value==='unknown')return browseOnlyReason?{browseOnlyReason}:{};
        const source=sourceForTarget(target),input=target.inputElement||target.boundInputElement;
        if(input){source.inputElement=input;source.selectionSnapshot=captureSelection(input);}
        if(!target.inputElement&&target.boundInputElement){const validate=source.validateTarget;source.validateTarget=()=> (!validate||validate()===true)&&window.unifiedDailyControls?.getPromptInput?.(source.node,source.widget)===input;}
        writer=createWidgetInserter(app,source,{commaSeparated:true});
        writer.defaultAction=target.inputElement&&writer.supportsActions.includes('append_cursor')?'append_cursor':'append_end';
        return {onInsert:writer,targetLabel:target.label,targetDirection:direction.value};
    }
    async function targetChanged(){if(updateTargetActions)updateTargetActions();else if(page==='library'&&utility.hidden)await loadLibrary(false);}
    targetPicker.onchange=run(async()=>{const index=targetPicker.value;selectTarget(index===''?null:availableTargets()[Number(index)]);await targetChanged();});
    direction.onchange=run(async()=>{writer?.dispose();writer=null;undoResource.hidden=true;await targetChanged();});
    for(const [key,label]of Object.entries(pages)){const item=button(label,'page-'+key,()=>{contextBack.hidden=true;browseReturn=null;return navigate(key);},nav);mountFunctionIcon(item,key);item.title=toolIdentity[key].purpose;}
    mountThemeToggle(header);
    button('设置','settings',()=>showSettings(),header);
    function close(){if(!canLeave())return false;closed=true;clearTimeout(componentRetryTimer);componentRequest?.abort();sidebarVersion++;searchVersion++;results?.dispose();restoreSelector?.();utilityCleanup?.();utilityCleanup=null;clearInterval(targetTimer);clearTimeout(searchTimer);writer?.dispose();workspace.dispose();closeTagManager();restoreGallery?.();root.remove();current=null;if(previousFocus?.isConnected)previousFocus.focus?.();return true;}
    const returnButton=button('返回常用控制台','return-origin',()=>{const destination=returnTo;if(close())destination?.onReturn();},header);
    returnButton.hidden=true;returnButton.className='uw-return-origin';header.prepend(returnButton);
    button('关闭工作台','close',close,header);
    for(const type of ['copy','cut','paste'])root.addEventListener(type,event=>{if(event.target.closest('input,textarea,[contenteditable=true]'))event.stopPropagation();});
    root.addEventListener('keydown',event=>{
        if(event.defaultPrevented||event.isComposing||event.keyCode===229)return;
        if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
            event.preventDefault();event.stopPropagation();search.focus();search.select();return;
        }
        if(event.key==='Escape'&&event.target===search){
            event.preventDefault();event.stopPropagation();
            if(search.value){search.value='';search.oninput();}else close();
            return;
        }
        if(event.key==='Tab'){
            const items=[...root.querySelectorAll('button,input,select,textarea,a[href],summary,iframe,[tabindex],[contenteditable=true]')].filter(item=>!item.disabled&&item.tabIndex>=0&&item.getClientRects().length);
            const edge=event.shiftKey?items[0]:items.at(-1);
            if(document.activeElement===edge){event.preventDefault();(event.shiftKey?items.at(-1):items[0])?.focus();}
        }
        if(event.key!=='Escape'||event.target.closest('input,textarea,select,[contenteditable=true]'))return;
        if(document.querySelector('#tb-shared-preset-editor, #unified-tag-manager .ut-dialog, #uw-reference-groups, #uw-prompt-use, #uw-replacement-review'))return;
        event.stopPropagation();event.preventDefault();
        const details=event.target.closest('details[open]');
        if(details){details.open=false;details.querySelector('summary')?.focus();return;}
        if(!utility.hidden)void navigate(page);else close();
    });
    const libraryBar=element('div',null,sections.library,{className:'uw-toolbar'}),libraryHost=element('div',null,sections.library,{className:'uw-library-host'});
    search.placeholder='搜索资料、Tag、模型 · Ctrl+K';
    search.setAttribute('aria-keyshortcuts','Control+k Meta+k');
    const sidebarToggle=button('收起侧栏','sidebar-toggle',()=>{
        const collapsed=root.dataset.sidebarCollapsed!=='true';root.dataset.sidebarCollapsed=String(collapsed);
        sidebarToggle.textContent=collapsed?'展开侧栏':'收起侧栏';sidebarToggle.setAttribute('aria-expanded',String(!collapsed));
    },nav);sidebarToggle.setAttribute('aria-expanded','true');
    button('提示词片段','fragments',()=>chooseLibrary('prompts','all'),libraryBar);
    // 基础 Tag 的分流现在由法典分组决定（整组判成串的搬去「标签 tags 串」），
    // 不再靠逗号数的形状筛选当默认，形状下拉保留为手动精确筛选。
    button('基础 Tag','tags',()=>chooseLibrary('tags','all'),libraryBar);
    button('Anima 画师','anima',()=>chooseLibrary('anima','all'),libraryBar);
    button('Krea2 情绪版','krea2mood',()=>chooseLibrary('krea2mood','all'),libraryBar);
    button('画师串','artiststr',()=>chooseLibrary('artiststr','all'),libraryBar);
    button('提示词方案','plans',()=>chooseLibrary('prompts','plans'),libraryBar);
    root.dataset.resourceView=localStorage.getItem('uw-resource-view')||'cards';
    const layoutButton=button(root.dataset.resourceView==='list'?'切换为卡片':'切换为列表','resource-layout',()=>{root.dataset.resourceView=root.dataset.resourceView==='list'?'cards':'list';localStorage.setItem('uw-resource-view',root.dataset.resourceView);layoutButton.textContent=root.dataset.resourceView==='list'?'切换为卡片':'切换为列表';},libraryBar);
    async function showSelectorTools({returnTo:selectorReturnTo=null}={}){
        if(!selector||!utilityPage(selector.label))return;const version=searchVersion,openedSelector=selector,openedTarget=target;
        await openedSelector.native();const overlay=document.querySelector('[id^="anima-"][id$="-selector-overlay"]');
        if(!overlay)throw new Error('选择工具尚未打开，请重试。');if(version!==searchVersion||closed){overlay.unifiedClose?.();return;}
        if(openedTarget && (target?.node!==openedTarget.node || target?.widget!==openedTarget.widget)){overlay.unifiedClose?.();throw new Error('写入目标已变化，请从当前目标重新打开选择器。');}
        if(target)element('p','写入目标：'+target.label,utility);
        const host=element('div',null,utility,{className:'uw-native-selector'});
        function mountSelector(overlay){
            targetPicker.disabled=direction.disabled=true;
            overlay.dataset.unifiedEmbedded='true';overlay.setAttribute('role','region');overlay.removeAttribute('aria-modal');
            host.replaceChildren(overlay);overlay.style.cssText='position:relative;inset:auto;z-index:auto;width:100%;height:65vh;min-height:400px;display:flex;background:transparent;backdrop-filter:none';
            const observer=new MutationObserver(()=>{if(!overlay.isConnected){observer.disconnect();restoreSelector=null;targetPicker.disabled=direction.disabled=false;if(selectorReturnTo&&close())selectorReturnTo.onReturn();else void navigate(page);}});observer.observe(host,{childList:true});
            restoreSelector=()=>{observer.disconnect();overlay.unifiedClose?.();restoreSelector=null;targetPicker.disabled=direction.disabled=false;};
            overlay.unifiedReopen=async reopen=>{
                observer.disconnect();overlay.unifiedClose?.();restoreSelector=null;
                targetPicker.disabled=direction.disabled=false;
                try{
                    await reopen();const replacement=document.querySelector('[id^="anima-"][id$="-selector-overlay"]');
                    if(version!==searchVersion||closed){replacement?.unifiedClose?.();return;}
                    if(!replacement)throw new Error('选择工具尚未打开，请重试。');mountSelector(replacement);
                }catch(error){if(version===searchVersion&&!closed){targetPicker.disabled=direction.disabled=false;await navigate(page);}throw error;}
            };
            if(overlay.unifiedFocus)overlay.unifiedFocus();else overlay.querySelector('input[type=search],input,button')?.focus();
        }
        mountSelector(overlay);
    }
    const selectorTools=button('更多选择工具','selector-tools',showSelectorTools,libraryBar);selectorTools.hidden=true;
    selectorToolbar=mountSelectorTools(selectorToolHost,{element,button,getTargets:availableTargets,getTarget:()=>target,selectTarget:run(async next=>{selectTarget(next);await targetChanged();}),report,
        open:async(tool,next)=>{
            requireComponent('anima');
            selector={node:next.node,section:tool.kind,label:tool.label,native:()=>openPromptSelector(app,tool.kind,next)};
            return showSelectorTools();
        }});
    const modelBar=element('div',null,sections.models,{className:'uw-toolbar'}),modelHost=element('div',null,sections.models,{className:'uw-provider-host'});
    for(const [key,label]of Object.entries(providers))button(label,key,()=>openModels(key),modelBar);
    button('模型设置','model-page-settings',()=>openModels(provider,'settings'),modelBar);
    const modelContext=element('span',null,modelBar),clearModel=button('清除筛选','model-clear',()=>{group='';modelQuery='';modelFile='';modelFavorites=false;return openModels();},modelBar);
    sections.gallery.classList.add('uw-gallery-page');
    const galleryBar=element('div',null,sections.gallery,{className:'uw-toolbar'}),galleryHost=element('div',null,sections.gallery,{className:'uw-provider-host uw-gallery-host'});
    const workspace=mountWorkspace(sections.workspace,{app,element,button,report,selectTarget,close,
        browse:async(next,inputElement,kind='')=>{selectTarget(next,inputElement);theme=kind;sourceCategory='';subcategory='';await chooseLibrary('prompts','all');},
        models:value=>navigate('models',{provider:value}),
        savePlan:(text,usage,label,sections)=>{if(!text.trim())throw new Error('请先填写提示词。');return window.weilinOpenSharedPresets({editorOnly:true,createPrompt:true,prefill:{prompt:text,plan_sections:sections,new_category_name:'我的方案',is_user_plan:true,template:true,sourceLabel:label,_semantic:{primary_class:'task_template',content_type:'template',usage}},onClose:()=>{root.hidden=false;}});},
    });
    async function loadLibrary(reset){
        if(!canLeave())return;requireComponent('weilin');
        libraryHost.querySelector('[data-uw=library-loading]')?.remove();
        const loading=element('div','正在加载资料库…',libraryHost,{className:'uw-empty'});loading.dataset.uw='library-loading';loading.setAttribute('role','status');
        libraryHost.setAttribute('aria-busy','true');
        try{
        if(type==='tags'){if(reset)tagState={...tagState,query,collection:group,favorites:view==='favorites'};await openTagManager({mount:libraryHost,state:tagState,...(tagId?{editTagId:tagId,readOnly:true}:{}),...insertionOptions(),onClose:async()=>{await navigate('workspace');nav.querySelector('[aria-current=page]')?.focus();}});tagId='';}
        else{
            await ensureSharedPresetManagerLoaded();
            if(closed||page!=='library'||!closeTagManager()){loading.remove();return;}
            // Anima 画师页只显示「Anima 画师风格」整区（40,600 条画师，带预览图），
            // Krea2 情绪版、画师串同理：各自整区独立出来，来源下拉同步收窄到本区。
            const area=type==='anima'?ANIMA_ARTIST_AREA:type==='krea2mood'?KREA2_MOOD_AREA:type==='artiststr'?ARTIST_STRING_AREA:'';
            const poolIntent=clearPoolOnce?{clearPool:true}:removePoolThemeOnce?{removePoolTheme:removePoolThemeOnce}:{};
            clearPoolOnce=false;removePoolThemeOnce='';
            await window.weilinOpenSharedPresets({mount:libraryHost,
                ...(reset?{view,semanticClass:area?'':theme,collectionId:group,query:area||query,categoryId:sourceCategory||undefined,subcategory:subcategory||''}:{}),
                ...(area?{sourceFilter:area,areaFilter:area}:{}),
                ...poolIntent,
                ...(promptId?{promptId}:{}),...insertionOptions(),onClose:()=>navigate('workspace')});
            promptId='';
        }
        mounted=type;libraryBar.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.uw===(type==='tags'?'tags':type==='anima'?'anima':type==='krea2mood'?'krea2mood':type==='artiststr'?'artiststr':view==='plans'?'plans':'fragments'))));
        loading.remove();
        }catch(error){loading.textContent=error.message;button('重新加载资料库','library-retry',()=>{report('');return loadLibrary(reset);},loading);throw error;}
        finally{libraryHost.removeAttribute('aria-busy');}
    }
    async function chooseLibrary(nextType,nextView){if(!canLeave())return;type=nextType;view=nextView;mounted='';await navigate('library',{reset:true});}
    async function openModels(next=provider,tool='',settingsSection='general'){
        if(!canLeave())return;requireComponent('lora_manager');
        provider=next;const url=new URL('/'+provider,location.origin);url.searchParams.set('uw_embed','1');if(group&&provider!=='statistics')url.searchParams.set('uw_group',group);
        if(tool)url.searchParams.set('uw_tool',tool);
        if(tool==='settings')url.searchParams.set('uw_settings',settingsSection);
        if(provider!=='statistics'){if(modelQuery)url.searchParams.set('uw_search',modelQuery);if(modelFile)url.searchParams.set('uw_file',modelFile);if(modelFavorites)url.searchParams.set('uw_favorites','1');}
        modelContext.textContent=provider==='statistics'?'全库统计':[group?'当前分组':'',modelQuery?'搜索：'+modelQuery:'',modelFavorites?'我的收藏':''].filter(Boolean).join(' · ');clearModel.hidden=provider==='statistics'||!modelContext.textContent;
        if(tool==='settings'&&frame?.contentWindow?.unifiedModelSettings&&new URL(frame.src).pathname===url.pathname){frame.contentWindow.unifiedModelSettings(settingsSection);}
        else if(frame?.src!==url.href){modelHost.replaceChildren();frame=element('iframe',null,modelHost,{src:url.href,title:providers[provider]||'模型管理'});frame.dataset.uw='model-frame';}
        modelBar.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.uw===provider)));
    }
    async function openGallery(selected){
        requireComponent('gallery');
        const version=++galleryVersion,nodes=(app.graph?._nodes||[]).filter(n=>n.unifiedGalleryActions);galleryNodes=nodes;galleryBar.replaceChildren();
        if(!nodes.includes(galleryNode)){restoreGallery?.();restoreGallery=null;galleryNode=null;galleryHost.replaceChildren();}
        const node=nodes.includes(selected)?selected:nodes.includes(galleryNode)?galleryNode:nodes.length===1?nodes[0]:null;
        for(const item of nodes){const picker=button(`${item.title} #${item.id}`,'gallery-node',()=>openGallery(item),galleryBar);picker.setAttribute('aria-pressed',String(item===node));}
        if(!nodes.length){restoreGallery?.();restoreGallery=null;galleryNode=null;galleryHost.replaceChildren();element('p','当前工作流没有图库节点。通过节点搜索添加图库节点后，这里会使用它的图库与选择结果。',galleryHost);return;}
        if(!node){element('p',galleryIntent?'选择图库节点后继续：'+galleryIntent.label:'请选择要使用的图库节点。',galleryBar);return;}
        if(galleryNode!==node||!galleryHost.contains(node.unifiedGalleryActions.root)){
            const content=node.unifiedGalleryActions.root;if(!content?.parentNode)throw new Error('图库正在加载，请稍后重新打开。');
            restoreGallery?.();galleryHost.replaceChildren();galleryNode=node;
            const marker=document.createComment('workbench-gallery-return'),style=content.style.cssText;content.parentNode.insertBefore(marker,content);galleryHost.append(content);
            restoreGallery=()=>{if(marker.parentNode){marker.replaceWith(content);content.style.cssText=style;}else content.remove();node.unifiedGalleryActions.setEmbedded(false);};
            node.unifiedGalleryActions.setEmbedded(true);
        }
        const intent=galleryIntent;if(intent){galleryIntent=null;try{await node.unifiedGalleryActions[intent.action](intent.query);}catch(error){if(closed||version!==galleryVersion)return;galleryIntent=intent;button('重试：'+intent.label,'gallery-retry',()=>openGallery(node),galleryBar);throw error;}}
    }
    function renderThemes(){
        if(!themeHost?.isConnected)return;
        const expanded=themeHost.querySelector('details')?.open||selectedThemes.some(id=>!themeShortcuts.includes(id));
        themeHost.replaceChildren();
        const draw=([key,label],parent)=>{const item=button(label,'theme-'+key,async()=>{if(!canLeave())return;const next=selectedThemes.includes(key)?'':key;if(!next)removePoolThemeOnce=key;theme=next;await chooseLibrary('prompts','all');},parent);item.setAttribute('aria-pressed',String(selectedThemes.includes(key)));};
        for(const key of themeShortcuts){const item=themes.find(([id])=>id===key);if(item)draw(item,themeHost);}
        const remaining=themes.filter(([key])=>!themeShortcuts.includes(key));if(remaining.length){const more=element('details',null,themeHost,{open:expanded});element('summary','更多主题 · '+remaining.length,more);remaining.forEach(item=>draw(item,more));}
    }
    async function renderSidebar(){
        const version=++sidebarVersion;side.replaceChildren();mountFunctionCard(side,page);element('small','我的资料',side);
        button('全部','all',async()=>{group='';theme='';sourceCategory='';subcategory='';query='';search.value='';clearPoolOnce=true;await chooseLibrary(type,'all');});
        button('收藏','favorites',showFavorites);button('最近使用','recent',()=>chooseLibrary('prompts','recent'));
        themeHost=null;if(page==='library'&&type==='prompts'){element('small','主题分类',side);themeHost=element('div',null,side,{className:'uw-themes'});renderThemes();}
        element('small','我的分组',side);const groupsHost=element('div',null,side);
        button('管理分组','manage-groups',()=>{requireComponent('weilin');return window.weilinOpenSharedPresets({collectionsOnly:true,selectorKind:'resource',onClose:renderSidebar});});
        element('small','整理与维护',side);
        button('整理资料','organize',async()=>{await chooseLibrary('prompts','all');const section=libraryHost.querySelector('.tb-spm-management');if(section)section.open=true;});
        button('导入与导出','transfer',showTransfers);
        try{const response=await fetch('/prompt_selector/collections/index',{cache:'no-store'}),data=await response.json();if(!response.ok)throw new Error(data.error||'读取分组失败');if(closed||version!==sidebarVersion)return;
            for(const item of data.groups){const b=button(item.id==='default'?'默认分组':item.name,'group-'+item.id,async()=>{group=item.id;await showGroup(item);},groupsHost);b.setAttribute('aria-pressed',String(group===item.id));}
        }catch(error){if(version===sidebarVersion){element('p','分组暂不可读，请检查服务连接后重试。',groupsHost);button('重试','retry-groups',renderSidebar,groupsHost);}}
    }
    function saveBrowsePosition(){
        if(!browseState||utility.hidden)return;
        browseState.scrollTop=main.scrollTop;
        const focused=document.activeElement;
        if(utility.contains(focused))browseState.focus={key:focused.dataset.uw,resource:focused.dataset.resourceKey};
    }
    function restoreBrowsePosition(state,version){
        if(closed||version!==searchVersion||utility.hidden)return;
        const focus=state.focus;
        if(focus){const item=[...utility.querySelectorAll('button')].find(b=>b.dataset.uw===focus.key&&b.dataset.resourceKey===focus.resource);if(item&&!item.closest('[hidden]'))item.focus({preventScroll:true});}
        main.scrollTop=state.scrollTop||0;
    }
    function cleanUtility(){updateTargetActions=null;const clean=utilityCleanup;utilityCleanup=null;clean?.();restoreSelector?.();}
    function utilityPage(title,back){if(!canLeave())return false;workspace.setActive(false);animeIntro.hidden=true;selectorToolHost.hidden=true;saveBrowsePosition();browseState=null;if(utility.hidden)utilityReturnFocus=document.activeElement;const searching=document.activeElement===search;searchVersion++;results?.dispose();results=null;cleanUtility();Object.values(sections).forEach(s=>{s.hidden=true;});utility.hidden=false;utility.replaceChildren();const bar=element('div',null,utility,{className:'uw-toolbar'});const backButton=button(back?'返回浏览结果':'返回 '+pages[page],'back',back||(()=>navigate(page)),bar);element('h2',title,bar);if(!searching)backButton.focus();return true;}
    function resourceResults(scope,extraSections=[]){
        results=mountResourceResults(element('div',null,utility),{element,button,scope,extraSections,state:browseState||{},open:async(kind,item,context)=>{
            saveBrowsePosition();browseState=null;
            contextBack.hidden=!browseReturn;
            group=context.group||'';theme='';sourceCategory='';subcategory='';query=context.query||'';
            if(kind==='prompts'){promptId=item.id;await chooseLibrary('prompts',context.favorites?'favorites':'all');}
            else if(kind==='tags'){tagId=item.resource_id;await chooseLibrary('tags',context.favorites?'favorites':'all');}
            else{modelQuery=item.file_name||'';modelFile=item.file_path;modelFavorites=!!context.favorites;await navigate('models',{provider:kind});}
        },more:async(kind,context)=>{
            saveBrowsePosition();browseState=null;
            contextBack.hidden=!browseReturn;
            group=context.group||'';theme='';sourceCategory='';subcategory='';query=context.query||'';
            if(['prompts','tags'].includes(kind))await chooseLibrary(kind,context.favorites?'favorites':'all');
            else{modelQuery=query;modelFile='';modelFavorites=!!context.favorites;await navigate('models',{provider:kind});}
        }});return results.ready;
    }
    function showFavorites(){return renderFavorites({});}
    async function renderFavorites(state){if(!utilityPage('我的收藏'))return;const version=searchVersion;browseState=state;contextBack.hidden=true;browseReturn=()=>renderFavorites(state);element('p','资料、Tag 和本机模型使用各自原来的收藏记录。图库收藏可在图库来源中查看。',utility);button('图库收藏','favorite-images',()=>navigate('gallery',{galleryIntent:{action:'showFavorites',label:'查看收藏'}}),utility);await resourceResults({favorites:true});restoreBrowsePosition(state,version);}
    async function useResource(options){
        if(!canLeave())return;
        const resolve=options.resolveText||(()=>options.text||'');const selected=insertionOptions();
        if(selected.onInsert){const activeWriter=selected.onInsert,text=await resolve();const result=await activeWriter({text,action:activeWriter.defaultAction||'append_end'});if(result.status!=='inserted'&&result.status!=='unchanged')throw new Error('目标已失效，请重新选择。');undoResource.hidden=result.status!=='inserted';activeWriter.onUndoInvalidated=()=>{undoResource.hidden=true;};report('已应用到：'+selected.targetLabel);return;}
        if(!utilityPage('使用：'+(options.title||'提示词')))return;const version=searchVersion;
        const preview=element('pre','正在读取…',utility,{className:'uw-pending-preview'});
        const targetNote=element('p','请在底栏选择使用目标并确认正负向。',utility);
        const actions=element('div',null,utility,{className:'uw-toolbar uw-use-actions'});
        let text=await resolve();if(version!==searchVersion)return;preview.textContent=text;
        const bind=()=>{actions.replaceChildren();const currentOptions=insertionOptions();targetNote.textContent=currentOptions.onInsert?'将应用到：'+currentOptions.targetLabel+(currentOptions.targetDirection==='negative'?' · 负向':' · 正向'):'请在底栏选择使用目标并确认正负向。';if(currentOptions.onInsert)mountInsertionActions(actions,currentOptions.onInsert,async()=>{const latest=await resolve();if(latest!==text){text=latest;preview.textContent=latest;throw new Error('原资料已更新，请核对预览后重新应用。');}return text;},report);};updateTargetActions=bind;bind();
    }
    async function showImageReference(reference){
        if(!utilityPage(`${reference.provider} · 图片 #${reference.resource}`,browseReturn))return;contextBack.hidden=true;
        const nodes=(app.graph?._nodes||[]).filter(node=>node.unifiedGalleryActions?.showReference);
        const host=element('div',null,utility,{className:'uw-image-reference'});
        if(!nodes.length){element('p','当前没有图库节点。添加图库节点后，可使用同一图片详情和选取功能。',host);return;}
        const show=async node=>{host.replaceChildren();const note=element('p','正在读取原图片…',host);try{await node.unifiedGalleryActions.showReference(reference,host);note.remove();}catch(error){note.textContent=error.message;button('重试','retry-image',()=>show(node),host);}};
        if(nodes.length===1)await show(nodes[0]);else{element('p','选择这张图片要使用的图库节点：',host);for(const node of nodes)button(`${node.title} #${node.id}`,'reference-gallery',()=>show(node),host);}
    }
    async function showGroup(item,state={}){
        if(!utilityPage(item.id==='default'?'默认分组':item.name))return;browseState=state;contextBack.hidden=true;browseReturn=()=>showGroup(item,state);const bar=element('div',null,utility,{className:'uw-toolbar'});
        button('提示词','group-prompts',()=>chooseLibrary('prompts','all'),bar);button('基础 Tag','group-tags',()=>chooseLibrary('tags','all'),bar);
        const version=searchVersion;const references=element('section',null,utility);references.dataset.kind='images';const ready=resourceResults({group:item.id},[references]);utility.append(references);
        try{const data=await getReferenceCollections({group_id:item.id});if(version!==searchVersion||closed)return;
            const images=data.items.filter(ref=>!providers[ref.provider]);element('h3','图片 · '+images.length,references);if(!images.length)element('p','这个分组还没有图片。可在图库的图片详情中加入分组。',references);
            for(const ref of images){const row=element('div',null,references,{className:'uw-resource-row'});element('span',`${ref.provider} · ${ref.resource}`,row);
                button('查看','open-reference',()=>{saveBrowsePosition();browseState=null;contextBack.hidden=false;return showImageReference(ref);},row);
                button('修改分组','edit-reference',()=>openReferenceCollections({provider:ref.provider,resource:ref.resource},{title:ref.resource,onSaved:()=>showGroup(item,state)}),row);}
        }catch(error){if(version===searchVersion){element('p',error.message,references);button('重试引用','retry-references',()=>showGroup(item),references);}}await ready;restoreBrowsePosition(state,version);
    }
    function showSettings(){
        if(!utilityPage('设置'))return;
        const filterBar=element('div',null,utility,{className:'uw-toolbar uw-settings-search'});
        const filter=element('input',null,filterBar,{type:'search',placeholder:'查找设置，如触发词、快捷键…'});filter.setAttribute('aria-label','查找设置');filter.setAttribute('aria-controls','uw-settings-results');
        const clearFilter=button('清除','settings-search-clear',()=>{filter.value='';applyFilter();filter.focus();},filterBar);clearFilter.hidden=true;
        const count=element('span','',filterBar,{className:'uw-muted'});count.setAttribute('role','status');
        const row=element('div',null,utility,{className:'uw-settings-grid',id:'uw-settings-results'});
        const area=(title,note)=>{const section=element('section',null,row);element('h3',title,section);if(note)element('p',note,section);return section;};
        const display=area('显示与浏览','工作台显示密度。其他界面偏好在 ComfyUI 设置中维护。');
        const label=element('label','显示密度 ',display),picker=element('select',null,label);for(const [value,text]of [['comfortable','舒适'],['compact','紧凑']])element('option',text,picker,{value});picker.value=root.dataset.density;
        picker.onchange=()=>{root.dataset.density=picker.value;localStorage.setItem('uw-density',picker.value);};
        mountCanvasThemeSetting(display,report);
        button('打开外观设置','app-settings',()=>openNativeSettings(app,root,'appearance'),display);
        const input=area('输入与补全','输入 /library 搜索共享 Tag；普通词典和模型补全沿用原设置。');
        button('编辑补全词典','completion-words',async()=>{if(!window.promptLibraryAutocomplete?.manageWords)throw new Error('补全工具尚未加载');if(!utilityPage('输入与补全',showSettings))return;const version=searchVersion;const dialog=await window.promptLibraryAutocomplete.manageWords(showSettings,element('div',null,utility));if(version!==searchVersion||closed){dialog.dispose?.();return;}utilityCleanup=()=>dialog.dispose?.();},input);
        button('普通词典补全设置','input-settings',()=>openNativeSettings(app,root,'completion'),input);
        button('模型补全设置','model-input-settings',()=>openNativeSettings(app,root,'modelInput'),input);
        const model=area('模型','模型路径、预览、触发词与备份由模型管理器统一维护。');
        button('模型常规设置','model-settings',()=>navigate('models',{modelTool:'settings',modelSettings:'general'}),model);
        button('模型显示设置','model-display-settings',()=>navigate('models',{modelTool:'settings',modelSettings:'interface'}),model);
        button('模型库与备份','model-library-settings',()=>navigate('models',{modelTool:'settings',modelSettings:'library'}),model);
        button('图库与来源设置','gallery-settings',()=>navigate('gallery',{galleryIntent:{action:'showSettings',label:'打开来源设置'}}),area('图库与来源','沿用当前图库节点的来源、站点和显示设置。'));
        button('打开快捷键设置','shortcut-settings',()=>openNativeSettings(app,root,'shortcuts'),area('快捷键','在 ComfyUI 设置的快捷键页调整。工作台内 Escape 返回上层，输入期间保留原编辑器快捷键。'));
        const advanced=element('details',null,row,{className:'uw-settings-advanced'});element('summary','兼容与恢复',advanced);
        const recovery=element('div',null,advanced);element('p','旧工作流与节点继续可用。导入失败会保留当前资料；编辑冲突时先保留草稿并重新读取版本。',recovery);
        button('导入与导出','settings-transfers',showTransfers,recovery);
        button('检查组件状态','compatibility-status',async()=>{const state=await checkComponents(false);if(state)report(`已加载 ${state.modules.filter(item=>item.ready).length} 个组件 · ${state.nodes} 个兼容节点。`);},recovery);
        const empty=element('p','没有匹配的设置。请换一个关键词，或清除搜索查看全部。',utility);empty.hidden=true;
        let filtering=false,advancedWasOpen=false;
        function applyFilter(){
            const words=filter.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
            if(words.length&&!filtering)advancedWasOpen=advanced.open;
            const items=[...row.children];let visible=0;
            for(const item of items){const text=item.textContent.toLocaleLowerCase();item.hidden=!words.every(word=>text.includes(word));if(!item.hidden)visible++;}
            advanced.open=words.length?!advanced.hidden:advancedWasOpen;
            filtering=!!words.length;clearFilter.hidden=!filtering;empty.hidden=visible>0;count.textContent=filtering?`找到 ${visible} 类设置`:'';
        }
        filter.oninput=applyFilter;
        filter.onkeydown=event=>{if(event.key==='Escape'&&!event.isComposing&&filter.value){event.preventDefault();event.stopPropagation();filter.value='';applyFilter();}};
        filter.focus();
    }
    function showTransfers(){if(!utilityPage('导入与导出'))return;element('p','选择资料类型后检查导入范围、原 ID 和冲突，再提交修改。',utility);
        button('提示词 ZIP 导入','import-prompts',()=>window.weilinOpenSharedPresets({importOnly:true,onClose:()=>{root.hidden=false;}}),utility);
       element('a','导出提示词库 ZIP（不含预览图）',utility,{href:'/prompt_selector/export?include_previews=0',download:'prompt_library.zip'});
       element('p','默认不打包预览图：库内预览合计约 21.7 GB，打包会长时间占用磁盘与带宽。导出内容为完整提示词、分类、审核与收藏分组数据，可直接再次导入。确需图片时可单独选择“含预览图”。',utility);
       element('a','导出含预览图 ZIP（体积很大）',utility,{href:'/prompt_selector/export?include_previews=1',download:'prompt_library.zip'});
       element('p','含预览图导出会在临时目录生成数十 GB 归档；若可用空间不足会直接提示并拒绝，不会中断服务。Tag 可在列表选择范围后导出，模型文件与图库图片由对应专业工具管理。',utility);
        button('基础 Tag JSON 导入 / 导出','import-tags',()=>chooseLibrary('tags','all'),utility);button('模型库与备份','import-models',()=>navigate('models',{modelTool:'settings',modelSettings:'library'}),utility);}
    async function navigate(next,opts={}){
        if(!canLeave())return;saveBrowsePosition();const returnFocus=!utility.hidden&&(utility.contains(document.activeElement)||document.activeElement===document.body)?utilityReturnFocus:null;utilityReturnFocus=null;searchVersion++;galleryVersion++;galleryIntent=opts.galleryIntent||null;results?.dispose();results=null;cleanUtility();page=next;lastPage=page;localStorage.setItem('uw-last-page',page);utility.hidden=true;Object.entries(sections).forEach(([key,s])=>{const active=key===page;s.hidden=!active;s.inert=!active;});
        workspace.setActive(page==='workspace');
        root.dataset.page=page;animeIntro.hidden=page==='workspace';
        if(page==='workspace')workspace.selectorHost.append(selectorToolHost);
        else if(page==='library')main.insertBefore(selectorToolHost,sections.library);
        selectorToolHost.hidden=!['workspace','library'].includes(page);
        const intro=toolIdentity[page];animeEyebrow.textContent='晴空手帖 / '+pages[page];animeTitle.textContent=intro.title;animeDescription.textContent=intro.purpose;
        nav.querySelectorAll('button').forEach(b=>b.setAttribute('aria-current',b.dataset.uw==='page-'+page?'page':'false'));report('');refreshTargets();
        const sidebarReady=opts.openSelector?Promise.resolve():renderSidebar();
        if(page==='workspace')workspace.refresh();
        if(page==='library'&&!opts.openSelector&&!opts.openPending)await loadLibrary(!!opts.reset);
        if(page==='models')await openModels(opts.provider,opts.modelTool,opts.modelSettings);if(page==='gallery')await openGallery(opts.node);await sidebarReady;
        if(returnFocus&&!closed&&utility.hidden&&(document.activeElement===document.body||utility.contains(document.activeElement))){(returnFocus.isConnected&&!returnFocus.closest('[hidden]')?returnFocus:nav.querySelector('[aria-current=page]'))?.focus();}
    }
    search.addEventListener('compositionstart',()=>{searchComposing=true;clearTimeout(searchTimer);});
    search.addEventListener('compositionend',()=>{searchComposing=false;search.oninput();});
    search.oninput=()=>{
        if(searchComposing)return;
        clearTimeout(searchTimer);
        report(search.value.trim()?'正在搜索…':'');
        const version=++searchVersion;
        results?.dispose();
        searchTimer=setTimeout(()=>{if(!closed&&version===searchVersion)void run(searchAll)();},300);
    };
    async function searchAll(){
        const value=search.value.trim();if(!value)return navigate(page);return renderSearch(value,{});
    }
    async function renderSearch(value,state){
        if(!utilityPage('搜索：'+value))return;const version=searchVersion;browseState=state;query=value;search.value=value;contextBack.hidden=true;browseReturn=()=>renderSearch(value,state);button('在图库中搜索','search-gallery',()=>navigate('gallery',{galleryIntent:{action:'search',query:value,label:'搜索“'+value+'”'}}),utility);await resourceResults({query:value});restoreBrowsePosition(state,version);if(version===searchVersion&&!closed)report('');
    }
    const targetTimer=setInterval(()=>{if(document.hidden||root.hidden||!root.isConnected)return;refreshTargets();if(!utility.hidden)return;if(page==='workspace')workspace.refresh();if(page==='gallery'){const nodes=(app.graph?._nodes||[]).filter(n=>n.unifiedGalleryActions);if(nodes.length!==galleryNodes.length||nodes.some((node,i)=>node!==galleryNodes[i]))void run(()=>openGallery())();}},750);
    root.dataset.density=localStorage.getItem('uw-density')||'comfortable';
    current={root,close,useResource,addPending:pending.add,addPendingMany:pending.addMany,showPending:()=>pendingButton.onclick(),open:async opts=>{if(opts.returnTo){returnTo=opts.returnTo;returnButton.textContent='← 返回'+returnTo.label;returnButton.title='回到打开前的'+returnTo.label;returnButton.hidden=false;}allowedTargets=opts.targetOptions||null;if(opts.targetOptions)selectTarget(null);if(opts.target)selectTarget(opts.target,opts.inputElement);if(opts.theme!=null){theme=opts.theme;group='';query='';if(opts.selector){sourceCategory='';subcategory='';search.value='';clearPoolOnce=true;removePoolThemeOnce='';}}if(opts.type)type=opts.type;if(opts.view)view=opts.view;selector=opts.selector||null;selectorTools.hidden=!selector;await navigate(opts.page||page||lastPage||(listPromptTargets(app).length?'workspace':'library'),{...opts,reset:opts.reset||opts.theme!=null||!!opts.view});if(opts.openSelector&&selector)await showSelectorTools({returnTo:opts.returnTo});}};
    window.unifiedWorkbenchOpenProvider=value=>current?.open({page:value==='gallery'?'gallery':'models',provider:value});window.unifiedWorkbenchReturn=()=>{if(current)current.root.hidden=false;};
    void checkComponents();
    try{await current.open(options);}catch(error){report(error);}if(!closed&&!root.hidden&&(document.activeElement===previousFocus||document.activeElement===document.body))search.focus();return current;
}

app.registerExtension({name:'UnifiedPromptWorkbench',afterConfigureGraph(){
    // Native custom palettes are restored after extension setup, before graph loading.
    installCanvasTheme(app);
},async setup(){
    installUiTheme();
    installResourceActions(app);window.unifiedOpenWorkbench=openWorkbench;window.weilinOpenSharedPresets=openSharedPresets;
    void ensureSharedPresetManagerLoaded().catch(()=>{});
    window.unifiedUseResourcePrompt=async options=>{const owner=current?.root.isConnected?current:await openWorkbench();return owner.useResource(options);};
    window.unifiedQueuePrompt=async resource=>{const owner=current?.root.isConnected?current:await openWorkbench();owner.addPending(resource);if(resource.open)await owner.showPending();};
    window.unifiedQueuePrompts=async resources=>{const owner=current?.root.isConnected?current:await openWorkbench();return owner.addPendingMany(resources);};
    if(!document.getElementById('uw-experience-style'))element('link',null,document.head,{id:'uw-experience-style',rel:'stylesheet',href:'/extensions/ComfyUI-Unified-Prompt-Workbench/workbench.css?v=20260928-gallery'});
    const entry=element('button','统一工作台',document.body,{id:'unified-workbench-entry',type:'button'});entry.title='工作区、资料库、模型与图库';entry.onclick=()=>openWorkbench();
    installBrowserImportReceiver({openWorkbench});
}});
