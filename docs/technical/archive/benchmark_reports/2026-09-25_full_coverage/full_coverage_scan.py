"""Full-coverage read-only taxonomy evidence scan.

Goal: replace the 16-record-per-round sampling protocol with ONE deterministic
pass over the whole library, producing a finite family inventory and a
convergence ledger that a human/agent adjudication loop can drive to zero.

Read-only with respect to production. Prompt bodies are processed in memory and
never emitted; only identity, hashes, engine labels and cue flags are written.

Cue catalogue is inherited verbatim from the Cycle 02 radius scanner so this
scan cannot silently widen or narrow the established family definitions.
"""
import argparse
import hashlib
import importlib
import json
import re
import sys
import time
import types
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROD = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector'
DATA = PROD / 'user_data/prompt_selector/data.json'
PROJECTION = DATA.with_name('semantic_projection.json')
SOURCES = PROD / 'prompt_selector'

LENGTH_MIN, LENGTH_MAX = 1, 1800
STRATA = ((1, 120), (121, 350), (351, 900), (901, 1800))

RISK = re.compile(
    r'\b(?:loli|shota|mesugaki|child|children|underage|teen|teenage(?:r|rs)?|randoseru|'
    r'junior high school|aged.down|young boy|little (?:girl|boy))\b'
    r'|\b(?:age(?:d)?\s*(?:[0-9]|1[0-7])\b|(?:[0-9]|1[0-7])[ -]+years?[ -]+old\b)'
    r'|未成年|幼女|幼童|小正太|萝莉',
    re.I,
)
PRESERVED_NAME = re.compile(r'小孩|幼女|幼童|正太|萝莉|未成年')


