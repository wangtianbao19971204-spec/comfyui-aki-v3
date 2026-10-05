import json,sys,collections
sys.stdout.reconfigure(encoding="utf-8")
p=r"ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\prompt_selector\data.json"
d=json.load(open(p,encoding="utf-8"))
imgs=[]
for c in d["categories"]:
    for pr in c["prompts"]:
        im=pr.get("image")
        if im: imgs.append(im)
print("有 image 字段的条目:",len(imgs),"总条目",sum(len(c["prompts"]) for c in d["categories"]))
print("样例:")
for x in imgs[:8]: print("  ",repr(x)[:160])
print("类型统计:",collections.Counter(type(x).__name__ for x in imgs))
