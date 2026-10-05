(function createT06ValueReader(app, options) {
  const {expectedGraphId, baseline, inputElement, nodeId=1063, widgetName='positive', sideNodeId=1030, sideWidgetName='text'}=options;
  const graph=app.graph, branch=graph?.extra?.uap_workbench?.activeBranch;
  if (!expectedGraphId || graph?.id!==expectedGraphId) throw Error('T06 requires the identified isolated workflow');
  const node=graph.getNodeById(nodeId), widget=node?.widgets?.find(item=>item.name===widgetName);
  const sideNode=graph.getNodeById(sideNodeId), sideWidget=sideNode?.widgets?.find(item=>item.name===sideWidgetName);
  if (!widget || !sideWidget || !String(baseline).startsWith('M9B synthetic ')) throw Error('T06 isolated target is missing');
  if (String(widget.value)!==baseline || typeof inputElement?.value!=='string' || inputElement.value!==baseline || !inputElement.isConnected) throw Error('T06 node/input baseline mismatch');
  if (node.inputs?.some(input=>(input.widget?.name||input.name)===widgetName && input.link!=null)) throw Error('T06 target is driven by a link');
  const sideBaseline=String(sideWidget.value ?? '');
  const readableNativeInput=()=>[widget.inputEl,widget.element,widget.input].find(input=>typeof input?.value==='string');
  const read=()=>{
    const valid=app.graph===graph && graph.id===expectedGraphId && graph.extra?.uap_workbench?.activeBranch===branch &&
      graph.getNodeById(nodeId)===node && node.widgets.includes(widget) && graph.getNodeById(sideNodeId)===sideNode && sideNode.widgets.includes(sideWidget) && inputElement.isConnected;
    const nativeInput=readableNativeInput();
    return {valid,graph_id:graph.id,branch,node_id:nodeId,widget:widgetName,node_value:String(widget.value ?? ''),
      bound_input_value:inputElement.value,bound_input_connected:inputElement.isConnected,
      bound_input_visible:!inputElement.closest('[hidden],[inert]') && inputElement.getClientRects().length>0,
      native_input_value:nativeInput?.value ?? null,side_node_id:sideNodeId,side_value:String(sideWidget.value ?? ''),side_unchanged:String(sideWidget.value ?? '')===sideBaseline};
  };
  return {read,ready:expected=>{
    const state=read();
    return state.valid && state.side_unchanged && state.node_value===expected && state.bound_input_value===expected;
  },baseline,sideBaseline};
})