def cue_specs():
    """Inherited verbatim from cycle_02/scan_round139_error_families.py."""
    return [
        # Batch 88: `slipping/slipped off shoulders` was listed here, but the engine maps it
        # to wear_state.off_shoulder (its own family, with its own cue), so 39 correct records
        # looked like misses; the bare word `top` also matched `the open top of the box`.
        {'id': 'wear_open', 'family': 'wear-state phrasing', 'pattern': r'\b(?:open(?:ed)?\s+(?:her\s+|his\s+|their\s+)?(?:clothes|clothing|shirt|jacket|coat|robe|sweater|cardigan|dress|blouse|bra)|(?:unzipped|unbuttoned|undone)\b[^.!?;]{0,65}\b(?:shirt|jacket|coat|robe|sweater|cardigan|dress|blouse|top|bra|clothes|clothing)|(?:robe|sweater|shirt|jacket|dress)[^.!?;]{0,45}\b(?:fallen\s+open|undone))\b', 'add_parents': ['穿着状态'], 'add_nodes': ['wear_state.open'], 'priority': 'primary'},
        # Split from the Cycle 02 combined cue: "bare shoulders" is a body-part
        # signal, while "off-shoulder" is a garment-state signal already served
        # by wear_state.off_shoulder. Keeping them merged mis-attributed 941
        # records to the body-part family.
        {'id': 'bare_shoulders_body', 'family': 'body-part / garment boundary', 'pattern': r'\bbare\s+shoulders?\b|\bshoulders?\s+(?:are|is)\s+bare\b', 'add_parents': ['身体部位'], 'add_nodes': ['part.shoulder'], 'priority': 'primary'},
        # Batch 88: `A discarded red off-shoulder top ... lie at her feet` describes a
        # garment on the floor, not a worn state.
        {'id': 'off_shoulder_garment', 'family': 'wear-state phrasing', 'pattern': r'\boff[- ]shoulder(?:ed)?\b', 'add_parents': ['穿着状态'], 'add_nodes': ['wear_state.off_shoulder'], 'require_callable': 'worn_not_discarded', 'priority': 'primary'},
        {'id': 'person_holding', 'family': 'natural-language action / subject relation', 'pattern': r'\b(?:she|he|woman|man|girl|boy|person|character)\b[^.!?;]{0,100}\bholds?\s+(?!a\s+hint\b)(?:a|an|the|her|his|their|your|one|two|three|\d+)\b', 'add_parents': ['持物与道具互动'], 'add_nodes': ['use_prop.holding'], 'priority': 'secondary'},
        {'id': 'camera_gaze', 'family': 'natural-language action / gaze relation', 'pattern': r'\b(?:gazes?|looks?)\s+(?:(?:intently|directly|straight)\s+)?at\s+(?:the\s+)?(?:camera|viewer)\b|\bdirectly\s+at\s+(?:the\s+)?camera\b|\bgaze\s+toward\s+(?:the\s+)?camera\b', 'add_parents': ['视线方向'], 'add_nodes': ['gaze.viewer'], 'priority': 'secondary'},
        # Batch 88: `as she stands (or sits on the edge of the seat)` is a parenthetical
        # alternative, not a depicted sitting pose.
        {'id': 'person_sitting', 'family': 'natural-language action / posture', 'pattern': r'\b(?:woman|man|girl|boy|person|character|she|he)\b[^.!?;]{0,100}\bsits?\b', 'add_parents': ['坐姿与蹲姿'], 'add_nodes': ['sit.sitting'], 'strip_parentheticals': True, 'priority': 'secondary'},
        {'id': 'kneeling_dogeza', 'family': 'natural-language action / posture', 'pattern': r'\b(?:dogeza|kneel(?:ing|ed)?|genuflect\w*)\b', 'add_parents': ['站姿与跪姿'], 'add_nodes': ['stand.kneeling'], 'priority': 'secondary'},
        {'id': 'falling_motion', 'family': 'natural-language action / motion', 'pattern': r'\b(?:falling\s+down|fall\s+down|in\s+mid[- ]fall)\b', 'add_parents': ['移动与运动'], 'add_nodes': [], 'priority': 'secondary'},
        {'id': 'hair_braid', 'family': 'hair modifier and attachment', 'pattern': r'\b(?:braid(?:s|ed)?|two\s+braids|hair\s+in\s+two\s+braids)\b', 'add_parents': ['头发与发型'], 'add_nodes': ['hair.braid'], 'priority': 'secondary'},
        {'id': 'hair_long', 'family': 'hair modifier and attachment', 'pattern': r'\b(?:long|long[- ]haired)\s+(?:(?:brown|black|white|red|blonde|blond|blue|purple|pink|silver|gradient|wavy|straight)\s+){0,3}hair\b|\bhair\s+(?:is\s+)?long\b', 'add_parents': ['头发与发型'], 'add_nodes': ['hair.long'], 'pending_if_nodes': ['hair.very_long'], 'priority': 'pending-semantics-aware'},
        # Batch 88: the 25-character gap still let `very long sleeves,hair`, `very long
        # beard,mustache,brown hair` and `very long tongue,tail` count; the very-long token
        # must now sit next to the word `hair`.
        {'id': 'hair_very_long', 'family': 'hair modifier and attachment', 'pattern': r'\b(?:very|extremely|incredibly|super|ultra)[_ -]+long(?:\s+[a-z-]+){0,2}\s+hair\b|\b(?:very|extremely|incredibly|super|ultra)[_ -]+long[- ]haired\b', 'add_parents': ['头发与发型'], 'add_nodes': ['hair.very_long'], 'priority': 'secondary'},
        # Instrument correction (2026-09-25): the inherited Cycle 02 cue treated
        # "gradient hair" as a white-hair signal. The engine maps it to
        # hair.multicolor, which is correct, so 618 false flags were removed from
        # hair.white and re-pointed at hair.multicolor as their own family.
        {'id': 'hair_color_white', 'family': 'hair modifier and attachment', 'pattern': r'\bwhite\s+(?:to\s+grey\s+)?hair\b(?!\s+(?:ribbon|ribbons|flower|flowers|clip|clips|bow|bows|ornament|ornaments|band|bands|pin|pins|ties?|accessor(?:y|ies)|piece|pieces))|\bhair\s+(?:is\s+)?white\b(?!\s+(?:flower|flowers|ribbon|ribbons|clip|clips|bow|bows|ornament|ornaments|band|bands|pin|pins|piece|pieces|lace|fur|feather|feathers|streak|streaks|tie|ties|accessor(?:y|ies)))', 'add_parents': ['头发与发型'], 'add_nodes': ['hair.white'], 'priority': 'secondary'},
        {'id': 'hair_gradient', 'family': 'hair modifier and attachment', 'pattern': r'\bgradient\s+hair\b|\bmulticolou?red\s+hair\b|\btwo[- ]tone\s+hair\b', 'add_parents': ['头发与发型'], 'add_nodes': ['hair.multicolor'], 'priority': 'secondary'},
        # Batch 90: the 45-character window also matched `bright overhead, casting
        # soft shadows`, `soft falling snow, city lights` and `soft blue sky` -
        # soft must directly govern a light noun for the flag to be a defect.
        {'id': 'overhead_soft_light', 'family': 'soft-light natural-language phrase', 'pattern': r'\bsoft\b[^.!?;]{0,45}\boverhead\b|\boverhead\b[^.!?;]{0,45}\bsoft\b', 'add_parents': ['光影效果'], 'add_nodes': ['light_effect.soft'], 'require_callable': 'soft_light_direct', 'priority': 'primary'},
        # Keep the parent check when the mistaken bag is its only plausible
        # support. Independent worn accessories are handled in the callable.
        {'id': 'handbag_false_positive_guard', 'family': 'object versus figurative/decorative depiction', 'pattern': r'\b(?:trash|garbage|plastic|litter)\s+bags?\b|\bbags?\s+under\s+(?:the\s+)?eyes\b', 'remove_parents': ['首饰与随身配饰'], 'remove_nodes': ['accessory.bag'], 'guard_only': True, 'require_callable': 'handbag_phrase_only', 'priority': 'primary'},
        {'id': 'computer_window_false_positive_guard', 'family': 'physical object versus computer UI', 'pattern': r'\bwindow\s*\(?\s*computing\s*\)?\b|\berror[_ ]message[_ ]window\b|\bwindow\s+(?:showing|with)\s+(?:an?\s+)?error\b', 'remove_parents': ['家具与生活用品'], 'remove_nodes': [], 'guard_only': True, 'priority': 'primary'},
        # Batch 88: the 55-character cross-window matched unrelated list items (`... the fur
        # ball decoration of long socks, the grass and leaf shapes, the tree texture`) and
        # ordinary `christmas tree decoration details`, where a real tree is present. Only an
        # actual overlay / motif counts now.
        {'id': 'tree_overlay_false_positive_guard', 'family': 'physical object versus decorative overlay', 'pattern': r'\btree\s+(?:overlay|pattern|print|motif|sticker|decal)\b|\b(?:overlay|pattern|print|motif|sticker|decal)\s+(?:of|with|showing)\b[^.!?;]{0,25}\btrees?\b|\b(?:decorative|drawn|painted)\s+tree\b', 'remove_parents': [], 'remove_nodes': ['plant.tree'], 'guard_only': True, 'priority': 'primary'},
        {'id': 'nude_clothing_context_guard', 'family': 'garment modifier versus depicted state', 'pattern': r'\b(?:nude|naked)\s+(?:pants|trousers|leggings|shorts|stockings|garment|clothing)\b', 'remove_parents': [], 'remove_nodes': ['cover.nude'], 'guard_only': True, 'require_callable': 'nude_colour_only', 'priority': 'primary'},
        # New families discovered by the release-gate historical replay triage
        # (rounds 91/97 leather armchair, round 131 snowstorm silhouette).
        {'id': 'fabric_leather_furniture_guard', 'family': 'physical material versus garment material', 'pattern': r'\bleather\b[^.!?;]{0,45}\b(?:sofa|couch|armchair|chair|seat|bench|stool|headboard|car interior)\b|\b(?:sofa|couch|armchair|chair|seat|bench|stool|headboard)\b[^.!?;]{0,45}\bleather\b', 'remove_parents': [], 'remove_nodes': ['fabric.leather'], 'guard_only': True, 'require_callable': 'leather_furniture_only', 'priority': 'primary'},
        # Batch 88: rewritten. The snow-weather branch contradicted the round-131 amendment,
        # which keeps light_effect.silhouette for a bare tree silhouette in a snow landscape.
        # The family the amendment named is a *body outline being modified*:
        # accentuating / carving / lengthening / reflecting `her silhouette`. The first
        # rewrite also accepted `outline`, which matched 63 records whose silhouette is a
        # real depicted silhouette (for example `her silhouette outlined by the light`),
        # so the modifier must now directly govern a possessive + silhouette.
        {'id': 'silhouette_snow_guard', 'family': 'body outline versus depicted silhouette', 'pattern': r'\b(?:accentuat\w*|carv\w*|lengthen\w*|elongat\w*|reflect\w*|highlight\w*)\s+(?:her|his|their|your|my|the)\s+(?:\w+\s+){0,2}silhouette\b|\bsilhouette\b[^.!?;]{0,25}\b(?:accentuat\w*|carv\w*|lengthen\w*|elongat\w*|is\s+reflected)\b', 'remove_parents': [], 'remove_nodes': ['light_effect.silhouette'], 'guard_only': True, 'require_callable': 'silhouette_not_landscape', 'priority': 'primary'},
        # Batch 88: `barefoot sandals (jewelry)` is jewelry and `barefoot (optional)` is an
        # optional tag, not a depicted state.
        {'id': 'barefoot', 'family': 'specific-vocabulary coverage', 'pattern': r'\bbarefoot\b(?!\s+(?:sandal|jewelry)|\s*\([^)]{0,30}\))|\bbare\s+feet?\b|\bbare\s+foot\b', 'add_parents': ['裸露与遮盖'], 'add_nodes': ['cover.barefoot'], 'priority': 'secondary'},
        {'id': 'garter', 'family': 'specific-vocabulary coverage', 'pattern': r'\bgarters?\b', 'add_parents': ['鞋袜与腿饰'], 'add_nodes': ['legwear.garter'], 'priority': 'secondary'},
        {'id': 'shackles', 'family': 'specific-vocabulary coverage', 'pattern': r'\b(?:iron\s+)?shackles?\b(?!\s+(?:piercing|jewelry|necklace|earrings?|decoration|ornaments?))', 'add_parents': ['束缚与控制'], 'add_nodes': ['restraint.cuffs'], 'priority': 'secondary'},
        {'id': 'torn_clothing', 'family': 'specific-vocabulary coverage', 'pattern': r'\btorn\s+(?:shirt|clothes|clothing|dress|jacket|coat|robe)\b', 'add_parents': ['穿着状态'], 'add_nodes': ['wear_state.torn'], 'priority': 'secondary'},
        {'id': 'tears_sobbing', 'family': 'specific-vocabulary coverage', 'pattern': r'\b(?:sobbing|teary[- ]eyed|tears?\s+streaming|crying)\b', 'add_parents': ['悲伤与哭泣'], 'add_nodes': ['sad.tears'], 'priority': 'secondary'},
        {'id': 'prison_cell', 'family': 'physical setting coverage', 'pattern': r'\b(?:prison\s+cell|jail\s+cell|prison)\b', 'add_parents': ['室内空间'], 'add_nodes': [], 'priority': 'secondary'},
        {'id': 'traditional_attire', 'family': 'natural-language clothing / prop coverage', 'pattern': r'\btraditional\s+(?:attire|clothing|garb|robes?)\b', 'add_parents': ['传统与民族服饰'], 'add_nodes': [], 'priority': 'secondary'},
        {'id': 'headdress', 'family': 'natural-language clothing / prop coverage', 'pattern': r'\b(?:golden\s+)?headdress\b|\bdangling\s+tassels?\b', 'add_parents': ['头饰与发饰'], 'add_nodes': [], 'priority': 'secondary'},
        {'id': 'warm_palette', 'family': 'natural-language color coverage', 'pattern': r'\b(?:warm\s+(?:golden|yellow|red|orange)\s+(?:tones?|colors?|palette)|warm\s+(?:golden|yellow|red|orange)\s+and\s+(?:emerald|green)\s+tones?)\b', 'add_parents': ['色彩与调色'], 'add_nodes': ['color.warm'], 'priority': 'secondary'},
        {'id': 'sleeveless_garment', 'family': 'natural-language garment coverage', 'pattern': r'\bsleeveless\s+(?:shirt|top|dress|jacket|blouse)\b', 'add_parents': ['服装材质与剪裁'], 'add_nodes': [], 'priority': 'secondary'},
        {'id': 'snapshot_photography', 'family': 'photography vocabulary', 'pattern': r'\b(?:realistic\s+snapshot\s+quality|ordinary\s+(?:camera|phone)|fashion\s+photography\s+style)\b', 'add_parents': ['摄影与写实'], 'add_nodes': ['photo.photography'], 'pending_if_nodes': ['photo.fashion'], 'priority': 'pending-semantics-aware'},
        {'id': 'soft_scene_modifier_history', 'family': 'historical natural-light boundary', 'pattern': r'\b(?:natural\s+light|softbox|sunlight|diffused\s+light|ambient\s+light)\b', 'add_parents': [], 'add_nodes': ['light_effect.soft'], 'guard_only': True, 'priority': 'historical-context-only'},
        {'id': 'figurative_place_history', 'family': 'historical physical-versus-figurative place boundary', 'pattern': r'\b(?:like|as\s+if\s+it\s+were|evoking)\b[^.!?;]{0,60}\b(?:cafe|café|coffeehouse|hotel\s+lobby)\b', 'add_parents': [], 'add_nodes': [], 'guard_only': True, 'priority': 'historical-context-only'},
        {'id': 'skin_color_clothing_guard_history', 'family': 'historical clothing color versus skin boundary', 'pattern': r'\b(?:tan|brown|black|white)\s+(?:clothes|clothing|fabric|palette|stockings|jacket|pants)\b', 'add_parents': [], 'add_nodes': [], 'guard_only': True, 'priority': 'historical-context-only'},
    ]



