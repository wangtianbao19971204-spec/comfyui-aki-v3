"""Batch 22 rules: prose-scene recall plus referent guards from rounds 105-108."""
import importlib.util
from pathlib import Path
import re

spec=importlib.util.spec_from_file_location('attribute_relations',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_attribute_relations/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
RECALL=previous.RECALL
FALSE_CUES={
 # the body's / her silhouette 是轮廓，不是剪影光效
 '光影效果':r"\b(?:body's|figure's|his|her|its|their|your)\s+silhouette\b|\bhighlight(?:s|ing)?\s+the\s+(?:[a-z'-]+\s+){0,3}silhouette\b|\b(?:full|entire)\s+silhouette\b",
 # holding 的主语是轮廓、版面或器物时不是人物持物
 '持物与道具互动':r"\b(?:contour|outline|boundary|border|edge|line|frame|panel|layout|design|composition|print|shape|fabric|drape|garment|texture)\b[^.!?;]{0,30}\bholding\b|\bholding the (?:entire|whole)\b",
 # 图像叙事/线稿语境里的 realism 不证明摄影写实
 '摄影与写实':r"\bgraphic storytelling\b|\bdraftsmanship\b|\brefined linework\b|\b(?:comic|manga|linework|draftsmanship)[^.!?;]{0,60}\brealism\b|\brealism[^.!?;]{0,60}\b(?:comic|manga|linework|draftsmanship)\b",
 # 发饰/挂件上的蝴蝶或假耳不证明独立动物主体
 '动物主体':r"\bbutterfly (?:hair ?(?:pin|clip)|ornament|necklace|earrings?|pendant|brooch)\b|\bfake (?:animal )?ears?\b",
 # 仿毛领、毛边是衣料，不是真实兽人特征
 '非人特征':r"\bfaux fur\b|\bfur (?:stole|collar|trim|hem|scarf)\b|\bfur-trimmed\b|\bfur trimmed\b",
 # 石材/木构地面与台阶属于建筑设施，不是天然地貌
 '自然地貌与水域':r"\b(?:stone|tile|marble|cement|concrete|wooden|brick)[- ]?(?:floor|paving|paved|patio)\b|\b(?:stone|concrete|wooden) (?:steps?|staircase|stairs|wall|blocks?)\b|\bbrick-paved\b",
 # cheerful 修饰图形风格时不作为人物神情
 '喜悦与微笑':r"\bcheerful\b[^.!?]{0,30}?\b(?:graphic|design|style|charm|illustration|punchy)\b",
}
PROTECTIONS={
 '光影效果':r"\b(?:backlit|backlight(?:ing)?|against the light|silhouette against|contre-jour|hidden in the shadows?|light and shadow|light (?:shines|streams|comes|from)|natural light)\b",
 '持物与道具互动':r"\b(?:holding|holds?|clutch\w*|grip\w*|carrying)\b[^.!?;]{0,24}\b(?:hand|hands|arm|arms|fingers)\b",
 '摄影与写实':r"\b(?:photograph\w*|photo|photoreal\w*|dslr|camera|lens|film still|shot on)\b",
 '动物主体':r"\b(?:real|live|actual|a|an|the) (?:butterfly|moth)\b|\bbutterfly (?:flying|landed|resting|wings)\b",
 '非人特征':r"\b(?:real|actual|own) fur\b|\bfurry (?:body|chest|legs|arms|tail|ears)\b|\bfur[- ]covered\b",
 '服装材质与剪裁':r"\b(?:tulle|corset|embroidered|semi[- ]transparent|lacy|plaid|pleated|blouse|bra|bodysuit|gown|dress|skirt|thigh-high boots?)\b",
 '喜悦与微笑':r"\b(?:smil\w+|grin\w*|laugh\w*|joy\w*|happy|smirk\w*)\b",
}
PLANT=r"\b(?:tulips?|chrysanthemums?|hydrangeas?|ivy|ferns?|shrubs?|bushes? with (?:large |thick )?leaves|bouquet of\b[^.;]{0,40}\b(?:flowers?|tulips?|roses?|blooms?)|wheat stalks?|plant decor|green plants|clusters of\b[^.;]{0,60}\bflowers?|blooming plum)\b"
LAND=r"\b(?:seaside|coastline|shore|beach|rocky path|river|stream|sea|ocean|lake|cliff|rolling hills?|mountains?|valley|dunes?|canyon|meadow|forest|standing water|water surface|pond|pool|fountain|onsen|hot springs?)\b"
LAND_SIMILE=re.compile(r"\b(?:like|as if|resembl\w+|reminiscent of|depict\w*|paint\w*|illustration|screen|poster|photo of|painting)\b[^.!?;]{0,30}$",re.I)

def _landform_present(positive):
    for match in re.finditer(LAND,positive,re.I):
        before=positive[max(0,match.start()-40):match.start()]
        after=positive[match.end():match.end()+24]
        if LAND_SIMILE.search(before):continue
        if re.match(r"\s+(?:wind|breeze)\b",after,re.I):continue
        return True
    return False
# Cues whose referent is decided by whole-body context; the node layer cannot see that context.
HARD_CUES={'摄影与写实'}
PLANT_GUARD=re.compile(r"\b(?:pattern|print|printed|embroidery|embroidered|motif|decor(?:ative|ated)|tattoo|sticker|logo|icon|wallpaper)\b",re.I)
BUILDING=r"\b(?:buildings?|corridors?|hallways?|metal columns?|stone columns?|stone (?:steps?|wall|blocks?|bench)|brick-paved|wooden (?:structure|ruins?|lattice|railing|fence|beams?)|high-rises?|glass-and-metal|floor-to-ceiling window|arch bridge|stone arch|towers?|handrails?|balcon(?:y|ies)|sliding door|window frames?|signs? on the wall|emergency slide housing)\b"
DOF=r"\b(?:softly blurred|soft-blurred|background (?:is |was )?blurred|blurred background|background blur|blurring the background|out of focus|defocused)\b"
PALETTE=r"\b(?:color palette|colour palette|palette|color scheme|colour scheme|dominated by (?:dark|warm|cool|neutral|black|white)|tones? of (?:black|white|gray|grey|warm|cool|neutral|beige)|colou?rs? (?:are |is |were |was )?(?:mainly|mostly)|overall (?:tone|tones|palette|color|colour))\b"
COVER=r"\b(?:baring (?:her|his|their) (?:breasts?|chest|crotch)|fully exposing (?:her|his|their)|(?:one )?exposed breast|reveal(?:ing|s)? (?:her|his|their) (?:bare )?(?:breasts?|chest|nipples?|pussy|thigh)|slipping off (?:one|her|his) shoulder|hang(?:ing)? open|fall(?:ing)? off one shoulder|unbuttoned to reveal)\b"
HOLD=r"\b(?:holds?|held|holding|clutch\w*|grip(?:s|ping)?|carry(?:ing|ies)|grabbing)\b[^.!?;]{0,30}\b(?:a|an|the|her|his|their|two|small|white|black|brown|gold|cream|ornate)\b"
GESTURE=r"\b(?:fingers? (?:on|touch\w*|press\w*)|hands? (?:crossed|folded|resting|rests?|on) |hand (?:reaches?|lifts?|gripping|rests?|press\w*)|leaning (?:slightly )?forward|head (?:tilted|turned)|turns? to look|hand up|raise (?:your|her|his|the) (?:right|left) ?arm|bring (?:your|her|his|the) hand|let (?:your|her|his) (?:left|right) arm hang|turn (?:your|her|his|the) body)\b"
SELF=r"\b(?:fingers?[^.!?;]{0,40}\b(?:into|inside)\b[^.!?;]{0,30}\b(?:her|his|their) own\b|(?:her|his) own (?:pussy|anus|vagina|crotch)\b[^.!?;]{0,40}\bfingers?\b|self-fingering|fingering herself|pushes? (?:a|two|her|his) (?:toy|finger)\b[^.!?;]{0,40}\b(?:into|inside)\b|pressing (?:a|the|two) (?:toy|fingers?|dildo)\b|(?:toy|fingers?|hand)\b[^.!?;]{0,40}\binto (?:her|his|their) own\b|masturbat\w*|solitary pleasure|fingers working toward)\b"
FLUID=r"\b(?:sweat(?:y|ing)?|sweat-glistened|love juices|squirt\w*|pussy juice)\b"
WEAR=r"\b(?:unbuttoned|off[- ]shoulder|loosely unbuttoned|dress tug|strap slip|bra strap|hem (?:slightly )?lifted|lifted by her hand|partially clothed|partly clothed|hang(?:ing)? open|fall(?:ing)? off one shoulder)\b"
HEADWEAR=r"\b(?:veil|bonnet|head ?scarf)\b"
SIT=r"\b(?:sits? (?:sideways|on|at|by|in|down|up)|sitting|seated|squatting|crouching|wariza)\b"
FRAMING=r"\b(?:medium (?:shots?|perspective|framing|view)|mid[- ]shot|cowboy shots?|close[- ]ups?|upper body|full body|portrait shot)\b"
ARTLIGHT=r"\b(?:lighting fixtures?|sconces?|wall lamps?|table lamps?|candlelight|neon lights?|light fixture)\b"
SORROW=r"\b(?:sorrow\w*|melanchol\w*|wistful\w*|tearful|somber|mournful)\b"
FABRIC=r"\b(?:sheer fabric|translucent fabric|semi[- ]transparent (?:fabric|material|effect)|fabric wrinkles|ruffled (?:trim|details|hem)|woven belt|knit textures?|delicate texture)\b"
LAYOUT=r"\b(?:cent(?:er|re)(?:ed)? composition|slightly (?:to the )?(?:right|left) of (?:the )?(?:frame|center)|off[- ]center|diagonal line|frame within a frame|letterboxed|rule of thirds|negative space|foreground|midground)\b"
EXPRESSION=r"\b(?:half[- ]lidded|half[- ]closed eyes?|parted lips|tongue out|expressionless|no expression)\b"
GAZE=r"\b(?:gazing (?:into the distance|away|upward|downward|wistfully)|looks? (?:directly |straight |back )?at the (?:camera|lens|viewer)|gazes? (?:directly |wistfully )?(?:at|toward|into|upward|downward)|turns? to look back at)\b"
FOOTWEAR=r"\b(?:strappy|pointed|glossy|stiletto|spiked|block|kitten|high)[- ]heels?\b|\bshe wears [^.;]{0,24}heels?\b"
BODY=r"\b(?:voluptuous|smooth (?:pale |fair )?skin|skin is (?:pale|smooth))\b"
DAYLIGHT=r"\b(?:sunshine|sunlit|golden (?:sunshine|sunlight|hour)|natural light)\b"
COMIC=r"\b(?:linework|line art|draftsmanship|graphic storytelling|comic|manga)\b"
STYLE=r"\b(?:graphic storytelling|aesthetics|artistic (?:style|individuality)|reminiscent of|inspired by|influenced by)\b"

def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))

