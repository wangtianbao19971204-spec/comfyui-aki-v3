"""Batch 26 rules: action scope, title context and garment-state guards from round 112."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('media_metaphors',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_media_metaphors/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

# Keep the inherited support table available to later batches and to the
# removal checks below.
SUPPORT={**previous.SUPPORT,
    '视线方向':r'\b(?:look(?:s|ing)?\b[^.;!?]{0,20}\bat\b|looking (?:away|back|up|down|toward)|gaze(?:s|d)? (?:at|toward|into)|staring at|glancing at|eyes? (?:on|fixed on)|smiles? back|turns? (?:to|toward) (?:the |her )?(?:side|viewer|camera))\b',
    '性交与体位':r"\b(?:missionary|doggy ?style|sex from behind|cowgirl|reverse cowgirl|spooning|(?:vaginal|anal) (?:sex|intercourse)|penetration by (?:a )?(?:man|penis)|sex|intercourse|gangbang|group sex|threesome|mmf|fff|hetero|yuri|lesbian|double penetration|multiple penetration|from behind|straddling|suspended congress|paizuri|fellatio|cunnilingus|anilingus|sucking another's pussy|inserting[^.;!?]{0,30} into another's (?:pussy|anus|ass)|(?:1|2|3|4|multiple) ?boys?|multiple boys?)\b",
    '手势与肢体动作':r'\b(?:hands?|arms?|fingers?|legs?|thighs?)\b[^.;!?]{0,25}\b(?:up|raised|crossed|spread|bent|clasped|wrapped|behind|toward|touching|grabbing|holding)\b|\b(?:grabbing|groping|fondling|squeezing|cupping|spreading|fingering|touching)\b[^,.;!?]{0,30}\b(?:ass|butt|buttocks|pussy|labia|vagina|crotch|hips|breasts?|nipples?)\b',
    '裙装与礼服':r'\b(?:skirt|dress|gown|miniskirt|mini skirt|sundress)\b',
}

# Explicit hand actions on a body or a self-directed object insertion still
# belong to an existing parent even when the library omitted that parent.
GESTURE_BODY=r"\b(?:grabbing|groping|fondling|squeezing|cupping|spreading)\b[^,.;!?]{0,30}\b(?:ass|butt|buttocks|pussy|labia|vagina|crotch|hips|breasts?|nipples?)\b"
SELF_INSERT=r"\b(?:vaginal|anal) object insertion\b|\b(?:dildo|vibrator)\b[^.;!?]{0,45}\bobject insertion\b|\bobject insertion\b[^.;!?]{0,45}\b(?:dildo|vibrator)\b"
SELF_TOY=r"\b(?:dildos?|vibrators?|sex toys?|anal beads?|butt plugs?|sex machines?|riding machines?)\b"
PARTNER=r"\b(?:\d*boys?|male|hetero|group sex|threesome|gangbang|yuri|lesbian|intercourse|cum|semen|ejaculat\w*|another's|shared object insertion)\b|\bsex\b(?!\s*(?:toys?|dolls?|machines?))"
GAZE_SUPPORT=SUPPORT['视线方向']
SEX_SUPPORT=SUPPORT['性交与体位']
FURNITURE_SUPPORT=r"\b(?:beds?|chairs?|stools?|benches?|sofas?|couches?|tables?|desks?|shelves?|shelf|books?|cups?|teacups?|bottles?|mirrors?|phones?|smartphones?|clocks?|pillows?|towels?|carpets?|rugs?|blankets?|sinks?|faucets?|baskets?|easels?|canvases?|instruments?|guitars?|pianos?|violins?|seats?|toys?|plush toys?|lanterns?|mailboxes?|storage boxes?|potted plants?)\b|(?<!glass )curtains?\b"

# A false cue only removes a parent when no independent evidence remains.
REMOVALS=[
    ('种族与幻想生物',[r'["“]\s*the monster\b'],r'\b(?:monster|goblin|orc|elf|angel|demon|devil|fairy|youkai|vampire|succubus|incubus|zombie|ghost|dragon|mermaid|slime)\b','Quoted work title, not a creature cue.'),
    ('城市与街道',[r'\burban modernity\b'],r'\b(?:city|cities|urban|street|road|alley|town|village|skyline|downtown|crosswalk|sidewalk|intersection|storefront|high[- ]rise|skyscrapers?)\b|\b(?:park|subway|metro|tram|asphalt)\b','Atmosphere word, not a city scene.'),
    ('家具与生活用品',[r'\b(?:staircase steps?|railing structure|metal handrails?|glass railings?|handrails?)\b'],FURNITURE_SUPPORT,'Architectural railing or steps, not furniture.'),
    ('视线方向',[r'\bguiding (?:the |her |his |their )?gaze\b'],GAZE_SUPPORT,'Composition guidance rather than a person looking.'),
    ('性交与体位',[r'\b(?:vaginal|anal) object insertion\b'],SEX_SUPPORT,'Object insertion is a self-directed act, not partner intercourse.'),
    ('持物与道具互动',[r'\bholding (?:her |his |their |the )?(?:stomach|abdomen|belly|waist)\b',r'\b(?:arms?|hands?)[^.;!?]{0,25}\b(?:crossed over|clutching|clutches|gripping)\b[^.;!?]{0,25}\b(?:stomach|abdomen|belly|waist)\b'],r'\b(?:holding|holds?|carrying|carries|grasp\w*|grip\w*|clutch\w*|grabb?\w*)\b[^.;!?]{0,45}\b(?:book|cup|phone|sword|gun|spear|bag|handbag|ball|bottle|flower|bouquet|dildo|vibrator|umbrella|weapon|guitar|piano|violin|camera|brush|pen|lipstick)\b','Body-part contact without a held object.'),
]


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))


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
        if parent in parents or parent in found or not allowed:return
        if re.search(pattern,positive,re.I):found.append(parent)
    gesture=False
    for match in re.finditer(GESTURE_BODY,positive,re.I):
        before=positive[max(0,match.start()-40):match.start()]
        if not re.search(r'\btentacles?\b[^.;!?]{0,25}$',before,re.I):
            gesture=True;break
    want('手势与肢体动作',GESTURE_BODY,allowed=gesture)
    want('自慰',SELF_INSERT,allowed=bool(re.search(SELF_TOY,positive,re.I)) and not re.search(PARTNER,positive,re.I))
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
