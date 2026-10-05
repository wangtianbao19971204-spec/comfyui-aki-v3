// Keep body-mounted dialogs inside their keyboard and pointer boundary.
export function manageModal(root, {initialFocus, onClose, returnFocus=document.activeElement} = {}) {
    const previous=returnFocus, blocked=[];
    for(let child=root;child?.parentElement;child=child.parentElement){
        for(const sibling of child.parentElement.children)if(sibling!==child&&!sibling.inert){blocked.push(sibling);sibling.inert=true;}
        if(child.parentElement===document.body)break;
    }
    const dialog=root.matches('[role=dialog]')?root:root.querySelector('[role=dialog]')||root;
    dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');root.tabIndex=-1;
    const focusable=()=>[...root.querySelectorAll('button,input,textarea,select,a[href],summary,[tabindex]')].filter(el=>!el.disabled&&el.tabIndex>=0&&!el.closest('[hidden],[inert]')&&el.getClientRects().length);
    const key=event=>{
        if(event.isComposing||event.defaultPrevented)return;
        if(event.key==='Escape'&&onClose){event.preventDefault();event.stopPropagation();onClose();}
        if(event.key==='Tab'){const items=focusable(),first=items[0]||root,last=items.at(-1)||root;if(!items.length||!root.contains(document.activeElement)||document.activeElement===(event.shiftKey?first:last)){event.preventDefault();(event.shiftKey?last:first).focus();}}
    };
    root.addEventListener('keydown',key);
    (initialFocus||focusable()[0]||root).focus();
    let done=false;
    const dispose=()=>{if(done)return;done=true;observer.disconnect();root.removeEventListener('keydown',key);for(const el of blocked)el.inert=false;if((document.activeElement===document.body||root.contains(document.activeElement))&&previous?.isConnected&&!previous.closest('[inert]'))previous.focus();};
    const observer=new MutationObserver(()=>{if(!root.isConnected)dispose();});observer.observe(document.body,{childList:true,subtree:true});
    return dispose;
}