def _plant_allowed(positive):
    match=re.search(PLANT,positive,re.I)
    if not match:return False
    window=positive[max(0,match.start()-80):match.end()+80]
    return not PLANT_GUARD.search(window)

PALETTE_GUARD=re.compile(r'\b(?:canvas|easel|paint ?brush(?:es)?|oil paint|paints?|smock|splotch\w*|turpentine|palette knife)\b',re.I)
HOLD_GUARD=re.compile(r'\bholds?\s+(?:down|up|open|together|still|back|in|out)\b',re.I)
DAYLIGHT_GUARD=re.compile(r'\s+(?:pink|white|red|blue|green|transitions?|balance|shade|tones?|colou?rs?)\b',re.I)

def _palette_allowed(positive):
    match=re.search(PALETTE,positive,re.I)
    if not match:return False
    window=positive[max(0,match.start()-100):match.end()+100]
    return not PALETTE_GUARD.search(window)

def _hold_allowed(positive):
    match=re.search(HOLD,positive,re.I)
    if not match:return False
    window=positive[max(0,match.start()-60):match.end()+60]
    if HOLD_GUARD.search(window):return False
    if re.search(r"\b(?:table|desk|vase|basket|tray|shelf|rack|stand|wall|surface|container|cupboard|hook|frame|tree|branch|cart|box|bed|sofa)\b[^.!?;]{0,24}\b(?:holds?|holding)\b",positive,re.I):
        return False
    if re.search(r"\b(?:holds?|holding|clutch\w*|grip(?:s|ping)?|carry(?:ing|ies)|grabbing)\s+(?:\w+\s+){0,2}(?:breasts?|chest|waist|hips?|thighs?|legs?|arms?|hands?|head|wrists?|shoulders?|neck|face|jaw|chin|knees?)\b",positive,re.I):
        return False
    return True

