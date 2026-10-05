"""Offline repair candidates require a false cue and no independent support."""
import importlib.util
from pathlib import Path
import re

spec=importlib.util.spec_from_file_location('previous_parent_contexts',Path(__file__).resolve().parent.parent/'2026-09-20_consecutive_parent_contexts/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
BAD={
    '制服与职业装':[r'\b(?:mobile|space|diving|wet|swim|track|bathing|body|cat|flight) suit\b'],
    '城市与街道':[r'\b(?:urban\s+)?street(?:\s+style|wear)\b'],
    '天空与天气':[r'\brain (?:boots?|coats?|jackets?|shoes?)\b'],
    '战斗与施法':[r'\bcombat (?:boots?|pants?|trousers?|uniform|gear)\b'],
    '种族与幻想生物':[r'\bfairy tales?\b',r'\bfairy lights?\b'],
    '愤怒与不满':[r'\b(?:playful|inviting|sensual|seductive|cute)(?:[ -]+\w+){0,2}\s+pout\b'],
    '持物与道具互动':[r"\b(?:holding|grabbing|gripping)\s+(?:(?:another|own|her|his|their|your|one's|another's)\s+)?(?:testicles?|penis|crotch|butt|ass|neck|shoulders?|feet|foot|fingers?|chest)\b"],
}
SUPPORT={**previous.SUPPORT,
    '城市与街道':r'\b(?:city|cities|urban|street|road|alley|town|village|skyline|downtown|crosswalk|sidewalk|intersection|storefront)\b|\bfront of\b[^.;]{0,70}\b(?:shop|store)\b|城市|街道|村庄|小镇',
    '天空与天气':r'\b(?:sky|clouds?|rain(?:ing|y)?|snow(?:ing|y)?|storm|fog|mist|sunset|sunrise|night|moon|stars?|wind|windy|weather|rainbow|thunder|lightning)\b|天空|天气|下雨|雪|月亮|夜晚',
    '战斗与施法':r'\b(?:combat|battle|fight(?:ing)?|attack|punch(?:ing)?|kick(?:ing)?|spell|magic|casting|shooting|duel)\b|战斗|施法|攻击|挥剑|魔法',
    '种族与幻想生物':r'\b(?:fairy|elf|elves|demon|angel|dragon|monster|zombie|ghost|undead|vampire|mermaid|android|robot|slime|goblin|orc|oni|succubus|incubus|pokemon|arachne|centaur|taur)\b|精灵|天使|恶魔|妖怪|魔物',
    '愤怒与不满':r'\b(?:angry|anger|annoyed|irritated|frown|frowning|scowl|scowling|pout|pouting|displeased|disgust|furious)\b|愤怒|不满|皱眉|生气',
    '亲密互动':r'\b(?:kiss(?:ing|es)?|hetero|yuri|yaoi|couple|romantic|intimate|groping|fondling|licking|embracing|sex)\b|亲吻|接吻|亲密|情侣',
    '头饰与发饰':r'\b(?:hat|cap|crown|tiara|headband|hairband|headdress|bow|hair (?:clip|ornament|ribbon|flower)|veil|helmet|beret|bonnet)\b|头饰|发饰|帽|发带|发箍',
}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    parts=refinements._positive_parts(body)
    positive='; '.join(parts)
    for parent in parents:
        remaining=positive
        cues=[]
        patterns=BAD.get(parent,[])
        if parent=='制服与职业装' and re.search(r'\b(?:armor|armour|mecha|gundam|exoskeleton)\b',positive):
            patterns=patterns+[r'\bpower suit\b']
        for pattern in patterns:
            cues.extend(m.group() for m in re.finditer(pattern,remaining))
            remaining=re.sub(pattern,' ',remaining)
        if parent=='头饰与发饰':
            for part in parts:
                for m in re.finditer(r'\bcap\b',part):
                    if not refinements._phrase_allowed(parent,'cap',part,m.start(),m.end()):
                        cues.append(m.group())
                        remaining=remaining.replace(part,part[:m.start()]+' '+part[m.end():])
        if parent in SUPPORT and cues and not re.search(SUPPORT[parent],remaining,re.I):
            result[parent]={'false_cues':cues,'reason':'False contextual cues removed; no independent support remains.'}
    if '亲密互动' in parents and re.search(r'\bkiss(?:ing)?\b',body,re.I) and not re.search(SUPPORT['亲密互动'],positive,re.I):
        result['亲密互动']={'false_cues':['quoted printed slogan'],'reason':'Action keyword occurs only in printed text.'}
    return result
