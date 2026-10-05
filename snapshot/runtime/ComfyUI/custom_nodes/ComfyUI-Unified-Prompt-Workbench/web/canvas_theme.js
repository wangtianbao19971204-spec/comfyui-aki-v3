import {getUiTheme} from './ui_theme.js';

const linkedKey='uw-canvas-theme-linked',originalKey='uw-canvas-original-palette';
let bridge;
const read=(key,fallback)=>{try{return localStorage.getItem(key)??fallback;}catch{return fallback;}};
const write=(key,value)=>{try{localStorage.setItem(key,value);}catch{/* Keep the current session usable. */}};

export function canvasPalette(theme,dark){
    const light=theme==='light'||(theme==='anime'&&!dark),color=theme==='anime';
    const background=light?(color?'#eef1fb':'#eef1f6'):(color?'#232530':'#202229');
    const grid=light?(color?'#cbd4ec':'#d0d8e5'):(color?'#393d50':'#343946');
    const surface=light?'#fcfcfa':color?'#2b2d39':'#272930',text=light?'#303b50':'#e5e7ef';
    const input=light?'#ffffff':'#22242b',muted=light?'#5b6579':'#b0b5c5',border=light?'#ced4df':'#404450';
    const pattern=`<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><circle cx="1" cy="1" r=".85" fill="${grid}"/></svg>`;
    return {
        id:`uw-sky-${color?'color-':''}${light?'day':'night'}-v1`,name:`晴空手帖 · ${color?'多色 · ':''}${light?'白天':'夜间'}`,light_theme:light,
        colors:{node_slot:{},litegraph_base:{
            BACKGROUND_IMAGE:'data:image/svg+xml,'+encodeURIComponent(pattern),CLEAR_BACKGROUND_COLOR:background,
            // UAP nodes have authored dark functional colors. Keep their labels readable without rewriting the workflow.
            NODE_TITLE_COLOR:'#e8edf8',NODE_SELECTED_TITLE_COLOR:'#ffffff',NODE_TEXT_COLOR:'#dfe6f2',NODE_TEXT_HIGHLIGHT_COLOR:'#ffffff',
            NODE_DEFAULT_COLOR:'#43516a',NODE_DEFAULT_BGCOLOR:'#2d3543',NODE_DEFAULT_BOXCOLOR:'#93a4c0',NODE_BOX_OUTLINE_COLOR:'#8c9ebc',
            WIDGET_BGCOLOR:'#222a37',WIDGET_OUTLINE_COLOR:'#5b6982',WIDGET_TEXT_COLOR:'#e8edf8',WIDGET_SECONDARY_TEXT_COLOR:'#b8c3d6',WIDGET_DISABLED_TEXT_COLOR:'#94a0b4',
            DEFAULT_SHADOW_COLOR:light?'rgba(46,61,86,.13)':'rgba(0,0,0,.22)',
        },comfy_base:{
            'fg-color':text,'bg-color':background,'comfy-menu-bg':surface,'comfy-menu-secondary-bg':light?'#eef0f6':'#24262d',
            'comfy-input-bg':input,'input-text':text,'descrip-text':muted,'drag-text':text,'error-text':light?'#ab354b':'#efafbd','border-color':border,
            'tr-even-bg-color':surface,'tr-odd-bg-color':input,'content-bg':surface,'content-fg':text,'content-hover-bg':light?'#e4eaf5':'#383f59','content-hover-fg':text,
            'bar-shadow':light?'rgba(41,59,92,.12)':'rgba(0,0,0,.22)',
        }},
    };
}

export function installCanvasTheme(app){
    if(bridge)return bridge;
    const settings=app.extensionManager?.setting,palettes=app.extensionManager?.colorPalette;
    if(!settings?.set||!palettes?.addCustomColorPalette||!palettes?.loadColorPalette)return null;
    let linked=read(linkedKey,'true')!=='false',pending=null,desired=null;
    const notify=error=>{
        document.documentElement.dataset.uwCanvasTheme='error';
        app.extensionManager?.toast?.add?.({severity:'warn',summary:'画布配色未同步',detail:error.message||'请在工作台设置中重新启用画布同步。',life:6000});
    };
    async function apply(theme){
        if(!linked)return;
        const current=palettes.getActiveColorPalette();
        const selected=settings.get('Comfy.ColorPalette')||current?.id;
        const savedPalette=settings.get('Comfy.CustomColorPalettes')?.[selected];
        const isLight=current?.id===selected?current.light_theme===true:selected==='light'||savedPalette?.light_theme===true;
        const palette=canvasPalette(theme,!isLight);
        if(current?.id===palette.id){document.documentElement.dataset.uwCanvasTheme='linked';return;}
        if(selected&&!selected.startsWith('uw-sky-'))write(originalKey,selected);
        if(!settings.get('Comfy.CustomColorPalettes')?.[palette.id]){
            await palettes.addCustomColorPalette(palette);
            if(!settings.get('Comfy.CustomColorPalettes')?.[palette.id])throw new Error('配色注册失败，请重试。');
        }
        if(!linked)return;
        await palettes.loadColorPalette(palette.id);
        await settings.set('Comfy.ColorPalette',palette.id);
        if(palettes.getActiveColorPalette()?.id!==palette.id)throw new Error('原生配色尚未切换，请重试。');
        document.documentElement.dataset.uwCanvasTheme='linked';
    }
    function sync(theme=getUiTheme()){
        if(!linked)return Promise.resolve();
        desired=theme;
        if(!pending)pending=(async()=>{
            while(desired){const next=desired;desired=null;await apply(next);}
        })().catch(error=>{notify(error);throw error;}).finally(()=>{pending=null;if(desired&&linked)void sync(desired).catch(()=>{});});
        return pending;
    }
    bridge={sync,get linked(){return linked;},async setLinked(value){
        linked=value;write(linkedKey,String(value));
        if(value)return sync();
        desired=null;await pending?.catch(()=>{});
        const original=read(originalKey,'dark');
        await palettes.loadColorPalette(original);await settings.set('Comfy.ColorPalette',original);
        document.documentElement.dataset.uwCanvasTheme='independent';
    }};
    window.addEventListener('uw-theme-change',event=>void sync(event.detail.theme).catch(()=>{}));
    window.addEventListener('storage',event=>{if(event.key===linkedKey)void bridge.setLinked(event.newValue!=='false').catch(notify);});
    void sync().catch(()=>{});return bridge;
}

export function mountCanvasThemeSetting(parent,report){
    const label=document.createElement('label');label.className='uw-canvas-theme-setting';label.style.display='block';
    const input=document.createElement('input');input.type='checkbox';input.checked=bridge?.linked??read(linkedKey,'true')!=='false';input.disabled=!bridge;
    input.setAttribute('aria-label','画布随工作台主题切换');label.append(input,document.createTextNode(' 画布、菜单随工作台主题切换'));parent.append(label);
    input.onchange=async()=>{input.disabled=true;try{await bridge.setLinked(input.checked);report(input.checked?'画布配色已同步。':'已恢复原生画布配色。');}catch(error){report(error);}finally{input.checked=bridge.linked;input.disabled=false;}};
}