def _framing_allowed(positive):
    if re.search(r"\bfull[- ]body tattoo\b",positive,re.I):return False
    return True

def _sorrow_allowed(positive):
    for match in re.finditer(SORROW,positive,re.I):
        before=positive[max(0,match.start()-40):match.start()]
        window=positive[max(0,match.start()-60):match.end()+60]
        if re.search(r'\bmedicine\s+$',before,re.I):continue
        if re.search(r'\b(?:expression|face|facial|eyes?|gaze|smile|smirk|look|lips|mood|countenance|tears?|crying)\b',window,re.I):
            return True
    return False

def _comic_allowed(positive):
    for match in re.finditer(COMIC,positive,re.I):
        after=positive[match.end():match.end()+16]
        if re.match(r"\s*\(object\)|\s+object\b",after,re.I):continue
        return True
    return False

def _daylight_allowed(positive):
    match=re.search(DAYLIGHT,positive,re.I)
    if not match:return False
    if match.group(0).lower().startswith('natural light') and DAYLIGHT_GUARD.match(positive[match.end():match.end()+24]):
        return False
    return True

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive=_positive(body,refinements)
    for parent,pattern in FALSE_CUES.items():
        if parent not in parents:continue
        if not re.search(pattern,positive,re.I):continue
        if parent=='自然地貌与水域' and _landform_present(positive):continue
        protection=PROTECTIONS.get(parent)
        if protection and re.search(protection,positive,re.I):continue
        if parent in HARD_CUES:
            result[parent]={'reason':'Style or medium context overrides the isolated keyword; no photographic evidence in the full text.'}
            continue
        remaining=re.sub(pattern,' ',positive,flags=re.I)
        if remaining==positive:continue
        node_evidence=bool(refinements.extract_refinements(positive,[parent]))
        if node_evidence:
            result.pop(parent,None)
        else:result[parent]={'reason':'False cue (contour, layout, garment material, ornament or style descriptor) with no node-level evidence left after removing it.'}
    for parent,pattern in PROTECTIONS.items():
        if parent in result and re.search(pattern,positive,re.I):result.pop(parent)
    return result

