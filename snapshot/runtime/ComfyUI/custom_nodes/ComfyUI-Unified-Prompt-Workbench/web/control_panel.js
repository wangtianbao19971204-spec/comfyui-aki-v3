import {app} from '../../../scripts/app.js';
import {controlScope, mountControlSwitches} from './control_switches.js';

// Standalone production workflows do not have the UAP daily controls.
app.registerExtension({
    name: 'UnifiedPromptWorkbench.ControlPanel',
    setup() {
        const button = Object.assign(document.createElement('button'), {textContent: '控制与擦线', type: 'button', hidden: true});
        button.style.cssText = 'position:fixed;right:24px;bottom:64px;z-index:1000;padding:9px 16px;border-radius:8px;background:#233744;color:#e4f1f8;border:1px solid #648494;cursor:pointer';
        const panel = document.createElement('aside'); panel.hidden = true;
        panel.style.cssText = 'position:fixed;right:24px;bottom:112px;width:min(360px,calc(100vw - 48px));max-height:70vh;overflow:auto;z-index:1000;padding:16px;background:#202b35;color:#e4f1f8;border:1px solid #648494;border-radius:8px;font:14px/1.6 system-ui';
        const style = document.createElement('style');
        style.textContent = '.desk-control-switches label{display:flex;gap:8px;align-items:center;margin:8px 0}.desk-control-switches small{display:block;margin-top:8px}.desk-control-switches select,.desk-control-switches button{font:inherit;padding:4px 8px}.desk-control-switches input[type=checkbox]{width:18px;height:18px;accent-color:#62abc5}';
        document.head.append(style); document.body.append(button, panel);
        let graph, model, controls;
        const refresh = () => {
            const root = app.rootGraph || app.graph;
            const scope = root && !root.extra?.uap_workbench && controlScope(root);
            const available = !!scope;
            button.hidden = !available;
            if (!available || graph !== root || model !== scope.model) {
                controls?.dispose(); controls = null; panel.hidden = true; graph = root; model = scope?.model;
                button.setAttribute('aria-expanded', 'false');
            }
            controls?.sync();
        };
        button.onclick = () => {
            refresh();
            if (button.hidden) return;
            if (!controls) controls = mountControlSwitches(panel, app);
            panel.hidden = !panel.hidden;
            button.setAttribute('aria-expanded', String(!panel.hidden));
        };
        setInterval(refresh, 750);
        refresh();
    },
});
