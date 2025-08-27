/** @ts-ignore */
import { app } from "../../scripts/app.js";
import { showTextModal, createModal } from "./ui/modal.js";
import { getCacheStatus, clearCache } from "./api/joycaption.js";
import { getWidget, refresh } from "./ui/helpers.js";
import { applyPresetFlow } from "./features/presets.js";

app.registerExtension({
  name: "olm.joycaption",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "OlmJoyCaption") return;

    const original = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = original?.call(this);

      const preset = () => getWidget(this, "preset_prompt")?.value;
      const setPrompt = (text) => {
        const w = getWidget(this, "prompt");
        if (w) w.value = text;
        refresh(this);
      };

      this.addWidget("button", "Apply Preset", null, async () => {
        await applyPresetFlow(this, {
          getPreset: preset,
          setPrompt,
          onDone: () => refresh(this),
        });
      });

      this.addWidget("button", "Clear Model Cache", null, async () => {
        const data = await clearCache();
        showTextModal(
          data.status === "success" ? "Cache Cleared" : "Error",
          data.status === "success"
            ? `✅ ${data.message}\n\nPreviously cached:\n${
                data.previous_cache || "(unknown)"
              }`
            : `❌ ${data.message || "Unknown error"}`
        );
      });

      this.addWidget("button", "Cache Status", null, async () => {
        const data = await getCacheStatus();
        const body = document.createElement("pre");
        body.className = "olm-pre";
        body.textContent =
          data.status === "success"
            ? data.cache_info ?? null
            : `❌ ${data.message ?? "Unknown"}`;
        const { cleanup } = createModal({
          title: "JoyCaption Cache Status",
          body,
          width: 680,
          actions: [
            { label: "Close", onClick: () => cleanup(), default: true },
          ],
        });
      });

      return r;
    };
  },
});