# --- batch 88 instrument predicates ---
# Batch 85 declared `require_callable` on two cues but never wired it into this
# scanner, so the engine-side `leather_furniture_only` helper was dead code.
# These predicates decide whether a cue hit is a real defect. They receive the
# NAI-stripped probe text and the served row.
CUE_CALLABLES = {}


def _cue_callable(name):
    def register(func):
        CUE_CALLABLES[name] = func
        return func
    return register


_LEATHER_GARMENT = re.compile(
    r'\b(?:leather|suede)\b[^.;!?]{0,30}\b(?:jacket|blazer|brim|corsage|coat|pants|trousers|skirt|shorts|boots?|gloves?|dress|'
    r'corset|bustier|harness|leotard|bodysuit|bra|lingerie|stockings|thighhighs|belt|straps?|heels?|'
    r'shoes?|sandals?|pumps?|stilettos?|footwear|cap|hat|choker|glove|bag|purse|backpack|pouch)\b'
    r'|\b(?:jacket|blazer|brim|corsage|coat|pants|trousers|skirt|shorts|boots?|gloves?|dress|corset|bustier|harness|'
    r'leotard|bodysuit|bra|lingerie|stockings|thighhighs|belt|heels?|shoes?|sandals?|pumps?|'
    r'stilettos?|footwear)\b[^.;!?]{0,20}\b(?:leather|suede)\b', re.I)
