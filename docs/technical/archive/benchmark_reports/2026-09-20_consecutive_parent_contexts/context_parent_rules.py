"""Conservative batch repair: require an identified false cue and no other evidence.

Returns candidates for an auditable data migration, not runtime deletions.
"""
import re

SUPPORT = {
    '头发与发型': r'\b(?:hair|hairstyle|bangs|braids?|ponytail|twintails|ahoge|bald|dreadlocks|sidelocks|bun)\b|头发|发型|刘海|马尾|辫',
    '绘画与插画': r'\b(?:illustration|paint(?:ing|erly)?|drawing|drawn|sketch|pencil|gouache|acrylic|watercolor|watercolour|artwork|concept art|digital art)\b|绘画|插画|数字画|画作',
    '移动与运动': r'\b(?:walk(?:ing|s)?|run(?:ning|s)?|jump(?:ing|s)?|fly(?:ing)?|float(?:ing|s)?|swim(?:ming|s)?|danc(?:ing|e|es)|crawl(?:ing|s)?|stretch(?:ing|es)?|fall(?:ing|s)?|climb(?:ing|s)?|rid(?:ing|e|es)|cycl(?:ing|e)|skat(?:ing|e)|skiing|wrestling|yoga|contortion|dynamic pose|in (?:the )?air|sport|sports|motion|movement)\b|奔跑|跑步|走路|游泳|跳舞|飞行|运动',
    '持物与道具互动': r'\b(?:hold(?:ing|s)?|carr(?:ying|ies)|grasp(?:ing|s)?|grip(?:ping|s)?|clutch(?:ing|es)?|grab(?:bing|s)?|playing (?:an? )?(?:instrument|guitar|piano|violin)|drink(?:ing|s)?|eat(?:ing|s)?|cook(?:ing|s)?|read(?:ing|s)?|smok(?:ing|es?)|using)\b|手持|拿着|持物|骑乘|吃饭|喝|吃|读书|弹琴',
    '视角与透视': r'\b(?:pov|profile|angle|from (?:above|below|behind|back|(?:the )?side|front)|straight[ -]on|dutch angle|fisheye|perspective|foreshortening|bird.?s[ -]eye|(?:low|high|overhead|downward|upward|eye.level)[ -]angle|top[ -]down|(?:above|below|front|side|back|rear|top|bottom|overhead) view|view from|ground level)\b|视角|透视|俯视|仰视|第一人称',
    '自然地貌与水域': r'\b(?:outdoors?|nature|landscape|mountains?|beach|ocean|sea|river|lake|waterfall|desert|cave|valley|countryside|field|water|underwater|lava|ice|snowflake|grasslands|riverside|embankment|underground|meadow|shoreline|pool|pond|coast|terrain)\b|海|湖|河|山|沙漠|地貌',
    '职业与身份': r'\b(?:maid|nurse|doctor|soldier|police|officer|firefighter|lifeguard|teacher|student|nun|priest|monk|samurai|ronin|knight|ninja|witch|wizard|magician|idol|dancer|waitress|waiter|chef|farmer|pirate|princess|queen|king|prince|office lady|businessman|scientist|mechanic|athlete|detective|pilot|astronaut|miko|performer)\b|职业|女仆|护士|医生|士兵|警察|学生',
    '光影效果': r'\b(?:light(?:ing)?|sunlight|shadow|shadows|shade|shaded|glow|glowing|silhouette|contrast|chiaroscuro|bloom|backlight|rimlight|exposure|illumination|sparkle|volumetric|occlusion)\b|光|影',
    '制服与职业装': r'\b(?:uniform|suit|formal|blazer|apron|scrubs|maid|police|military|nurse|school|sailor)\b|制服|职业装|西装|水手服|校服',
    '动漫与卡通': r'\b(?:anime|cartoon|chibi|cel shading|toon|animation|animated)\b|动漫|卡通|二次元|赛璐璐|Q版',
    '拥抱与日常互动': r'\b(?:hug(?:ging|s)?|embrac(?:e|ing|es)|holding hands|handshake|handshaking|patting|headpat|talk(?:ing)?|conversation|feeding|carrying (?:a )?(?:person|girl|boy|woman|man))\b|拥抱|牵手|交谈|抚头',
}

BAD = {
    '头发与发型': [r'\b(?:pubic|facial|body|armpit|leg) hair\b'],
    '绘画与插画': [r'\b(?:draw(?:ing|s)?|drew)\s+(?:the\s+)?(?:eye|eyes|attention|focus|viewer|gaze)\b'],
    '移动与运动': [r'\bthe walking dead\b',r'\b(?:lean(?:ing|s)?|sleep(?:ing|s)?|curled up)\b',r'\b(?:hand|rod|railing|rail|road|path|line|water|sweat|tears|blood)\s+(?:\w+ly\s+)?(?:runs|running)\b'],
    '持物与道具互动': [r"\b(?:holding|grabbing|gripping)\s+(?:(?:another|own|her|his|their|your|one's|another's|girl's|boy's)\s+)?(?:hands?|arms?|legs?|head|breasts?|hips?|waist|hair|wrists?)\b",r"\bholding\s+(?:another(?=\s*(?:;|$))|(?:a |the )?(?:girl|boy|woman|man|person)(?!['’])|(?:her|his|their|your) breath)\b"],
    '视角与透视': [r'\b(?:sex|hug|hugging|grabbing|embracing) from behind\b',r'\bfrom behind (?:her|his|their) ear\b'],
    '自然地貌与水域': [r'\bstar ocean\b',r'\b(?:ocean|sea) blue\b',r'\bwater (?:droplets?|bottles?|drinks?)\b',r'\bice cream\b'],
    '职业与身份': [r'\bthe king of fighters\b'],
    '光影效果': [r'\bshadow of the colossus\b'],
    '制服与职业装': [r'\bbitch suit\b'],
    '拥抱与日常互动': [r'\b(?:hug(?:ging|s)?|embrac(?:e|ing|es))\s+(?:her|his|their|the)\s+(?:curves|body|figure|silhouette|hips|thighs)\b'],
}

def candidates(body, parents, refinements):
    parts=refinements._positive_parts(body)
    # Artist identifiers and named work qualifiers cannot provide visual cues.
    positive='; '.join(p for p in parts if not p.startswith(('artist:', '@')))
    results={}
    for parent in parents:
        if parent not in BAD: continue
        remaining=positive
        cues=[]
        for pattern in BAD[parent]:
            if parent=='持物与道具互动' and re.search(r'\b(?:severed|disembodied) head\b',positive):
                pattern=pattern.replace('|head|','|')
            for match in re.finditer(pattern,remaining): cues.append(match.group())
            remaining=re.sub(pattern,' ',remaining)
        if parent=='视角与透视':
            for part in parts:
                for match in re.finditer(r'\bfrom (?:above|below|behind|(?:the )?side)\b',part):
                    if not refinements._phrase_allowed(parent,match.group(),part,match.start(),match.end()):
                        cues.append(match.group())
                        remaining=remaining.replace(part,part[:match.start()]+' '+part[match.end():])
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            results[parent]={'false_cues':cues,'reason':'All detected cues for this parent have a different contextual meaning; no independent supporting cue remains.'}
    if '动漫与卡通' in parents and re.search(r'\b(?:anime|cartoon|chibi|cel shading)\b',body,re.I) and not re.search(SUPPORT['动漫与卡通'],positive,re.I):
        results['动漫与卡通']={'false_cues':['nonpositive animation terms'],'reason':'Animation terms occur only in excluded nonpositive text.'}
    return results
