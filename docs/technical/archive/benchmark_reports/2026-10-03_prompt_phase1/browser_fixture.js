(async () => {
    const {app} = await import('/scripts/app.js');
    if (app.graph._nodes.length) throw new Error('Use a new blank unsaved workflow');
    if (!window.__phase1Blocked) throw new Error('Write guard required');
    const add = (type, values = {}) => {
        const node = LiteGraph.createNode(type);
        if (!node) throw new Error(type + ' unavailable');
        app.graph.add(node);
        for (const [key, value] of Object.entries(values)) {
            const widget = node.widgets.find(w => w.name === key);
            if (!widget) throw new Error(key + ' unavailable');
            widget.value = value;
        }
        return node;
    };
    const positive = add('WeiLinPromptUI', {positive: 'adult traveler, blue coat, mountain path', auto_random: false, lora_str: ''});
    positive.title = '[00W-1P] QA 正向';
    const negative = add('CR Prompt Text', {prompt: 'blurry, low contrast'}); negative.title = '[00W-1N] QA 负向';
    const encode = add('CLIPTextEncode'), encodeNegative = add('CLIPTextEncode');
    const model = add('UNETLoader', {unet_name: 'Anima\\animayume_v15Base.safetensors'});
    const clip = add('CLIPLoader');
    const lora = add('Lora Loader (LoraManager)');
    const stack = add('Lora Stacker (LoraManager)');
    stack.lorasWidget.value = [{name: 'QA_traveler_v2', strength: 0.8, clipStrength: 0.8, active: true, expanded: false}, {name: 'QA_disabled', strength: 1, clipStrength: 1, active: false}];
    const sampler = add('KSampler', {cfg: 1, sampler_name: 'euler'});
    const latent = add('EmptyLatentImage', {width: 512, height: 512});
    const connect = (from, slot, to, name) => from.connect(slot, to, to.inputs.findIndex(i => i.name === name));
    connect(positive, 0, encode, 'text'); connect(negative, 0, encodeNegative, 'text');
    connect(model, 0, lora, 'model'); connect(clip, 0, lora, 'clip');
    // LoraManager creates its optional chain socket dynamically.
    if (!lora.inputs.some(i => i.name === 'lora_stack')) lora.addInput('lora_stack', 'LORA_STACK');
    connect(stack, 0, lora, 'lora_stack');
    connect(lora, 0, sampler, 'model'); connect(lora, 1, encode, 'clip'); connect(lora, 1, encodeNegative, 'clip');
    connect(encode, 0, sampler, 'positive'); connect(encodeNegative, 0, sampler, 'negative'); connect(latent, 0, sampler, 'latent_image');
    const branch = {id: 'qa-prompt', label: '中性隔离验收', nodeIds: app.graph._nodes.map(n => n.id)};
    app.graph.extra.uap_workbench = {activeBranch: branch.id, viewBranch: branch.id, branches: [branch]};
    const realFetch = window.fetch;
    window.__phase1MetadataCalls = [];
    window.fetch = function(input, options) {
        const url = String(input?.url || input);
        if (url.includes('/api/lm/loras/get-trigger-words?')) {
            window.__phase1MetadataCalls.push(url);
            if (window.__phase1MetadataError) return Promise.resolve(new Response(JSON.stringify({success: false}), {status: 409}));
            return Promise.resolve(new Response(JSON.stringify({success: true, trigger_words: ['traveler_v2', 'blue coat']}), {status: 200}));
        }
        return realFetch.call(this, input, options);
    };
    window.__phase1Fixture = {positive, sampler, stack, encode, model, branch, app};
    window.unifiedDailyControls.render(branch, true);
    window.unifiedDailyControls.show(true);
    return {nodeCount: app.graph._nodes.length, isolated: true};
})()
