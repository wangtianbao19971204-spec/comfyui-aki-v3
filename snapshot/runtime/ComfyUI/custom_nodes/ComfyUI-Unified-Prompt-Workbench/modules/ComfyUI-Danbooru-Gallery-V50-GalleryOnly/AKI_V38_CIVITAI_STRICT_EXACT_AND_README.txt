AKI V38 - Civitai strict 精确 AND 版

本版修复：
1. strict 模式不再使用宽泛 substring 判断。
   - 2girls 不再命中 2girls1boy。
   - sex 不再命中 sexual。
2. loose 模式仍保留宽松相关性排序。
3. sexfrombehind / sex_from_behind / sex from behind 等常见紧凑 tag 仍按精确短语互通。

使用：
- 2girls sex：严格，必须两个词都以精确 token/tag/phrase 命中。
- loose 2girls sex：宽松，按相关性排序。
