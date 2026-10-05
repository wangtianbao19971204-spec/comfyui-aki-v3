// Static text inspection only. Never execute a graph node to obtain a preview.
const textWidget=(node,name)=>node?.widgets?.find(widget=>widget.name===name&&typeof widget.value==='string');

export function inspectStaticPromptInputs(graph,branch){
    if(!graph||!branch)return [];
    const members=new Set(branch.nodeIds.map(String));
    const nodes=branch.nodeIds.map(id=>graph.getNodeById(id)).filter(Boolean);
    const rows=[];
    for(const node of nodes){
        const type=node.comfyClass||node.type;
        if(!['CLIPTextEncode','Krea2EditGroundedEncode'].includes(type))continue;
        const field=type==='CLIPTextEncode'?'text':'prompt';
        const label=`${node.title||type} #${node.id} / ${field}`;
        if(node.mode!=null&&node.mode!==0){rows.push({node,label,status:'disabled',reason:'编码节点未启用'});continue;}
        const input=node.inputs?.find(port=>port.name===field);
        if(input?.link==null){
            const widget=textWidget(node,field);
            rows.push(widget?{node,label,status:type==='CLIPTextEncode'?'static':'source',
                              text:widget.value,source:label,
                              reason:type==='CLIPTextEncode'?'直接字段：编码前文本已确认':'编辑指令字段原文；图片与系统指令仍由运行时合成'}:
                             {node,label,status:'unknown',reason:'找不到可读的文本字段'});
            continue;
        }
        const link=graph.links?.[input.link],source=link&&graph.getNodeById(link.origin_id);
        if(!source||!members.has(String(source.id))||source.mode!=null&&source.mode!==0){
            rows.push({node,label,status:'unknown',reason:'上游文本来源不存在、跨分支或未启用'});continue;
        }
        const sourceType=source.comfyClass||source.type;
        if(type==='CLIPTextEncode'&&sourceType==='CR Prompt Text'&&link.origin_slot===0&&
           source.inputs?.find(port=>port.name==='prompt')?.link==null){
            const widget=textWidget(source,'prompt');
            if(widget){rows.push({node,label,status:'static',text:widget.value,
                                  source:`${source.title||sourceType} #${source.id} / prompt`,
                                  reason:'纯文本传递：编码前文本已确认'});continue;}
        }
        rows.push({node,label,status:'unknown',sourceNode:source,
                   reason:`${sourceType} 需运行后才能确定输出；这里只显示静态支持范围`});
    }
    return rows;
}