def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    vetoed=[]
    for parent in list(found):
        pattern=FALSE_CUES.get(parent)
        if not pattern:continue
        if not re.search(pattern,positive,re.I):continue
        if parent=='自然地貌与水域' and _landform_present(positive):continue
        protection=PROTECTIONS.get(parent)
        if protection and re.search(protection,positive,re.I):continue
        if parent in HARD_CUES:vetoed.append(parent);continue
        remaining=re.sub(pattern,' ',positive,flags=re.I)
        if remaining!=positive and not refinements.extract_refinements(positive,[parent]):vetoed.append(parent)
    found=[p for p in found if p not in vetoed]
    def want(parent,pattern,guard=None):
        if parent in parents or parent in found:return
        if not re.search(pattern,positive,re.I):return
        if guard is not None and not guard(positive):return
        found.append(parent)
    want('植物与花园',PLANT,guard=_plant_allowed)
    want('建筑与设施',BUILDING)
    want('焦点与景深',DOF)
    want('色彩与调色',PALETTE,guard=_palette_allowed)
    want('裸露与遮盖',COVER)
    want('持物与道具互动',HOLD,guard=_hold_allowed)
    want('手势与肢体动作',GESTURE)
    want('自慰',SELF)
    want('射精与体液',FLUID)
    want('穿着状态',WEAR)
    want('头饰与发饰',HEADWEAR)
    want('坐姿与蹲姿',SIT)
    want('景别与主体占比',FRAMING,guard=_framing_allowed)
    want('人工光与发光',ARTLIGHT)
    want('悲伤与哭泣',SORROW,guard=_sorrow_allowed)
    want('服装材质与剪裁',FABRIC)
    want('布局与画面结构',LAYOUT)
    want('眼口表情',EXPRESSION)
    want('视线方向',GAZE)
    want('鞋袜与腿饰',FOOTWEAR)
    want('体型与肤色',BODY)
    want('自然光',DAYLIGHT,guard=_daylight_allowed)
    want('漫画与线稿',COMIC,guard=_comic_allowed)
    want('艺术流派与视觉风格',STYLE)
    want('束缚与控制',r"\bchained\b")
    want('作品角色',r"\b(?:exodia|duel monster)\b")
    rejected=candidates(body,parents+found,refinements)
    return [p for p in found if p not in rejected]