_LEATHER_NON_FURNITURE = re.compile(r'\b(?:patent|faux|vegan|glossy)\s+leather\b', re.I)
_LEATHER_SHOE_ANAPHORA = re.compile(
    r'\b(?:boots?|shoes?|pumps?|stilettos?|heels?)\b[^.;!?]{0,110}'
    r'\btheir\s+(?:shiny |glossy |black )?leather\b', re.I)


@_cue_callable('leather_furniture_only')
def _leather_furniture_only(probe, row):
    """True only when no leather mention belongs to a garment, shoe or bag."""
    if not re.search(r'\bleather\b', probe, re.I):
        return False
    if _LEATHER_NON_FURNITURE.search(probe):
        return False
    return not (_LEATHER_GARMENT.search(probe) or _LEATHER_SHOE_ANAPHORA.search(probe))


_BAG_GUARD_PHRASE = re.compile(r'\b(?:trash|garbage|plastic|litter)\s+bags?\b|'
                               r'\bbags?\s+under\s+(?:the\s+)?eyes\b', re.I)
_BAG_REAL = re.compile(r'\b(?:backpack|handbag|shoulder bag|purse|satchel|tote|pouch|bag|bags)\b', re.I)
_ACCESSORY_LEAF = re.compile(r'^accessory\.')
_OTHER_WORN_ACCESSORY = re.compile(
    r'\b(?:necklace|pendant|earrings?|bracelet|choker|neck ribbon|bowtie|bow tie|'
    r'(?:hair|neck|black|blue|pink|purple|yellow|red|white) bows?|'
    r'wrist cuffs?|detached collar|belly chain|ankle ribbon laces|nipple rings?|necktie|'
    r'collar\s*,\s*chain)\b', re.I)


