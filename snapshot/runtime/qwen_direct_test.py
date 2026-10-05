import base64
import io
from pathlib import Path

from PIL import Image
from llama_cpp import Llama
from llama_cpp.llama_chat_format import Qwen3VLChatHandler

MODEL = r"G:\ComfyUI-aki-v3\ComfyUI\models\LLM\Qwen3-VL-8B-Instruct-abliterated-v2.0.Q6_K.gguf"
MMPROJ = r"G:\ComfyUI-aki-v3\ComfyUI\models\LLM\Qwen3-VL-8B-Instruct-abliterated-v2.0.mmproj-f16.gguf"

# 自动找 ComfyUI/input 或 temp 里最近的一张图，避免路径写错
roots = [
    Path(r"G:\ComfyUI-aki-v3\ComfyUI\input"),
    Path(r"G:\ComfyUI-aki-v3\ComfyUI\temp"),
]
suffixes = {".png", ".jpg", ".jpeg", ".webp"}
images = []

for root in roots:
    if root.exists():
        images.extend([p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes])

if not images:
    raise FileNotFoundError("没有在 ComfyUI/input 或 ComfyUI/temp 找到 png/jpg/webp 图片。")

IMAGE = max(images, key=lambda p: p.stat().st_mtime)
print("Using image:", IMAGE)

print("Loading Qwen3VL handler...")
handler = Qwen3VLChatHandler(clip_model_path=MMPROJ)

print("Loading model on CPU for isolation test...")
llm = Llama(
    model_path=MODEL,
    chat_handler=handler,
    n_ctx=8192,
    n_gpu_layers=0,   # CPU 测试，先排除 CUDA/GPU offload 问题
    verbose=True,
)

print("Preparing image...")
img = Image.open(IMAGE).convert("RGB")
img.thumbnail((512, 512))

buf = io.BytesIO()
img.save(buf, format="PNG")
data = base64.b64encode(buf.getvalue()).decode("utf-8")
image_url = "data:image/png;base64," + data

print("Running Qwen3VL completion. CPU 模式可能需要等几分钟...")
resp = llm.create_chat_completion(
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image in 10 concise English visual tags."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ],
    max_tokens=64,
    temperature=0.2,
)

print("\nRESULT:")
print(resp["choices"][0]["message"]["content"])