const sections={appearance:'root/Appearance',completion:'root/pysssss',modelInput:'root/LoRA Manager',shortcuts:'keybinding'};

export async function openNativeSettings(app,root,section){
    const command=app.extensionManager?.command;
    if(!command?.commands.some(item=>item.id==='Comfy.ShowSettingsDialog'))throw new Error('当前 ComfyUI 设置入口尚未就绪，请稍后重试。');
    const focus=document.activeElement;root.hidden=true;
    const restore=()=>{if(root.isConnected){root.hidden=false;if(focus?.isConnected)focus.focus();}};
    try{
        await command.execute('Comfy.ShowSettingsDialog');
        const dialog=await new Promise((resolve,reject)=>{
            const find=()=>document.querySelector('[role="dialog"]:has([data-nav-id="root/Comfy"])');
            const existing=find();if(existing){resolve(existing);return;}
            const observer=new MutationObserver(()=>{const node=find();if(node){clearTimeout(timer);observer.disconnect();resolve(node);}});
            observer.observe(document.body,{childList:true,subtree:true});
            const timer=setTimeout(()=>{observer.disconnect();reject(new Error('设置页未能打开，请重试。'));},5000);
        });
        const observer=new MutationObserver(()=>{if(!dialog.isConnected||dialog.dataset.state==='closed'||!root.isConnected){observer.disconnect();restore();}});
        observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['data-state']});
        const nav=dialog.querySelector(`[data-nav-id="${sections[section]}"]`);
        if(nav)nav.click();
        else throw new Error('对应设置分类当前不可用，请在已打开的设置页中查找。');
    }catch(error){restore();throw error;}
}
