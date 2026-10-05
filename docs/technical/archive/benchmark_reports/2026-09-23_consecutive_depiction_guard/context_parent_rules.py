"""Batch 44 rules: silhouette/profile, material simile and depicted-scene guards from round 131."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('metaphor_guard',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_metaphor_guard/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT}

# silhouette 作形体/风格名词（classic heroic silhouette）不推剪影光效；同文有真实光源词时保留。
SILHOUETTE_STYLE=r"\b(?:classic|heroic|iconic|stylized)\s+silhouette\b"
LIGHT_SUPPORT=r"\b(?:lighting|backlit|backlight|rim light|light source|sunlight|neon|candlelight|spotlight|glow\w*|lamps?|sunbeam\w*|light rays?)\b"

# 材质比喻（like flower petals）不证明独立植物。
FLOWER_SIMILE=r"\b(?:like|resembling|akin to)\s+(?:a\s+|the\s+)?(?:flower\s+petals?|petals?|flowers?|roses?|blossoms?)\b"
PLANT_SUPPORT=r"\b(?:flowers?|roses?|petals?|blossoms?|trees?|leaf|bouquet|vase|garden|forest|bamboo|mushrooms?|plants?|ivy|ferns?|grass|moss|thicket|bush|foliage)\b|\b(?:green|autumn|dry|fallen|maple|palm|broad|large)\s+leaves\b"

# 只有自然光、没有任何人工光源线索时，不补人工光与发光（撤回上游由 light 词误补的写法）。
ARTIFICIAL_SOURCE=r"\b(?:lamps?|lamplight|lamp light|neon|led\b|leds\b|spotlights?|studio lights?|studio lighting|candlelight|candles?|torches?|chandeliers?|fluorescent|streetlights?|city lights|light from the (?:screen|shop|phone)|screen light|phone light|glowing (?:eyes|screen|shelves|rim light)|bioluminescent|camera flash|fireworks?|fire glow|lighting fixtures?|light fixtures?|warm interior lighting|windows? with (?:faint |warm |interior )?light)\b"
NATURAL_LIGHT=r"\b(?:sunlight|sunshine|daylight|natural light|natural lighting|morning light|afternoon light|setting sun|sunbeams?)\b"

# 海报/画作/屏幕里描绘的天气不是实际环境（必须有描绘关系词，或画框内涵）。
DEPICTED_SCENE=(r"\b(?:posters?|paintings?|pictures?|photos?|photographs?|screens?|murals?|canvas|drawings?|portraits?)\b"
    r"[^.;!?]{0,20}\b(?:of|shows?|showing|displays?|displaying|depicts?|depicting|features?|featuring)\b"
    r"[^.;!?]{0,20}\b(?:snow|snowing|rain|raining|night|sunset|storm)\b"
    r"|\b(?:photo|picture|painting|drawing|portrait)\s+frames?\b[^.;!?]{0,25}\b(?:snow|snowing|rain|raining|night|sunset|storm)\b")
WEATHER_SUPPORT=r"\b(?:snow|snowing|snowstorm|rain|raining|storm|night|nighttime|sunset|sunlight|daylight|clouds?|overcast|fog|mist)\b"

REMOVALS=[
    ('光影效果',[SILHOUETTE_STYLE],LIGHT_SUPPORT,'Silhouette as a figure or style noun is not a lighting effect.'),
    ('植物与花园',[FLOWER_SIMILE],PLANT_SUPPORT,'Material simile, not an actual plant.'),
    ('天空与天气',[DEPICTED_SCENE],WEATHER_SUPPORT,'Weather depicted inside a picture is not the actual environment.'),
]

# 显式传统中式服装写法补传统与民族服饰；显式长刀写法补武器与装备。
TRADITIONAL_CHINESE=r"\btraditional chinese (?:clothing|costume|outfit|attire|dress)\b"
BLADE=r"(?<!shoulder )(?<!fan )(?<!razor )(?<!grass )\b(?:long|curved|jagged|ornate|giant|sharp)\s+blades?\b"
# 工具墙/工艺装置里的锯片、金属片不是武器。
BLADE_GUARD=r"\b(?:saw|tools?|metal|gears?|hooks?|discs?|fragments?|art wall|saw blades?)\b"


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body)).replace('; ', ', ')


def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive=_positive(body,refinements)
    node_parents={node['parent'] for node in refinements.REFINEMENT_NODES.values()}
    for parent,patterns,support,reason in REMOVALS:
        if parent not in parents:continue
        remaining=positive;cues=[]
        for pattern in patterns:
            cues.extend(match.group() for match in re.finditer(pattern,remaining,re.I))
            remaining=re.sub(pattern,' ',remaining,flags=re.I)
        if not cues:continue
        if re.search(support,remaining,re.I):continue
        if parent in node_parents and refinements.extract_refinements(remaining,[parent]):continue
        result[parent]={'false_cues':cues,'reason':reason}
    return result


def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    def want(parent,pattern,allowed=True):
        if parent in parents or parent in found:return
        if not allowed:return
        if re.search(pattern,positive,re.I):found.append(parent)
    want('传统与民族服饰',TRADITIONAL_CHINESE)
    blade_allowed=False
    for match in re.finditer(BLADE,positive,re.I):
        before=positive[max(0,match.start()-60):match.start()]
        if re.search(BLADE_GUARD,before,re.I):continue
        blade_allowed=True;break
    want('武器与装备',BLADE,allowed=blade_allowed)
    if '人工光与发光' in found and re.search(NATURAL_LIGHT,positive,re.I) and not re.search(ARTIFICIAL_SOURCE,positive,re.I):
        found.remove('人工光与发光')
    rejected=candidates(body,list(parents)+list(found),refinements)
    return [parent for parent in found if parent not in rejected]
