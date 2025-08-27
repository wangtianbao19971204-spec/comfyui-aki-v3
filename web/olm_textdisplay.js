/** @ts-ignore */
import { app } from "../../scripts/app.js";
/** @ts-ignore */
import { ComfyWidgets } from "../../scripts/widgets.js";
import { getWidget } from "./ui/helpers.js";

app.registerExtension({
  name: "Olm.TextDisplayWidget",
  async beforeRegisterNodeDef(nodeType, nodeData, app) {
    if (nodeData.name === "OlmTextDisplay") {
      const onNodeCreatedOriginal = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        onNodeCreatedOriginal?.call(this);
        const w = ComfyWidgets["STRING"](
          this,
          "olmTextDisplay",
          ["STRING", { multiline: true, placeholder: " " }],
          app
        ).widget;
        w.inputEl.readOnly = true;
        w.inputEl.style.opacity = 0.8;
        w.inputEl.style.cursor = "auto";
      };

      const onExecutedOriginal = nodeType.prototype.onExecuted;
      nodeType.prototype.onExecuted = function (message) {
        onExecutedOriginal?.call(this);

        if (message?.text) {
          const widget = getWidget(this, "olmTextDisplay");
          if (widget) {
            widget.value = message.text.join("");
          }

          this.onResize?.(this.size);
        }
      };
    }
  },
});