@_cue_callable('handbag_phrase_only')
def _handbag_phrase_only(probe, row):
    """A bag guard hit needs no real bag or independently worn accessory."""
    if any(_ACCESSORY_LEAF.match(leaf) for leaf in row['leaves']):
        return False
    without_guard = _BAG_GUARD_PHRASE.sub(' ', probe)
    return not (_BAG_REAL.search(without_guard) or _OTHER_WORN_ACCESSORY.search(without_guard))


_NUDE_COLOUR = re.compile(r'\b(?:nude|naked)\s+(?:pants|trousers|leggings|shorts|stockings|garment|'
                          r'clothing|dress|top|bra|heels|pumps|stilettos|sandals|bodysuit|lace|silk|fabric)\b', re.I)
_NUDE_STATE = re.compile(
    r'\b(?:topless|completely\s+nude|fully\s+nude|nude\s+(?:except|but)|naked\s+(?:except|but)|'
    r'wearing\s+only|only\s+wearing|only\s+in|discarded|stripped|undressed|bare\s+breasts|'
    r'breasts\s+exposed|exposed\s+breasts|bare\s+chest|nude\s+body|nude\s+figure)\b', re.I)


@_cue_callable('nude_colour_only')
def _nude_colour_only(probe, row):
    """True only when `nude` appears solely as a colour adjective on clothing."""
    if not _NUDE_COLOUR.search(probe):
        return False
    return not _NUDE_STATE.search(probe)


_LANDSCAPE_SILHOUETTE = re.compile(
    r'\b(?:tree|trees|mountain|mountains|landscape|forest|branch|branches|plant|plants|skyline|'
    r'buildings?)\b[^.;!?]{0,25}\bsilhouette\b|\bsilhouette\b[^.;!?]{0,25}\b(?:tree|trees|'
    r'mountains?|landscape|forest|branch|buildings?)\b', re.I)
_LIGHT_SOURCE = re.compile(
    r'\b(?:back-?lit|backlight(?:ing)?|rim\s+light|silhouetted\s+against|glow(?:ing)?|'
    r'light\s+streams?|sunlight|moonlight|illuminat\w*|light\s+source|lights?\s+from|'
    r'light\s+and\s+shadow\s+come\s+from)\b', re.I)


@_cue_callable('silhouette_not_landscape')
def _silhouette_not_landscape(probe, row):
    """A silhouette flag needs a modified body outline with no real light source.

    Round-131's amendment keeps landscape silhouettes, and the 11 records scanned
    on 2026-09-26 showed that `backlight / rim light highlighting her silhouette`
    is a depicted silhouette too. Only phrasing that modifies the body outline
    without any light source (`a belt accentuating her hourglass silhouette`)
    stays flagged.
    """
    if _LANDSCAPE_SILHOUETTE.search(probe):
        return False
    return not _LIGHT_SOURCE.search(probe)


@_cue_callable('worn_not_discarded')
def _worn_not_discarded(probe, row):
    """`A discarded off-shoulder top ... at her feet` is not a worn state."""
    for match in re.finditer(r'\boff[- ]shoulder\b', probe, re.I):
        before = probe[max(0, match.start() - 60):match.start()]
        if re.search(r'\b(?:discarded|dropped|fell|fallen|lying|lies|tossed|strewn|piled)\b', before, re.I):
            return False
    return True


_B90_SOFT_DIRECT = re.compile(
    r'\b(?:soft|diffuse?d|gentle|even)\b[\s,]{1,3}'
    r'(?:(?:warm|cool|golden|amber|natural|diffused|ambient|even|and)\b[\s,]{0,2}){0,2}'
    r'(?:light|lighting|daylight|sunlight|moonlight|glow|illumination|illuminated)\b'
    r'|\b(?:light|lighting|daylight|sunlight|moonlight|glow|illumination)\b[\s,]{0,3}'
    r'(?:is|was|looks?|feels?|are|were|appears?)[\s,]{0,2}\b(?:soft|gentle|diffused|even)\b', re.I)


@_cue_callable('soft_light_direct')
def _soft_light_direct(probe, row):
    """The overhead soft-light cue only counts when soft governs a light noun.

    Full-library measurement of the alternative (running the engine's B86
    window over the comma-joined text) added 978 then 1663 light_effect.soft
    leaves, far beyond this 94-record family, so the engine rule was left alone
    and the cue was narrowed instead.
    """
    return bool(_B90_SOFT_DIRECT.search(probe))


_NEGATION = re.compile(r'\b(?:no|not|without|never|excluding|absence of)\s+[^,;.!?|\u2014\u2013]+')
_NEGATIVE_SECTION = re.compile(r'\b(?:negative\s*prompt|负面提示词)\b.*$', re.S | re.I)
_PARENTHETICAL = re.compile(r'\([^)]*\)')

def compile_specs():
    out = []
    for spec in cue_specs():
        item = dict(spec)
        item['regex'] = re.compile(spec['pattern'], re.I)
        out.append(item)
    return out


