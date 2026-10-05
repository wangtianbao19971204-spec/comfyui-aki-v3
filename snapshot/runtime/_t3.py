import json,sys,re
sys.stdout.reconfigure(encoding="utf-8")
p=r"ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\prompt_selector\data.json"
d=json.load(open(p,encoding="utf-8"))
print("top keys:",list(d.keys())[:20])
c=d["categories"]
print("categories:",len(c))
def keys(x,n=0):
    return list(x.keys())
print("cat keys:",keys(c[0]))
print("prompt keys:",keys(c[0]["prompts"][0]))
