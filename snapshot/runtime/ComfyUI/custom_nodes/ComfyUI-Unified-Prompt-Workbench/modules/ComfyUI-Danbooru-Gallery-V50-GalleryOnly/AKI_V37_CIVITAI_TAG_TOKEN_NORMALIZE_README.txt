AKI V37 - Civitai tag/token normalize

修复：
1. Civitai 搜索支持中文全角逗号、顿号、中文分号：
   2girls，sex / 2girls、sex / 2girls;sex 都会拆成两个词。
2. 支持常见紧凑 tag 同义词：
   sexfrombehind -> sex_from_behind / sex from behind
   longhair -> long_hair / long hair
   bluehair 等同类 hair/eyes 简写。
3. strict 仍然默认要求所有词命中；loose 仍然显式宽松。
