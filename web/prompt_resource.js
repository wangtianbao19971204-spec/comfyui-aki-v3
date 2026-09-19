import {formatEmbeddingReference} from './prompt_target.js';

export async function readModelPrompt(provider,filePath){
    if(!['loras','embeddings'].includes(provider))throw new Error('该模型类型没有可插入的提示词。');
    const response=await fetch(`/api/lm/${provider}/prompt-resource?file_path=${encodeURIComponent(filePath)}`,{cache:'no-store'});
    const result=await response.json();if(!response.ok||!result.success)throw new Error(result.error||'模型已不可用，请刷新列表。');
    if(provider==='embeddings')return formatEmbeddingReference(result.resource.relative_path);
    const text=result.resource.trained_words.join(', ');if(!text.trim())throw new Error('这个模型没有触发词，请先在模型详情中编辑。');return text;
}

export async function queuePromptResource(resource){
    const owner=window.unifiedQueuePrompt?window:window.parent?.unifiedQueuePrompt?window.parent:window.opener;
    if(!owner?.unifiedQueuePrompt)throw new Error('请从 ComfyUI 的统一工作台打开资源后再加入待用列表。');
    return owner.unifiedQueuePrompt(resource);
}