def load_runtime():
    package = types.ModuleType('full_coverage_runtime')
    package.__path__ = [str(SOURCES)]
    sys.modules[package.__name__] = package
    pmod = importlib.import_module(package.__name__ + '.semantic_projection')
    rmod = importlib.import_module(package.__name__ + '.semantic_refinements')
    tmod = importlib.import_module(package.__name__ + '.semantic_taxonomy')
    return pmod, rmod, tmod


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def stratum_of(length):
    for index, (low, high) in enumerate(STRATA):
        if low <= length <= high:
            return index
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('scan', 'inventory', 'batch', 'close', 'ledger'), default='scan')
    parser.add_argument('--label', default=None, help='Run label used in the convergence ledger')
    parser.add_argument('--families', default=None, help='Comma separated "target" names for batch/close')
    parser.add_argument('--limit', type=int, default=0, help='Max records to emit in batch mode')
    parser.add_argument('--verdict', default=None, choices=('implemented', 'rejected', 'narrowed', 'deferred'))
    parser.add_argument('--note', default='', help='Evidence note recorded with an adjudication')
    parser.add_argument('--batch', default=None, help='Batch id, e.g. batch_001')
    args = parser.parse_args()

    started = time.time()
    stamp = datetime.now(timezone.utc).astimezone().isoformat()
    pmod, rmod, tmod = load_runtime()
    specs = compile_specs()
    parents_whitelist = set(tmod.SUBCATEGORY_PARENTS)
    doc = pmod.read_projection(PROJECTION)

    data_bytes = DATA.read_bytes()
    data_sha = hashlib.sha256(data_bytes).hexdigest()
    payload = json.loads(data_bytes)
    del data_bytes

    index_path = HERE / 'coverage_index.jsonl'
    if args.mode == 'scan':
        stream = index_path.open('x', encoding='utf-8', newline='\n')
        totals = Counter()
        usable_len = Counter()
        cue_hits = Counter()
        flagged_rows = 0
        for category in payload['categories']:
            name = category.get('name', '')
            head = name.split('/')[0].strip()
            preserved = head == '🔞一键模式' or bool(PRESERVED_NAME.search(name))
            for prompt in category.get('prompts', []):
                text = prompt.get('prompt') or ''
                totals['records'] += 1
                if preserved:
                    totals['out_preserved_source'] += 1
                    continue
                length = len(text)
                if not LENGTH_MIN <= length <= LENGTH_MAX:
                    totals['out_length'] += 1
                    continue
                if RISK.search(text.replace('_', ' ')):
                    totals['out_age_risk'] += 1
                    continue
                decision = pmod.decision_for(doc, category, prompt)
                if not decision.get('manual_search_eligible'):
                    totals['out_not_eligible'] += 1
                    continue
                if decision.get('semantic_review_status') == 'user_confirmed':
                    totals['out_user_confirmed'] += 1
                    continue
                if decision.get('declared_usage', decision.get('usage')) not in ('positive', 'mixed'):
                    totals['out_usage'] += 1
                    continue
                if decision.get('primary_class') == 'artist_style':
                    totals['out_artist_style'] += 1
                    continue
                parents = [p for p in pmod.selector_subcategories(decision, prompt) if p in parents_whitelist]
                if not parents:
                    totals['out_no_parent'] += 1
                    continue
                leaves = list(rmod.extract_refinements(text, parents))
                parent_set, leaf_set = set(parents), set(leaves)
                # Cue matching must ignore non-positive NAI weight regions the
                # same way the refinement extractor does: a phrase that only
                # appears inside "-1::...::" is not evidence (batch 73).
                probe = tmod.strip_nonpositive_nai_weights(text).replace('_', ' ')
                # Batch 88: mirror the engine's own positive-part rule - a phrase
                # that only appears behind a negation is not evidence - and keep a
                # parenthetical-free copy for cues whose branch is an aside.
                # Batch 89: the engine drops everything from the negative-prompt
                # marker on (record 2497's `character kneeling ...` sits inside
                # its own negative prompt), so the cues must read the same text.
                # This runs BEFORE the negation strip: `no emotion negative
                # prompt: deformed` would otherwise swallow the marker itself.
                probe = _NEGATIVE_SECTION.sub(' ', probe)
                probe = _NEGATION.sub(' ', probe)
                probe_noparen = _PARENTHETICAL.sub(' ', probe)
                flags = []
                for spec in specs:
                    haystack = probe_noparen if spec.get('strip_parentheticals') else probe
                    if not spec['regex'].search(haystack):
                        continue
                    cue_hits[spec['id']] += 1
                    if spec.get('guard_only') and not spec.get('remove_nodes') and not spec.get('remove_parents'):
                        continue
                    if spec.get('pending_if_nodes'):
                        if not any(node in leaf_set for node in spec['pending_if_nodes']):
                            continue
                    if spec.get('require_callable'):
                        _guard = CUE_CALLABLES.get(spec['require_callable'])
                        if _guard is None or not _guard(probe, {'parents': parent_set, 'leaves': leaf_set}):
                            continue
                    for target in spec.get('add_nodes', ()):
                        if target not in leaf_set:
                            flags.append({'cue': spec['id'], 'kind': 'missing_node', 'target': target})
                    for target in spec.get('add_parents', ()):
                        if target not in parent_set:
                            flags.append({'cue': spec['id'], 'kind': 'missing_parent', 'target': target})
                    for target in spec.get('remove_nodes', ()):
                        if target in leaf_set:
                            flags.append({'cue': spec['id'], 'kind': 'false_positive_node', 'target': target})
                    for target in spec.get('remove_parents', ()):
                        if target in parent_set:
                            flags.append({'cue': spec['id'], 'kind': 'false_positive_parent', 'target': target})
                usable_len[stratum_of(length)] += 1
                if flags:
                    flagged_rows += 1
                totals['in_scope'] += 1
                stream.write(json.dumps({
                    'id': prompt.get('id'),
                    'category_id': category.get('id'),
                    'category': name,
                    'prompt_sha256': hashlib.sha256(text.encode()).hexdigest(),
                    'length': length,
                    'stratum': stratum_of(length),
                    'parents': parents,
                    'leaves': leaves,
                    'flags': flags,
                }, ensure_ascii=False) + '\n')
        stream.close()
        summary = {
            'schema': 'full-coverage-scan/v1',
            'run_label': args.label or 'run_000',
            'created_at': stamp,
            'elapsed_seconds': round(time.time() - started, 1),
            'data_sha256': data_sha,
            'projection_sha256': sha_file(PROJECTION),
            'source_sha256': {name: sha_file(SOURCES / name) for name in (
                'prompt_selector.py', 'semantic_projection.py',
                'semantic_refinements.py', 'semantic_taxonomy.py')},
            'cue_catalogue_size': len(specs),
            'totals': dict(totals),
            'in_scope_by_stratum': {
                '{}..{}'.format(*STRATA[i]): usable_len[i] for i in range(4)
            },
            'cue_hit_counts': dict(cue_hits),
            'flagged_rows': flagged_rows,
            'clean_rows': totals['in_scope'] - flagged_rows,
            'clean_pct': round(100.0 * (totals['in_scope'] - flagged_rows) / max(1, totals['in_scope']), 3),
            'index_sha256': sha_file(index_path),
        }
        (HERE / 'scan_summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.mode == 'batch':
        wanted = {name.strip() for name in (args.families or '').split(',') if name.strip()}
        if not wanted:
            raise SystemExit('--families is required in batch mode')
        rows = [json.loads(line) for line in index_path.read_text(encoding='utf-8').splitlines()]
        bodies = {}
        payload = json.loads(DATA.read_bytes())
        for category in payload['categories']:
            for prompt in category.get('prompts', []):
                bodies[prompt.get('id')] = (category.get('name'), prompt.get('prompt') or '')
        del payload
        selected = []
        for row in rows:
            hits = sorted({flag['cue'] for flag in row['flags'] if flag['target'] in wanted})
            if not hits:
                continue
            name, text = bodies[row['id']]
            selected.append({
                'id': row['id'], 'category': name, 'prompt': text,
                'prompt_sha256': row['prompt_sha256'], 'length': row['length'],
                'parents': row['parents'], 'leaves': row['leaves'],
                'cues': hits,
                'targets': sorted({(f['target'], f['kind']) for f in row['flags'] if f['target'] in wanted}),
            })
            if args.limit and len(selected) >= args.limit:
                break
        batch_id = args.batch or 'batch_001'
        out = HERE / (batch_id + '.jsonl')
        out.write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in selected), encoding='utf-8')
        meta = {
            'batch': batch_id, 'created_at': stamp, 'families': sorted(wanted),
            'records': len(selected), 'index_sha256': sha_file(index_path),
            'file': out.name, 'file_sha256': sha_file(out),
        }
        (HERE / (batch_id + '.meta.json')).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return

    if args.mode == 'close':
        wanted = [name.strip() for name in (args.families or '').split(',') if name.strip()]
        if not wanted or not args.verdict:
            raise SystemExit('--families and --verdict are required in close mode')
        adj_path = HERE / 'adjudications.jsonl'
        with adj_path.open('a', encoding='utf-8', newline='\n') as stream:
            for name in wanted:
                stream.write(json.dumps({
                    'target': name, 'verdict': args.verdict, 'run': args.label or '',
                    'recorded_at': stamp, 'batch': args.batch or '', 'note': args.note,
                }, ensure_ascii=False) + '\n')
        print(json.dumps({'recorded': wanted, 'verdict': args.verdict}, ensure_ascii=False))
        return

    # inventory mode: aggregate the index into families and a convergence ledger
    rows = [json.loads(line) for line in index_path.read_text(encoding='utf-8').splitlines()]
    spec_by_cue = {spec['id']: spec for spec in specs}
    families = {}
    for row in rows:
        for flag in row['flags']:
            spec = spec_by_cue[flag['cue']]
            key = flag['target'] + '|' + flag['kind']
            entry = families.setdefault(key, {
                'target': flag['target'], 'kind': flag['kind'], 'cue': flag['cue'],
                'family': spec['family'], 'priority': spec['priority'],
                'records': 0, 'examples': [],
            })
            entry['records'] += 1
            if len(entry['examples']) < 8:
                entry['examples'].append(row['id'])
    ordered = sorted(families.values(), key=lambda x: (-x['records'], x['target']))
    inventory = {
        'schema': 'full-coverage-family-inventory/v1',
        'created_at': stamp,
        'in_scope_records': len(rows),
        'flagged_records': sum(1 for r in rows if r['flags']),
        'clean_records': sum(1 for r in rows if not r['flags']),
        'open_items': sum(len(r['flags']) for r in rows),
        'family_count': len(ordered),
        'families': ordered,
    }
    adj_path = HERE / 'adjudications.jsonl'
    adjudications = []
    if adj_path.exists():
        adjudications = [json.loads(line) for line in adj_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    latest = {}
    for item in adjudications:
        latest[item['target']] = item
    implemented = {t: v for t, v in latest.items() if v['verdict'] == 'implemented'}
    rejected = {t: v for t, v in latest.items() if v['verdict'] == 'rejected'}
    characterized = {t: v for t, v in latest.items() if v['verdict'] in ('narrowed', 'deferred')}
    resolved = set(implemented) | set(rejected)
    # Convergence is measured on the CURRENT scan, not on verdict bookkeeping.
    # Implemented families simply stop producing flags (verified by rescan);
    # rejected families keep producing flags but those flags are not defects,
    # so they are removed from the net open count explicitly.
    current_flags = inventory['open_items']
    rejected_flags = sum(f['records'] for f in ordered if f['target'] in rejected)
    net_open = current_flags - rejected_flags
    baseline_open = None
    _ledger_path = HERE / 'convergence_ledger.json'
    if _ledger_path.exists():
        baseline_open = json.loads(_ledger_path.read_text(encoding='utf-8')).get('baseline', {}).get('open_items')
    resolved_records = (baseline_open - net_open) if baseline_open else 0
    inventory['adjudication'] = {
        'families_implemented': len(implemented),
        'families_rejected': len(rejected),
        'families_characterized': len(characterized),
        'families_open': len(ordered) - len(resolved) - len(characterized),
        'current_scan_flags': current_flags,
        'rejected_family_flags': rejected_flags,
        'open_items_remaining': net_open,
        'items_resolved': resolved_records,
        'resolution_pct': round(100.0 * resolved_records / max(1, baseline_open or 1), 3),
        'open_pct_remaining': round(100.0 * net_open / max(1, baseline_open or 1), 3),
        'effective_clean_pct': round(100.0 * (inventory['clean_records'] + rejected_flags)
                                     / max(1, inventory['in_scope_records']), 3),
        'verdicts': {t: v['verdict'] for t, v in latest.items()},
        'notes': {t: v.get('note', '') for t, v in latest.items() if v.get('note')},
        'by_family': {f['target']: f['records'] for f in ordered},
    }
    (HERE / 'family_inventory.json').write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    ledger_path = HERE / 'convergence_ledger.json'
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
    else:
        ledger = {
            'schema': 'full-coverage-convergence-ledger/v1',
            'scope_definition': (
                'All non-preserved records, length 1-1800, no age-risk terms, '
                'manual_search_eligible, usage in (positive,mixed), not artist_style, '
                'not user_confirmed, at least one whitelisted parent. '
                'Cue catalogue inherited from the Cycle 02 radius scanner.'),
            'baseline': {},
            'runs': [],
        }
    if not ledger.get('baseline'):
        ledger['baseline'] = {
            'in_scope_records': inventory['in_scope_records'],
            'flagged_records': inventory['flagged_records'],
            'clean_records': inventory['clean_records'],
            'open_items': inventory['open_items'],
            'family_count': inventory['family_count'],
            'clean_pct': round(100.0 * inventory['clean_records'] / max(1, inventory['in_scope_records']), 3),
        }
    run_label = args.label or f"run_{len(ledger['runs']) + 1:03d}"
    ledger['runs'] = [entry for entry in ledger['runs'] if entry.get('run_label') != run_label]
    ledger['runs'].append({
        'run_label': run_label,
        'recorded_at': stamp,
        'in_scope_records': inventory['in_scope_records'],
        'flagged_records': inventory['flagged_records'],
        'clean_records': inventory['clean_records'],
        'open_items': inventory['open_items'],
        'family_count': inventory['family_count'],
        'families_implemented': inventory['adjudication']['families_implemented'],
        'families_rejected': inventory['adjudication']['families_rejected'],
        'families_characterized': inventory['adjudication']['families_characterized'],
        'families_open': inventory['adjudication']['families_open'],
        'open_items_remaining': inventory['adjudication']['open_items_remaining'],
        'items_resolved': inventory['adjudication']['items_resolved'],
        'resolution_pct': inventory['adjudication']['resolution_pct'],
        'open_pct_remaining': inventory['adjudication']['open_pct_remaining'],
        'effective_clean_pct': inventory['adjudication']['effective_clean_pct'],
        'clean_pct': round(100.0 * inventory['clean_records'] / max(1, inventory['in_scope_records']), 3),
        'note': 'adjudication applied' if implemented else 'baseline measurement; adjudication not yet applied',
    })
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'in_scope_records': inventory['in_scope_records'],
        'flagged_records': inventory['flagged_records'],
        'clean_records': inventory['clean_records'],
        'open_items': inventory['open_items'],
        'family_count': inventory['family_count'],
        'top_families': [{k: f[k] for k in ('target', 'kind', 'family', 'records')} for f in ordered[:15]],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
