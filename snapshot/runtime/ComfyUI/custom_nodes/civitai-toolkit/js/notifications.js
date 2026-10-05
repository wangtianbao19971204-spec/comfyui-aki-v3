import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

app.registerExtension({
    name: "Civitai.Toolkit.Notifications",
    async setup() {
        console.log("[Civitai Toolkit] Setting up toast notifications listener.");

        // 监听后端通过 WebSocket 发送的自定义事件。
        api.addEventListener("scan_started", (event) => {
            const data = event.detail;
            app.extensionManager.toast.add({
                severity: 'info',
                summary: 'Background Scan Started (Civitai Toolkit)',
                detail: data.message,
                life: 5000
            });
        });

        api.addEventListener("scan_complete", (event) => {
            const data = event.detail;
            if (data.success) {
                app.extensionManager.toast.add({
                    severity: 'success',
                    summary: 'Scan Complete! (Civitai Toolkit)',
                    detail: data.message,
                    life: 10000
                });
            } else {
                app.extensionManager.toast.add({
                    severity: 'error',
                    summary: 'Scan Failed (Civitai Toolkit)',
                    detail: data.message,
                    life: 15000
                });
            }
        });
    }
});
