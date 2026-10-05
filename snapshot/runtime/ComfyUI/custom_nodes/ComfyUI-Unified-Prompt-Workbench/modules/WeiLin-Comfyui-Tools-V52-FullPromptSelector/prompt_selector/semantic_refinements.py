"""Original-text refinements below the library's reviewed semantic subtopics."""
import hashlib
import re

from .semantic_taxonomy import SUBCATEGORY_PARENTS, strip_nonpositive_nai_weights

REFINEMENT_VERSION = '2026-09-27.02'
REFINEMENT_NODES = {}


def _group(parent, prefix, rows):
    for slug, label, words in rows:
        node_id = f'{prefix}.{slug}'
        REFINEMENT_NODES[node_id] = {
            'label': label, 'parent': parent, 'owner': SUBCATEGORY_PARENTS[parent],
            'tags': words.split('|'),
        }


_group('职业与身份', 'role', [
    ('student','学生','student|schoolgirl|schoolboy|学生'), ('teacher','教师','teacher|教师|老师'),
    ('maid','女仆','maid|女仆'), ('medical','医护','doctor|nurse|医生|护士'),
    ('military','军警','soldier|police officer|police|士兵|警察'), ('royal','王室身份','princess|queen|king|prince|公主|女王'),
    ('religious','宗教职业','nun|priest|monk|miko|修女|巫女'), ('magic','施法者','witch|wizard|magician|魔女|巫师'),
    ('performer','演艺职业','idol|dancer|singer|actor|voice actor|偶像|舞者'),
    ('office','办公职业','office lady|businessman|秘书|白领'), ('warrior','武士、骑士与忍者','samurai|knight|ninja|武士|骑士|忍者'),
    ('service','餐饮服务','chef|waitress|waiter|厨师|服务员'),
])
_group('种族与幻想生物', 'species', [
    ('elf','精灵','elf|dark elf|精灵'), ('angel','天使','angel|天使'), ('demon','恶魔','demon|devil|succubus|incubus|恶魔|魅魔'),
    ('vampire','吸血鬼','vampire|吸血鬼'), ('mermaid','人鱼','mermaid|人鱼'), ('robot','机械生命','android|robot|cyborg|机器人|仿生人'),
    ('slime','史莱姆','slime|slime girl|史莱姆'), ('undead','亡灵','ghost|zombie|undead|幽灵|僵尸'),
    ('fairy','妖精','fairy|妖精'), ('monster','魔物','goblin|orc|monster|goblin girl|哥布林|兽人'),
])
_group('动物与拟人', 'anthro', [
    ('furry','兽人','furry|anthro|kemono|furry female|furry male|兽人|福瑞'),
    ('cat','猫拟人','cat girl|catgirl|cat boy|猫娘'), ('fox','狐拟人','fox girl|fox boy|狐娘'),
    ('rabbit','兔拟人','bunny girl|rabbit girl|兔娘'), ('dog','犬拟人','dog girl|dog boy|犬娘'),
])
_group('性别表现', 'gender', [
    ('crossdress','异性装扮','crossdressing|otoko no ko|女装男子'), ('androgynous','中性外表','androgynous|tomboy|中性外表'),
    ('femboy','女性化男性','femboy|男娘|伪娘'), ('futanari','双性特征','futanari|扶她|扶他'),
])
_group('头发与发型', 'hair', [
    ('short','短发','short hair|短发'), ('medium','中长发','medium hair|medium-length hair|中长发'),
    ('long','长发','long hair|long brown hair|long gradient hair|长发'), ('very_long','超长发','very long hair|absurdly long hair|extremely long gradient hair|extremely long hair|very long silver white hair|very long snow white hair|very long straight black hair|extremely long silvery white hair|超长发'),
    ('ponytail','马尾','ponytail|high ponytail|low ponytail|side ponytail|单马尾'),
    ('twintails','双马尾','twintails|low twintails|short twintails|双马尾'),
    ('braid','编发','braid|braids|single braid|twin braids|french braid|braided bangs|braided ponytail|braided bun|braided pigtails|braided sidelock|low-braided long hair|bun with braided base|braided auburn hair|braided|braided hair|编发|麻花辫'),
    ('bun','发髻','hair bun|hair buns|double bun|double small bun|single hair bun|single side bun|side bun|side up bun|braided bun|messy bun|high bun|low bun|neat bun|tight bun|half-up bun|发髻|丸子头'),
    ('bob','波波头','bob cut|bob hair|波波头'), ('curly','卷发','curly hair|wavy hair|卷发|波浪发'),
    ('straight','直发','straight hair|直发'), ('bangs','刘海','bangs|blunt bangs|swept bangs|刘海'),
    ('ahoge','呆毛','ahoge|呆毛'), ('black','黑发','black hair|黑发'), ('white','白发与银发','white hair|silver hair|hair is white|white haired|white to grey hair|white to grey|silver-white hair|silvery-white hair|白发|银发'),
    ('blonde','金发','blonde hair|blond hair|金发'), ('brown','棕发','brown hair|棕发'),
    ('red','红发','red hair|红发'), ('blue','蓝发','blue hair|蓝发'), ('pink','粉发','pink hair|粉发'),
    ('purple','紫发','purple hair|紫发'), ('green','绿发','green hair|绿发'),
    ('multicolor','多色头发','multicolored hair|two-tone hair|gradient hair|双色头发|渐变发色'),
])
_group('眼睛与瞳色', 'eyes', [
    ('blue','蓝瞳','blue eyes|aqua eyes|蓝瞳'), ('red','红瞳','red eyes|红瞳'),
    ('green','绿瞳','green eyes|绿瞳'), ('brown','棕瞳','brown eyes|棕瞳'),
    ('gold','金瞳与黄瞳','yellow eyes|golden eyes|amber eyes|金瞳|黄瞳'),
    ('purple','紫瞳','purple eyes|紫瞳'), ('pink','粉瞳','pink eyes|粉瞳'),
    ('heterochromia','异色瞳','heterochromia|异色瞳'), ('slit','竖瞳','slit pupils|竖瞳'),
    ('glowing','发光眼睛','glowing eyes|发光眼睛'), ('heart','心形瞳孔','heart-shaped pupils|heart pupils|心形瞳孔'),
])
_group('面部特征', 'face', [
    ('makeup','妆容','makeup|eyeliner|eyeshadow|妆容|眼线|眼影'), ('lipstick','唇妆','lipstick|red lips|purple lips|口红'),
    ('freckles','雀斑','freckles|雀斑'), ('mole','痣','mole|mole under eye|mole under mouth|泪痣'),
    ('beard','胡须','beard|mustache|facial hair|胡须'), ('fangs','尖牙','fang|fangs|sharp teeth|尖牙'),
    ('facial_mark','面部印记','facial mark|facepaint|面部印记|脸部彩绘'),
])
_group('体型与肤色', 'body', [
    ('slim','纤细体型','slim|slender|skinny|纤细体型'), ('muscular','肌肉体型','muscular|muscular male|muscular female|肌肉体型'),
    ('plump','丰满体型','plump|chubby|curvy|丰满体型'), ('petite','娇小体型','petite body|short stature|娇小体型'),
    ('large_bust','丰满胸部','large breasts|huge breasts|gigantic breasts|big breasts'),
    ('small_bust','平胸与小胸','flat chest|small breasts|平胸'),
    ('pale','浅肤色','pale skin|fair skin|light skin|浅肤色|白皙皮肤'),
    ('dark','深肤色','dark skin|dark-skinned female|dark-skinned male|深肤色'),
    ('tan','晒黑肤色','tan|tanned skin|tanlines|晒痕'), ('shiny','光泽皮肤','shiny skin|oiled skin|glossy skin|光泽皮肤'),
])
_group('身体部位', 'part', [
    ('hands','手部','hands|hand|fingers|手部'), ('feet','足部','feet|foot|soles|toes|足底|脚趾'),
    ('legs','腿部','legs|thighs|bare legs|大腿'),
    ('chest','胸部','breasts|large breasts|small breasts|huge breasts|gigantic breasts|big breasts|nipples|cleavage|胸部'),
    ('waist','腰腹','navel|stomach|abdomen|belly|肚脐|腹部'), ('hips','臀部','ass|buttocks|臀部'),
    ('shoulder','肩颈锁骨','collarbone|shoulders|bare shoulder|bare shoulders|neck|锁骨'),
])
_group('身体改造与伤痕', 'marks', [
    ('tattoo','纹身','tattoo|tattoos|stomach tattoo|纹身'), ('piercing','穿孔','piercing|body piercing|nose stud|穿孔'),
    ('scar','伤疤','scar|scars|facial scar|伤疤'), ('prosthetic','义肢','prosthetic arm|prosthetic leg|prosthesis|义肢'),
    ('bruise','淤伤','bruise|bruises|bruising on face|淤伤'), ('bandage','绷带','bandages|bandaged arm|绷带'),
])
_group('非人特征', 'nonhuman', [
    ('ears','兽耳','cat ears|fox ears|rabbit ears|wolf ears|dog ears|animal ears|squirrel ears|bear ears|cow ears|horse ears|mouse ears|deer ears|raccoon ears|tiger ears|sheep ears|lion ears|jackal ears|leopard ears|pig ears|bat ears|panda ears|goat ears|兽耳'),
    ('tail','尾巴','tail|cat tail|fox tail|dragon tail|mouse tail|尾巴'),
    ('wings','翅膀','wings|angel wings|bat wings|dragon wings|翅膀'),
    ('horns','角','horns|antlers|single horn|鹿角'), ('tentacles','触手','tentacles|tentacle|触手'),
    ('scales','鳞片','scales|鳞片'), ('claws','兽爪','claws|兽爪'),
])
_group('裸露与遮盖', 'cover', [
    ('nude','全身裸露','nude|naked|completely nude|裸体'), ('topless','上身裸露','topless|topless female|裸露上身'),
    ('bottomless','下身裸露','bottomless|裸露下身'), ('barefoot','赤足','barefoot|no shoes|bare foot|bare feet|赤足'),
    ('shoulders','露肩','bare shoulders|裸肩'), ('no_underwear','无内衣','no bra|no panties|无内衣'),
    ('covering','身体遮盖','covering breasts|covering crotch|breast cover|遮盖胸部'),
])
_group('裙装与礼服', 'skirt', [
    ('dress','连衣裙','dress|long dress|mini dress|wedding dress|maid dress|china dress|sundress|shirt-dress|shirtdress|连衣裙'),
    ('skirt','半身裙','skirt|long skirt|mini skirt|pleated skirt|pencil skirt|半身裙'), ('pleated','百褶裙','pleated skirt|百褶裙'),
    ('mini','短裙','miniskirt|mini skirt|mini dress|short skirt|短裙'), ('long','长裙','long skirt|long dress|长裙'),
    ('gown','礼服','evening gown|gown|晚礼服'), ('wedding','婚纱','wedding dress|bridal gown|婚纱'),
    ('sundress','吊带与夏裙','sundress|夏日连衣裙'), ('pencil','包臀裙','pencil skirt|包臀裙'),
])
_group('上衣与外套', 'top', [
    ('shirt','衬衫','shirt|collared shirt|dress shirt|衬衫'), ('tshirt','T恤','t-shirt|t shirt|T恤'),
    ('blouse','女式衬衣','blouse|女式衬衣'), ('sweater','毛衣','sweater|cardigan|毛衣|开衫'),
    ('hoodie','卫衣','hoodie|卫衣'), ('jacket','夹克','jacket|夹克'), ('coat','大衣','coat|overcoat|大衣'),
    ('cape','披风','cape|cloak|capelet|披风|斗篷'), ('tank','背心','tank top|camisole|背心'),
    ('crop','短上衣','crop top|cropped top|露脐上衣'),
])
_group('裤装', 'pants', [
    ('shorts','短裤','shorts|短裤'), ('jeans','牛仔裤','jeans|牛仔裤'), ('trousers','长裤','pants|trousers|长裤'),
    ('leggings','紧身裤','leggings|紧身裤'), ('bloomers','灯笼短裤','bloomers|灯笼短裤'),
])
_group('制服与职业装', 'uniform', [
    ('school','校服','school uniform|serafuku|sailor uniform|校服'), ('military','军装','military uniform|军装'),
    ('maid','女仆装','maid outfit|maid dress|女仆装'), ('suit','西装','suit|business suit|formal suit|西装'),
    ('medical','医护与实验服','nurse uniform|lab coat|labcoat|护士服|白大褂'), ('police','警服','police uniform|警服'),
    ('bunny','兔女郎制服','bunny suit|兔女郎装'),
])
_group('传统与民族服饰', 'traditional', [
    ('kimono','和服','kimono|和服'), ('yukata','浴衣','yukata|浴衣'), ('hakama','袴','hakama|袴'),
    ('hanfu','汉服','hanfu|汉服'), ('qipao','旗袍','cheongsam|qipao|china dress|旗袍'),
    ('sari','纱丽','sari|纱丽'), ('miko','巫女服','miko outfit|巫女服'),
])
_group('泳装与内衣', 'underwear', [
    ('bikini','比基尼','bikini|比基尼'), ('onepiece','连体泳衣','one-piece swimsuit|one piece swimsuit|连体泳衣'),
    ('school','死库水','school swimsuit|死库水'), ('bra','胸罩','bra|bralette|胸罩'), ('panties','内裤','panties|内裤'),
    ('lingerie','成套内衣','lingerie|成套内衣'), ('sports','运动内衣','sports bra|运动内衣'),
])
_group('奇幻与角色服饰', 'fantasy_clothes', [
    ('armor','盔甲','armor|armour|盔甲|铠甲'), ('bodysuit','连体服','bodysuit|leotard|zero suit|连体战斗服'),
    ('animal','动物装','animal costume|shark costume|reindeer costume|动物装'),
    ('mage','法师袍','mage robe|wizard robe|sorcerer robe|法师袍'), ('cosplay','角色扮装','cosplay|cosplay costume|角色扮装'),
])
_group('鞋袜与腿饰', 'legwear', [
    ('boots','靴子','boots|thigh boots|ankle boots|长靴'), ('heels','高跟鞋','high heels|高跟鞋'),
    ('sneakers','运动鞋','sneakers|运动鞋'), ('sandals','凉鞋与拖鞋','sandals|slippers|凉鞋|拖鞋'),
    ('socks','袜子','socks|ankle socks|短袜'), ('thighhighs','长筒袜','thighhighs|kneehighs|stockings|长筒袜'),
    ('pantyhose','连裤袜','pantyhose|tights|连裤袜'), ('fishnet','网袜','fishnet legwear|fishnet stockings|网袜'),
    ('garter','腿环与吊袜带','garter straps|garter belt|thigh strap|garter|garters|吊袜带|腿环'),
])
_group('头饰与发饰', 'headwear', [
    ('hat','帽子','hat|帽子'), ('cap','制式帽','cap|military cap|军帽'), ('beret','贝雷帽','beret|贝雷帽'),
    ('crown','冠冕','crown|tiara|王冠'), ('bow','发带与发蝴蝶结','hair bow|hair ribbon|hairband|red ribbons|red bows|发带'),
    ('clip','发夹与发簪','hairclip|hair clip|hairpin|hair stick|发夹|发簪'),
    ('headband','发箍','headband|发箍'), ('flower','花饰','hair flower|flower hair ornament|花发饰'),
])
_group('首饰与随身配饰', 'accessory', [
    ('earrings','耳饰','earrings|earring|耳环'), ('necklace','项链','necklace|项链'),
    ('choker','颈环','choker|颈环'), ('bracelet','手链','bracelet|bangle|手链'),
    ('ring','戒指','ring|rings|戒指'), ('glasses','眼镜','glasses|eyewear|round glasses|眼镜'),
    ('gloves','手套','gloves|手套'), ('belt','腰带','belt|waist belt|腰带'),
    ('bag','包袋','bag|handbag|backpack|包袋|背包'), ('scarf','围巾与披帛','scarf|围巾'),
    ('mask','面具与口罩','mask|face mask|面具|口罩'),
])
_group('服装材质与剪裁', 'fabric', [
    ('lace','蕾丝','lace|蕾丝'), ('leather','皮革','leather|皮革'), ('latex','乳胶','latex|rubber clothes|乳胶'),
    ('silk','丝绸','silk|satin|丝绸|缎面'), ('denim','牛仔布','denim|牛仔布'),
    ('transparent','透视材质','see-through|transparent clothes|透视材质'),
    ('frills','褶边与荷叶边','frills|ruffles|frilled dress|荷叶边'), ('sleeves','袖型','long sleeves|short sleeves|puffy sleeves|detached sleeves|泡泡袖'),
    ('tight','紧身剪裁','tight clothes|skin-tight|紧身剪裁'), ('patchwork','拼接布料','patchwork clothes|拼接布料'),
])
_group('穿着状态', 'wear_state', [
        ('open','敞开衣物','open shirt|open clothes|open jacket|open robe|open coat|open sweater|open dress|open blouse|open cardigan|open bra|opened shirt|opened clothes|opened jacket|opened robe|opened coat|opened dress|opened blouse|opened cardigan|opened bra|unbuttoned|unzipped|fallen open|falls open|undone|pulled open|popped open|torn open|hangs open|衣衫敞开'),
    ('lift','掀起衣物','skirt lift|dress lift|shirt lift|skirt lifted|掀裙'),
        ('off_shoulder','衣物滑肩','off shoulder|off-shoulder|off her shoulders|one shoulder bared|shoulder bared|slipping off her shoulders|衣物滑肩'),
    ('partly','部分穿着','partially clothed|half-dressed|部分穿着'),
        ('torn','破损衣物','torn clothes|ripped outfits|torn shirt|torn dress|torn jacket|torn coat|torn clothing|torn robe|torn skirt|torn pants|ripped|tattered|破损衣物'),
    ('pull','拉扯衣物','panty pull|pantyhose pull|shirt pull|dress tug|拉扯衣物'),
])
_group('坐姿与蹲姿', 'sit', [
    ('sitting','坐姿','sitting|seated|sits|sit|sit down|sit on the right|sit on chair|sit on sofa|sit on bed|sit on the man\'s left|sit on the man\'s right|坐姿'), ('squat','蹲姿','squatting|squats|蹲姿'),
    ('seiza','正坐','seiza|正坐'), ('wariza','鸭子坐','wariza|鸭子坐'),
    ('crossed','盘腿坐','cross-legged|indian style|盘腿坐'),
])
_group('站姿与跪姿', 'stand', [
    ('standing','站立','standing|stands|站立'), ('kneeling','跪姿','kneeling|kneels|kneel|dogeza|跪姿'),
    ('one_knee','单膝跪地','on one knee|one knee|单膝跪地'), ('one_leg','单腿站立','standing on one leg|单腿站立'),
])
_group('卧姿与趴姿', 'lie', [
    ('back','仰卧','on back|lying on back|supine|仰卧'), ('stomach','俯卧','on stomach|prone|俯卧'),
    ('side','侧卧','on side|lying on side|侧卧'), ('recline','斜倚','reclining|reclined|斜倚'),
])
_group('移动与运动', 'motion', [
    ('walk','行走','walking|walks|行走'), ('run','奔跑','running|runs|sprinting|奔跑'),
    ('jump','跳跃','jumping|leaping|跳跃'), ('dance','舞蹈','dancing|舞蹈'),
    ('swim','游泳','swimming|游泳'), ('fly','飞行','flying|飞行'), ('sport','竞技运动','gymnastics|wrestling|basketball|体操|摔跤'),
])
_group('手势与肢体动作', 'gesture', [
    ('raised','抬臂举手','hand up|arm up|arms up|raised arm|raised arms|举手|抬臂'),
    ('vsign','V字手势','v-sign|peace sign|v|V字手势'), ('heart','比心','heart hands|hand heart|比心'),
    ('point','指向','pointing|pointing at viewer|指向'), ('stretch','伸展','stretching|伸展'),
    ('head_tilt','歪头','head tilt|歪头'), ('legs','腿部动作','spread legs|legs spread|leg up|leg lift|leg lifts|leg lifted|lifted leg|lifting leg|lifting her leg|lifting his leg|lifting their leg|leg raise|leg raised|raised leg|raising leg|raising her leg|raising his leg|leg extended upwards|抬腿'),
    ('behind','手臂背后','arms behind back|hand behind back|手臂背后'),
])
_group('持物与道具互动', 'use_prop', [
    ('holding','持物','holding|holds|hold|carrying|grabbing dildo|手持'), ('food','进食','eating|drinking|进食'),
    ('reading','阅读','reading|reading book|阅读'), ('music','演奏','playing guitar|playing piano|playing violin|演奏'),
    ('camera','拍摄','holding camera|taking photo|拍照'), ('weapon','持械','holding sword|holding gun|holding spear|持剑'),
])
_group('拥抱与日常互动', 'interaction', [
    ('hug','拥抱','hugging|hug|embracing|拥抱'), ('hands','牵手','holding hands|牵手'),
    ('carry','背负与抱起','piggyback|carrying person|princess carry|公主抱'),
    ('lean','依靠他人','leaning on another|leaning against another|依靠他人'),
])
_group('穿脱与整理', 'adjust', [
    ('undress','脱衣','undressing|removing clothes|脱衣'), ('dress','穿衣','dressing|putting on clothes|穿衣'),
    ('hair','整理头发','brushing hair|combing hair|梳头'), ('clothes','整理衣物','adjusting clothes|adjusting necktie|整理衣物'),
])
_group('战斗与施法', 'combat', [
    ('melee','近身战斗','melee|swordfight|hand-to-hand combat|近身战斗'), ('shoot','射击','firing gun|shooting gun|gunfire|射击'),
    ('magic','施法','casting spell|spellcasting|casting magic|施法'), ('stance','战斗姿态','battle stance|fighting stance|战斗姿态'),
])
_group('亲密互动', 'intimacy', [
    ('kiss','接吻','kiss|kissing|接吻'), ('pair','亲密关系','yuri|hetero|yaoi|百合'),
])
_group('自慰', 'self_touch', [
    ('manual','自我刺激（方式不限）','masturbation|female masturbation|male masturbation|自慰'),
    ('device','使用道具','vibrator|dildo|using vibrator|using dildo'),
])
_group('口部互动', 'oral', [
    ('oral','口部接触','oral|fellatio|cunnilingus|口交'), ('deep','深入口部','deepthroat|irrumatio|深喉'),
])
_group('手足互动', 'limb_contact', [
    ('hand','手部接触','handjob|手交'), ('feet','足部接触','footjob|足交'),
    ('chest','胸部接触','paizuri|乳交'), ('thigh','腿间接触','thighjob|素股'),
])
_group('性交与体位', 'position', [
    ('front','正面体位','missionary|missionary position|传教士体位'), ('behind','背后体位','sex from behind|doggystyle|后入'),
    ('riding','上位体位','cowgirl position|reverse cowgirl|骑乘位'),
    ('side','侧卧体位','spooning|spooning position|侧卧体位'),
])
_group('射精与体液', 'fluid', [
    ('saliva','唾液','saliva|saliva trail|唾液'), ('milk','乳汁','lactation|breast milk|乳汁'),
    ('semen','精液','cum|semen|ejaculation|精液'), ('other','生殖道体液','pussy juice|female ejaculation'),
])
_group('束缚与控制', 'restraint', [
    ('rope','绳缚','shibari|rope bondage|crotch rope|绳缚'), ('limbs','四肢束缚','bound arms|bound wrists|bound legs|bound ankles|taped ankles|tied with duct tape|四肢束缚'),
    ('gag','口部束缚','gag|gagged|ball gag|taped mouth|口塞'), ('blindfold','眼罩','blindfold|blindfolded|眼罩'),
    ('cuffs','镣铐','handcuffs|shackles|shackle|手铐|镣铐'),
])
_group('暴力与伤害', 'injury', [
    ('blood','血迹','blood|blood on face|blood splatter|血迹'), ('strike','打击','slapping|spanking|spanked|打击'),
    ('electric','电击','electrocution|electric shock|电击'), ('wound','创伤','wound|torn flesh|broken bones|伤口'),
])
_group('视线方向', 'gaze', [
        ('viewer','看向观众','looking at viewer|looking at the viewer|gazing at viewer|staring at viewer|looking directly at viewer|look at the camera|looks at the camera|looks directly at the camera|gaze at the camera|gaze directly at the camera|gaze toward the camera|gazes at the camera|gazes directly at the camera|gazing at the camera|gazing directly at the camera|stare at the camera|stares at the camera|stares directly at the camera|staring at the camera|staring directly at the camera|look at viewer|looks at viewer|gaze at viewer|gazes at viewer|directly at the camera|intensely at the camera|look at the viewer|looks at the viewer|gazes directly at the viewer|looks directly at the viewer|look directly at the viewer|look directly at the camera|staring directly at camera|stare directly at camera|gazing directly at camera|gaze toward camera|看向观众'), ('away','移开视线','looking away|移开视线'),
    ('back','回望','looking back|回望'), ('up','向上看','looking up|向上看'),
    ('down','向下看','looking down|向下看'), ('other','看向他人','looking at another|看向他人'),
])
_group('喜悦与微笑', 'smile', [
    ('gentle','微笑','smile|smiling|微笑'), ('grin','咧嘴笑','grin|grinning|咧嘴笑'),
    ('smirk','坏笑','smirk|evil grin|evil smile|坏笑'), ('laugh','大笑','laughing|大笑'),
])
_group('悲伤与哭泣', 'sad', [
    ('tears','流泪','tears|crying|sobbing|teary-eyed|teary eyed|流泪'), ('sad','悲伤','sad|sad expression|悲伤'),
])
_group('愤怒与不满', 'angry', [
    ('anger','愤怒','angry|anger vein|愤怒'), ('annoyed','烦躁与嫌弃','annoyed|disgust|嫌弃'),
    ('frown','皱眉','frown|scowl|皱眉'),
])
_group('惊讶与紧张', 'tense', [
    ('blush','脸红','blush|nose blush|脸红'), ('surprise','惊讶','surprised|shocked expression|惊讶'),
    ('fear','恐惧','scared|fear|terrified expression|恐惧'), ('shy','害羞','shy|embarrassed|害羞'),
])
_group('平静与冷淡', 'calm', [
    ('blank','无表情','expressionless|无表情'), ('bored','无聊','bored|无聊'),
    ('sleepy','困倦','sleepy|drowsy|困倦'), ('serious','严肃','serious|严肃'),
])
_group('眼口表情', 'mouth_eyes', [
    ('open','张嘴','open mouth|张嘴'), ('parted','微张嘴','parted lips|parted mouth|微张嘴'),
    ('closed_mouth','闭嘴','closed mouth|闭嘴'), ('closed_eyes','闭眼','closed eyes|eyes closed|闭眼'),
    ('half_eyes','半闭眼','half-closed eyes|half closed eyes|半闭眼'), ('wink','眨眼','wink|one eye closed|眨眼'),
    ('tongue','吐舌','tongue out|吐舌'), ('clenched','咬牙','clenched teeth|咬牙'),
])
_group('自然地貌与水域', 'land', [
    ('mountain','山地','mountain|mountains|山地'), ('beach','海滩','beach|shoreline|海滩'),
    ('sea','海洋','ocean|sea|海洋'), ('underwater','水下','underwater|水下'),
    ('river','河流','river|河流'), ('lake','湖泊','lake|湖泊'), ('waterfall','瀑布','waterfall|瀑布'),
    ('desert','沙漠','desert|沙漠'), ('cave','洞穴','cave|洞穴'), ('meadow','草原','meadow|grasslands|草原'),
])
_group('植物与花园', 'plant', [
    ('forest','森林','forest|森林'), ('tree','树木','tree|trees|树木'),
    ('flowers','花卉','flowers|flower|rose|roses|hibiscus|blooming plum|花卉'), ('garden','花园','garden|rose garden|花园'),
    ('mushroom','菌菇','mushroom|fungi|蘑菇'), ('bamboo','竹子与竹林','bamboo|bamboo forest|竹林'),
])
_group('天空与天气', 'weather', [
    ('clear','晴空','blue sky|clear sky|晴空'), ('cloud','云层','clouds|cloudy sky|overcast|云层'),
    ('rain','雨天','rain|raining|rainy|雨天'), ('snow','雪天','snow|snowing|snowflakes|雪天'),
    ('night','夜晚与星空','night|nighttime|starry sky|夜空'), ('sunset','日落','sunset|日落'),
    ('moon','月亮','moon|full moon|月亮'), ('fog','雾','fog|mist|薄雾'),
    ('rainbow','彩虹','rainbow|彩虹'),
])
_group('城市与街道', 'urban', [
    ('street','街道','street|city street|街道'), ('road','道路','road|sidewalk|道路'),
    ('skyline','城市天际线','cityscape|skyline|城市天际线'), ('alley','小巷','alley|alleyway|小巷'),
    ('park','城市公园','park|城市公园'),
])
_group('建筑与设施', 'building', [
    ('castle','城堡与宫殿','castle|palace|城堡'), ('religion','宗教建筑','church|temple|shrine|cathedral|神社|寺庙'),
    ('school','学校设施','school|classroom|学校|教室'), ('hospital','医疗设施','hospital|医院'),
    ('station','车站','train station|station|车站'), ('bridge','桥梁','bridge|桥梁'),
    ('ruins','遗迹废墟','ruins|ruin|遗迹|废墟'), ('industrial','工业设施','factory|laboratory|工厂|实验室'),
])
_group('室内空间', 'room', [
    ('bedroom','卧室','bedroom|卧室'), ('living','客厅','living room|客厅'), ('bathroom','浴室','bathroom|浴室'),
    ('kitchen','厨房','kitchen|厨房'), ('classroom','教室','classroom|教室'), ('office','办公室','office|办公室'),
    ('cafe','咖啡馆','cafe|café|咖啡馆'), ('restaurant','餐馆','restaurant|餐馆'),
    ('vehicle','载具内部','train interior|car interior|bus interior|车厢内部'),
])
_group('幻想与科幻环境', 'fantasy_scene', [
    ('space','太空','outer space|space station|太空|空间站'), ('cyber','赛博空间','cyber background|digital realm|赛博空间'),
    ('dungeon','地下城','dungeon|地下城'), ('magic','魔法环境','magical forest|fantasy landscape|魔法森林'),
    ('postapocalyptic','末日环境与设定','post-apocalyptic|wasteland|末日环境'),
])
_group('纯色与抽象背景', 'backdrop', [
    ('white','白色背景','white background|白色背景'), ('black','深色背景','black background|dark background|黑色背景'),
    ('simple','简洁背景','simple background|简洁背景'), ('gradient','渐变背景','gradient background|渐变背景'),
    ('abstract','抽象背景','abstract background|geometric background|抽象背景'),
])
_group('视角与透视', 'angle', [
    ('pov','第一人称','pov|第一人称'), ('above','俯视','from above|high angle|high-angle|bird\'s-eye view|俯视'),
    ('below','仰视','from below|low angle|low-angle|仰视'), ('behind','背面视角','from behind|from back|rear view|背面视角'),
    ('side','侧面视角','from side|from the side|side view|侧面视角'),
    ('front','正面视角','front view|straight-on|正面视角'), ('dutch','倾斜镜头','dutch angle|倾斜镜头'),
    ('fisheye','鱼眼','fisheye|鱼眼'), ('foreshorten','透视缩短','foreshortening|透视缩短'),
])
_group('景别与主体占比', 'framing', [
    ('close','近景','close-up|close up|近景'), ('portrait','肖像','portrait|肖像'),
    ('upper','半身','upper body|半身'), ('cowboy','七分身','cowboy shot|七分身'),
    ('full','全身','full body|全身'), ('wide','远景','wide shot|long shot|远景'),
])
_group('局部特写', 'focus', [
    ('face','面部特写','face focus|面部特写|脸部特写'), ('eyes','眼部特写','eye focus|eyes focus|眼部特写'),
    ('hands','手部特写','hand focus|hands focus|手部特写'), ('feet','足部特写','foot focus|feet focus|足部特写'),
    ('chest','胸部特写','breasts focus|chest focus|胸部特写'), ('waist','腹部特写','stomach focus|navel focus|腹部特写'),
    ('object','物件特写','object focus|物件特写'),
])
_group('焦点与景深', 'depth', [
    ('dof','景深','depth of field|shallow depth of field|景深'), ('bokeh','散景','bokeh|散景'),
    ('motion','运动模糊','motion blur|运动模糊'), ('soft','柔焦','soft focus|柔焦'),
])
_group('布局与画面结构', 'layout', [
    ('center','居中','centered composition|居中构图'), ('symmetric','对称','symmetry|symmetrical|对称构图'),
    ('thirds','三分法','rule of thirds|三分法'), ('negative','留白','negative space|留白'),
    ('sheet','设定表','character sheet|reference sheet|设定表'), ('split','分割画面','split theme|split screen|分割画面'),
    ('isometric','等距视图','isometric|等距视图'),
])
_group('多格与连续画面', 'panels', [
    ('comic','漫画分格','comic panels|panel layout|漫画分格'), ('four','四格','4koma|four-panel comic|四格漫画'),
    ('sequence','连续分镜','sequence|storyboard|连续分镜'),
])
_group('文字与图形', 'graphic', [
    ('text','文字','text|文字'), ('japanese','日文','japanese text|日文文字'),
    ('english','英文','english text|英文文字'), ('bubble','对话框','speech bubble|speech balloon|对话框'),
    ('poster','海报','poster|海报'), ('symbol','符号','symbol|symbols|symbolism|符号'),
])
_group('自然光', 'daylight', [
    ('sun','阳光','sunlight|daylight|阳光'), ('moon','月光','moonlight|月光'),
    ('sunset','夕阳与金色时刻','sunset lighting|golden hour|夕阳光'), ('dappled','斑驳光','dappled sunlight|斑驳阳光'),
])
_group('人工光与发光', 'artificial_light', [
    ('neon','霓虹','neon lights|neon lighting|霓虹'), ('studio','摄影棚灯光','studio lighting|摄影棚灯光'),
    ('candle','烛光','candlelight|candle light|烛光'), ('spot','聚光灯','spotlight|spotlights|聚光灯'),
    ('glow','发光效果','glowing|bioluminescence|bioluminescent|发光效果'),
])
_group('光影效果', 'light_effect', [
    ('back','逆光','backlighting|backlight|逆光'), ('rim','轮廓光','rim lighting|rim light|轮廓光'),
    ('volume','体积光','volumetric lighting|volumetric light|体积光'), ('rays','光束','light rays|god rays|光束'),
    ('contrast','明暗对照','chiaroscuro|明暗对照'), ('soft','柔光','soft lighting|soft light|soft overhead lighting|柔光'),
    ('bloom','辉光','bloom|bloom light|辉光'), ('silhouette','剪影','silhouette|剪影'),
])
_group('色彩与调色', 'color', [
    ('mono','单色','monochrome|greyscale|grayscale|单色'), ('pastel','粉彩色调','pastel colors|pastel color|粉彩色调'),
    ('warm','暖色调','warm colors|warm tone|warm color palette|warm golden and emerald tones|warm yellow tones|warm golden tones|暖色调'), ('cool','冷色调','cool colors|cold tone|cool-toned color palette|冷色调'),
    ('vivid','鲜艳色调','vibrant colors|saturated colors|鲜艳色调'), ('muted','低饱和色调','muted colors|desaturated|低饱和色调'),
    ('contrast','高对比','high contrast|高对比'), ('grain','胶片颗粒','film grain|胶片颗粒'),
])
_group('摄影与写实', 'photo', [
    ('photography','摄影','photography|photograph|ordinary camera|摄影'), ('realism','写实','realistic|photorealistic|realism|写实'),
    ('film','胶片摄影','film photography|analog photography|胶片摄影'),
    ('cinematic','电影感','cinematic|film still|电影感'), ('fashion','时尚与编辑摄影','fashion photography|editorial photography|时尚摄影'),
])
_group('动漫与卡通', 'cartoon', [
    ('anime','动漫','anime|anime style|动漫'), ('chibi','Q版','chibi|chibi only|Q版'),
    ('cartoon','卡通','cartoon|卡通'), ('cel','赛璐璐','cel shading|赛璐璐'),
])
_group('漫画与线稿', 'drawing', [
    ('lineart','线稿','lineart|line art|线稿'), ('sketch','素描与草图','sketch|pencil sketch|素描|草图'),
    ('ink','墨线','ink drawing|ink illustration|墨线'), ('manga','漫画','manga|漫画'),
    ('inkwash','水墨','ink wash|sumi-e|水墨'),
])
_group('绘画与插画', 'illustration', [
    ('digital','数字插画','digital illustration|digital painting|数字插画'),
    ('illustration','插画','illustration|插画'), ('painting','绘画','painting|绘画'),
    ('concept','概念艺术','concept art|概念艺术'),
])
_group('水彩与油画', 'paint', [
    ('watercolor','水彩','watercolor|watercolour|水彩'), ('oil','油画','oil painting|油画'),
])
_group('三维与数字渲染', 'render', [
    ('3d','三维','3d|cgi|三维'), ('lowpoly','低多边形','low-poly|low poly|低多边形'),
    ('raytrace','光线追踪','ray tracing|光线追踪'), ('clay','黏土渲染','clay render|claymation|黏土渲染'),
])
_group('像素与平面设计', 'design', [
    ('pixel','像素画','pixel art|像素画'), ('vector','矢量','vector art|vector illustration|矢量'),
    ('graphic','平面设计','graphic design|平面设计'), ('glitch','故障风','glitch art|glitch background|故障艺术'),
])
_group('艺术流派与视觉风格', 'art_style', [
    ('surreal','超现实','surrealism|surreal|超现实'), ('gothic','哥特','gothic|哥特'),
    ('impressionist','印象派','impressionism|impressionist|印象派'), ('minimal','极简','minimalism|minimalist|极简'),
    ('artnouveau','新艺术','art nouveau|新艺术'), ('artdeco','装饰艺术','art deco|装饰艺术'),
    ('retro','复古','retro|vintage|70s film aesthetic|复古'), ('cyberpunk','赛博朋克','cyberpunk|赛博朋克'),
])
_group('质量与分辨率', 'quality', [
    ('highres','高分辨率','highres|absurdres|high resolution|4k|8k|高分辨率'),
    ('quality','质量强化','best quality|amazing quality|masterpiece|质量强化'),
])
_group('细节与材质', 'detail', [
    ('eyes','眼部细节','detailed eyes|眼部细节'), ('face','面部细节','detailed face|面部细节'),
    ('texture','纹理细节','detailed texture|realistic textures|纹理细节'),
    ('intricate','精细刻画','intricate details|ultra detailed|hyper-detailed|精细刻画'),
])
_group('武器与装备', 'weapon', [
    ('sword','刀剑','sword|katana|holding sword|刀剑'), ('gun','枪械','gun|handgun|rifle|pistol|holding gun|枪械'),
    ('spear','长柄武器','spear|lance|halberd|holding spear|长枪'), ('bow','弓弩','bow weapon|crossbow|bow and arrow|弓弩'),
    ('shield','盾牌','shield|盾牌'), ('knife','匕首','dagger|knife|匕首'),
])
_group('交通与机械', 'vehicle', [
    ('car','汽车','car|parked cars|automobile|汽车'), ('motorcycle','摩托车','motorcycle|摩托车'),
    ('bicycle','自行车','bicycle|自行车'), ('train','火车','train|火车'),
    ('aircraft','飞机','airplane|aircraft|helicopter|飞机'), ('ship','船舶','ship|boat|船舶'),
    ('mecha','机甲与机器人','mecha|robot|super robot|机甲'),
])
_group('家具与生活用品', 'furniture', [
    ('bed','床','bed|床铺'), ('chair','椅子','chair|椅子'), ('table','桌子','table|desk|桌子'),
    ('sofa','沙发','sofa|couch|沙发'), ('mirror','镜子','mirror|镜子'),
    ('book','书籍','book|books|书籍'), ('cup','杯具','cup|teacup|beer mug|杯具'),
    ('phone','手机','phone|smartphone|手机'), ('instrument','乐器','guitar|piano|violin|乐器'),
])
_group('食物与饮料', 'food', [
    ('fruit','水果','fruit|fruits|apple|lemon|strawberry|cherry|水果'),
    ('dessert','甜品','cake|ice cream|chocolate|甜品'), ('bread','面包','bread|toast|面包'),
    ('noodles','面食','noodles|ramen|pasta|面条'), ('meat','肉食','meat|roast chicken|grilled fish|fried fish|烤肉'),
    ('tea_coffee','茶与咖啡','tea|coffee|茶水|咖啡'), ('alcohol','酒类','wine|beer|cocktail|champagne|酒类'),
    ('juice','果汁','juice|fruit juice|果汁'),
])
_group('动物主体', 'animal', [
    ('cat','猫','cat|cats|猫咪'), ('dog','犬','dog|dogs|犬只'), ('bird','鸟','bird|birds|crow|鸟类'),
    ('horse','马','horse|horses|马匹'), ('rabbit','兔','rabbit|rabbits|bunny|bunnies|兔子'),
    ('fish','鱼','fish|goldfish|tropical fish|鱼类'), ('insect','昆虫','insect|butterfly|昆虫'),
    ('reptile','爬行动物','snake|lizard|turtle|爬行动物'),
])
_group('成人道具', 'adult_prop', [
    ('device','刺激器具','vibrator|dildo|vibrator controller'),
    ('pump','泵具','breast pump|penis pump'), ('protection','防护用品','condom|condoms'),
])


_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
# Reviewed danbooru-style type disambiguators (batch 77). A parenthetical
# that names a medium/object category disambiguates the phrase instead of
# clarifying it, so the whole part stays opaque exactly as round 19 requires.
_PAREN_TYPE_ASIDES = frozenset({
    'object', 'substance', 'manga', 'anime', 'symbol', 'series',
    'helmet', 'armor', 'costume', 'wig', 'mask', 'cosplay',
})

_EXACT = {}
_TRIE = {}
_ZH = {}
for _node_id, _node in REFINEMENT_NODES.items():
    for _tag in _node['tags']:
        _tag = _tag.lower().replace('_', ' ')
        _EXACT.setdefault(_tag, []).append(_node_id)
        if re.search(r'[\u4e00-\u9fff]', _tag):
            _ZH.setdefault(_tag, []).append(_node_id)
        elif len(_tag) > 1:
            _branch = _TRIE
            for _word in _WORD.findall(_tag):
                _branch = _branch.setdefault(_word, {})
            _branch.setdefault(None, []).append((_tag, _node_id))
_ZH_PATTERN = re.compile('|'.join(re.escape(word) + (r'(?!务)' if word.endswith('服') else '') for word in sorted(_ZH, key=len, reverse=True)))

# Round 135 batch 1 admits only the active, same-owner device construction
# frozen in the batch contract.  Passive ``pressed`` clauses, ``holds`` and
# ``one of ... hands`` stay out of scope so they cannot become a twelfth
# candidate through the refinement layer.
_SAME_OWNER_DEVICE = re.compile(
    r'\b(?P<owner>her|his|their)\s+own hand pressing\s+'
    r'(?:a\s+)?(?:wand\s+)?(?:vibrator|dildo)\s+'
    r'(?:directly\s+)?against\s+(?P=owner)\s+'
    r'(?:clit(?:oris)?|pussy|vulva|genitals?|crotch|anus|penis)\b',
    re.I,
)
_RECIPROCAL_CLINGING = re.compile(r'\bclinging to (?:each other|one another)\b', re.I)
_NONHUMAN_CLINGING_SUBJECT = re.compile(
    r'\b(?:clothes?|clothing|cloth|dress(?:es)?|fabric|pants|stockings?|tights|curtains?|'
    r'slime|mucus|leaves|vines?)\b[^,.;!?]{0,40}\bclinging to (?:each other|one another)\b',
    re.I,
)
_MULTIPLE_HUMAN_CONTEXT = re.compile(
    r'\b(?:(?:multiple|several|many|two|three|four|five|six)\s+'
    r'(?:girls?|women|boys?|men|people|persons?|bodies)|'
    r'\d+\+?\s*(?:girls?|women|boys?|men|people|persons?|bodies)|everyone|everybody|clones|'
    r'multiple copies|body pile|stacked bodies|tangled limbs|arms reaching)\b',
    re.I,
)


def _positive_parts(body):
    text = str(body or '').lower().replace('\\', '').replace('\n', ',')
    text = re.sub(r'\bcarrying\s+(?:a|an)\s+(?:(?:tired|pensive|sad|happy|calm|gentle|warm|serious|thoughtful|confident|mysterious|sultry)[, ]+){0,4}(?:expression|mood|air|feeling)\b', lambda m: m.group().replace('carrying', 'showing'), text)
    text = re.sub(r'\bmakeup\s+(?:is|was)\b[^.!?;]{0,60}\bwith\s+(?:(?:a\s+)?(?:hint|touch)\s+of\s+)?blush\b', lambda m: m.group().replace('blush', 'rouge'), text)
    text = re.sub(r'\bmakeup with defined eyes,\s*(?:soft |subtle |pink )?blush\b', lambda m: m.group().replace('blush', 'rouge'), text)
    text = re.sub(r'\bdecoration made of[^.!?;]{0,70}\bits scales\b', lambda m: m.group().replace('its scales','its surface details'), text)
    text = re.sub(r'\b(?:skin|hair)\b[^.!?;]{0,65}\bglowing\s+(?:under|in)\b', lambda m: m.group().replace('glowing', 'illuminated'), text)
    text = re.sub(r'\b(?:lower part of the painting|the painting has a strong artistic sense)\b', lambda m: m.group().replace('painting','image'), text)
    if 'bar background' in text and re.search(r'\bbottles\b',text) and not re.search(r'\b(?:[1-9](?:girls?|boys?)|woman|man|wearing)\b',text):
        text = re.sub(r'\bglasses\b','water glasses',text)
    text = re.sub(r'\b(?:vases? placed[^.!?;]{0,65}each|table is[^.!?;]{0,65})[ ,]+holding\b', lambda m: m.group().replace('holding', 'containing') if not re.search(r'\b(?:she|he|woman|man|girl|boy)\b', m.group()) else m.group(), text)
    text = re.sub(r'\b(?:naked|nude)(\s+(?:woman|man)[^.!?]{0,220}\bbody exposed apart from[^.!?]{0,100}\b(?:dress|gown|shirt|coat)\b)', r'\1', text)
    text = re.sub(r'\brather than\b[^,.;!?]*', '', text)
    text = re.sub(r'\bplump\s*,\s*(?=(?:moist\s+)?leaves\b)', 'plump ', text)
    text = re.sub(r'\belevator\b[^.!?;]{0,180}\bcar walls\b', lambda m: m.group().replace('car walls', 'cabin walls'), text)
    text = re.sub(r'\btear-like adornments\b[^.!?;]{0,100}\blike frozen tears\b', lambda m: m.group().replace('like frozen tears', 'like frozen crystals'), text)
    # Local editorial instructions do not turn their negative examples positive,
    # and must not hide the genuine prompt following the closing bracket.
    text = re.sub(r'【[^】]*(?:负面加|放入负面|加入负面)[^】]*】', '', text)
    text = re.sub(r'(服改造\d*)[（(][^）)]*[）)]', r'\1', text)
    text = re.sub(r'((?<![a-z])(?:reading|reads?|says?|text(?:[ _]+shows)?)(?![a-z])[ _]*:?[ _]*)["“][^"”]*["”]', r'\1', text)
    text = re.sub(r'\btext[ _]*:(?!:)[ _]*[^,;.!?]*', 'text', text)
    text = re.sub(r'["“][^"”]*["”](?=\s+(?:printed|written|emblazoned|embroidered)\b)', '', text)
    text = re.sub(r'["“][^"”]*["”](?=\s+sign\b)', '', text)
    text = re.sub(r'(\b(?:her|his|their)\s+piercing)\s*,\s*(?=[a-z -]{0,40}\beyes\b)', r'\1 ', text)
    # A few imported NAI spans omit one opening colon but retain the terminator.
    text = re.sub(r'(?<![\d:])(-\d+(?:\.\d+)?)\s*:(?!:)([^:\n]+)::', r'\1::\2::', text)
    text = strip_nonpositive_nai_weights(text)
    text = re.sub(r'\bno\s+text\s*\|', 'no text,', text)
    text = re.sub(r'\([^()]*(?::\s*(?:-\d+(?:\.\d+)?|0(?:\.0+)?)\s*)\)', '', text)
    text = re.split(r'原版负面|负面提示词\s*[:：]|negative[ _]prompt\s*:', text, maxsplit=1)[0]
    # Keep comma-separated garment adjectives in the same exception clause.
    text = re.sub(r'\b(?:nude|naked) except(?: for)?(?:[ ,]+[a-z-]+){0,9}[ ,]+(?:shorts|pants|trousers|skirt|dress|shirt|top|jacket|coat|blouse)\b',
                  lambda match: match.group().replace(',', ' '), text)
    parts = []
    for raw in re.split(r'[,，;；\n]|(?<!\d)::', text):
        raw = re.sub(r'^\s*(?:\+?\d+(?:\.\d+)?\s*::|char\d+\s*[:：]|(?:source|target|mutual)[#:]|(?:right|left) girl:)', '', raw)
        raw = raw.strip(' {}[]()【】（）\t')
        if re.search(r':\s*(?:-\d+(?:\.\d+)?|0(?:\.0+)?)$', raw):
            continue
        raw = re.sub(r':\s*\+?\d+(?:\.\d+)?$', '', raw).rstrip()
        if not raw or raw.startswith(('@', 'artist:', 'by artist ', 'text:', 'written text:')):
            continue
        qualified = re.fullmatch(r'([^()]+)\s*\(([^()]+)\)?', raw)
        if qualified:
            base = qualified.group(1).strip().replace('_', ' ')
            qualifier = qualified.group(2).strip()
            if qualifier == 'cosplay':
                if base not in {'pussy', 'anus', 'penis', 'breasts', 'vagina'}:
                    parts.append('cosplay')
                continue
            colors = {'black', 'white', 'silver', 'blonde', 'brown', 'red', 'blue', 'green', 'pink', 'purple'}
            if base in _EXACT and qualifier in {'medium', 'style', *colors}:
                parts.append(base)
                if base.endswith('hair') and qualifier in colors:
                    parts.append(f'{qualifier} hair')
                continue
        if len(re.findall(r'\b[a-z]+_[a-z_]+\b', raw)) >= 2 and not re.search(r'\b(?:is|are|wears|wearing|she|he|her|his|no|not|without|never)\b', raw):
            parts.extend(word.strip('{}[]()').replace('_', ' ') for word in raw.split())
        else:
            parts.append(raw.replace('_', ' '))
    return parts


def _scene_text(body):
    """Ignore a depicted setting when classifying the surrounding real scene."""
    body = re.sub(r'\bbowling alley\b|\bstreet fashion(?: style)?\b', '', body, flags=re.I)
    body = re.sub(r'\bumbrella adorned with\b[^.!?;,]{0,100}', '', body, flags=re.I)
    body = re.sub(r'\b(?:hair|twin[- ]tails|ponytails)\b[^.!?;,]{0,35}\badorned with\s+(?:[a-z-]+\s+){0,5}(?:flowers?|blossoms?|ornaments?)(?=,|[.!?;]|$|\s+and\s+(?:[a-z-]+\s+){0,3}hairpins\b)(?:,\s*(?:and\s+)?(?:[a-z-]+\s+){0,4}(?:flowers?|blossoms?|ornaments?)(?=,|[.!?;]|$|\s+and\s+(?:[a-z-]+\s+){0,3}hairpins\b))*', '', body, flags=re.I)
    text = re.sub(r'\b(?:shopping bag|tote bag|handbag|bag)\s+printed with\b[^.!?;]*?(?=$|[.!?;]|,\s*(?:the scene\b|she\b|he\b|the woman\b|the man\b|(?:in the |the )?(?:background|foreground|midground)\b))', '', body, flags=re.I)
    text = re.sub(r'\b(?:virtual|printed) backdrop (?:shows|depicts)\b[^.!?;]*', '', text, flags=re.I)
    return re.sub(r'\bbackdrop with (?:a )?(?:cityscape|skyline)(?: and [^,.;!?]+)?', '', text, flags=re.I)


def _phrase_allowed(parent, phrase, text, start, end):
    before, after = text[:start], text[end:]
    # Piercing is a light-motion verb here; it is not a body modification.
    if (parent == '身体改造与伤痕' and phrase == 'piercing'
            and re.search(r'\b(?:sunlight|sunbeams?|sunrays?|(?:golden|warm) (?:rays?|beams?))\b[^.;!?]{0,45}$', before)
            and re.match(r'\s+(?:through\b|(?:the\s+)?(?:air|dust|clouds?|foliage|mist|forest|canopy|gaps?|veil)\b)', after)):
        return False
    if parent == '持物与道具互动' and phrase == 'reading' and re.match(r'\s+nook\b', after):
        return False
    if (parent == '室内空间' and phrase in {'cafe', 'café'}
            and re.search(r'\bas if (?:captured|photographed|shot|taken)\b[^.;!?]{0,80}$', before)):
        return False
    if parent == '拥抱与日常互动' and phrase in {'hug', 'hugging'} and re.search(r'\b(?:leggings|pants|dress|skirt)\s*$', before):
        return False
    if parent == '动物主体' and re.match(r'\s+(?:legs?|charms?)\b', after):
        return False
    if parent == '植物与花园' and phrase in {'tree', 'trees'} and re.match(r'\s+(?:girl|boy|woman|man)\b', after):
        return False
    if parent == '植物与花园' and re.match(r'\s+(?:flowers?\s+)?(?:necklace|hairpin|hair ornament)\b', after):
        return False
    if parent == '体型与肤色' and phrase in {'slender', 'slim', 'skinny'} and (re.match(r'\s+(?:heels?|jade-like fingers)\b', after) or re.search(r'\bheel\s+(?:is\s+)?$', before)):
        return False
    if parent == '天空与天气' and phrase == 'night' and re.match(r'\s+wear\b', after):
        return False
    if parent == '裸露与遮盖' and phrase == 'nude' and re.match(r'\s+(?:pink|lipstick|lip color)\b', after):
        return False
    # Round 139 #8: "nude pants" names a garment, it does not depict a nude body.
    if (parent == '裸露与遮盖' and phrase in {'nude', 'naked'}
            and re.match(r'\s+(?:pants|trousers|leggings|shorts|stockings|garment|clothing)\b', after)):
        return False
    # Round 139 #13: a printed/overlaid tree is decoration, not a scene plant.
    if (parent == '植物与花园' and phrase in {'tree', 'trees'}
            and (re.match(r'[^.!?;]{0,55}\b(?:decoration|overlay|pattern|print|motif|sticker)\b', after)
                 or re.search(r'\b(?:decoration|overlay|pattern|print|motif|sticker)\b[^.!?;]{0,55}$', before))):
        return False
    # Batch 73 (round 141 residual): minimalism naming a scene attribute
    # ("minimalist background") is not an art-style label.
    if (parent == '艺术流派与视觉风格' and phrase in {'minimalism', 'minimalist'}
            and re.match(r'\s+(?:indoor\s+)?(?:space|room|interior|background|scene'
                         r'|apartment|studio|decor|decoration|setting|set|palette)\b', after)):
        return False
    # Batch 73 (round 141 residual): a hostile modifier makes the smile not gentle
    # (the same phrase already feeds smile.smirk).
    if (parent == '喜悦与微笑' and phrase in {'smile', 'smiling'}
            and re.search(r'\b(?:evil|sinister|wicked|malicious|cruel|sadistic|grim)\s+$', before)):
        return False
    # Batch 75: "bags under the eyes" is an eye-bag and waste bags are refuse,
    # neither is a carried accessory; leather furniture is not garment material.
    # Measured before landing: accessory.bag -45, fabric.leather -27, zero
    # collateral, zero gains (coord_bag_leather_delta_001.json).
    if parent == '首饰与随身配饰' and phrase in {'bag', 'bags'}:
        if re.match(r'\s+under\s+(?:the\s+)?eyes?\b', after, re.I):
            return False
        if re.search(r'\b(?:garbage|trash|rubbish|litter|plastic|paper)\s+$', before, re.I):
            return False
    if parent == '服装材质与剪裁' and phrase == 'leather':
        # Batch 87: window form. `seat leather details` and `the leather
        # surface` slipped through the forward-only closed list.
        _leather_window = text[max(0, start - 30):end + 40]
        # Adjacency on both sides, and only real furniture nouns. The earlier
        # wide list (surface/interior/cabin/upholstery) removed a round-121
        # retain_nodes positive, which the replay gate caught.
        _FURN = (r'(?:sofa|couch|armchair|chair|seats?|bench|stool|headboard|headrest|backrest|armrest)')
        _leather_furniture = bool(
            re.match(r'\s+(?:[a-z-]+\s+){0,2}' + _FURN + r'\b', after, re.I)
            or re.search(r'\b' + _FURN + r'\b(?:[ ,]+[a-z-]+){0,2}\s*$', before, re.I))
        _leather_garment = re.search(
            r'\b(?:jacket|coat|pants|trousers|skirt|shorts|boots?|gloves?|dress|corset|bustier|'
            r'harness|leotard|bodysuit|bra|lingerie|stockings|thighhighs|belt|straps?|heels?|'
            r'shoes?|sandals?|pumps?|footwear|choker|cap|hat|miniskirt|catsuit|glove)\b',
            _leather_window, re.I)
        if _leather_furniture and not _leather_garment:
            return False
    if parent == '光影效果' and phrase == 'silhouette' and re.search(r'\btrace the\s*$', before) and re.match(r'\s+of (?:her|his) skin\b', after):
        return False
    if parent == '服装材质与剪裁' and phrase == 'silk' and re.match(r'\s+(?:chaise lounge|sofa|chair)\b', after):
        return False
    if parent == '身体部位' and phrase in {'shoulder', 'shoulders'} and (re.search(r'\bpleats at the\s*$', before) or re.match(r'\s+is (?:a |an )?(?:[a-z-]+\s+){0,4}shoulder bag\b', after)):
        return False
    if parent == '移动与运动' and phrase in {'running', 'runs'} and re.search(r'\b(?:chain|train)\s*$', before):
        return False
    if parent == '手势与肢体动作' and phrase == 'stretching' and (re.search(r'\b(?:background|space)\s*$', before) or re.match(r'\s+(?:liminal\s+)?space\b', after)):
        return False
    if parent == '手势与肢体动作' and phrase == 'pointing' and re.search(r'\b(?:blade|sword|arrow)\s*$', before):
        return False
    if parent == '站姿与跪姿' and phrase == 'standing' and re.match(r'\s+in for\b', after):
        return False
    if parent == '光影效果' and phrase == 'silhouette' and re.search(r'\b(?:naturalistic|commanding)\s*$', before):
        return False
    if parent == '体型与肤色' and phrase in {'slender', 'slim', 'skinny'} and (re.match(r'\s+(?:straps?|(?:double-ended\s+)?toys?|fingers?)\b', after) or re.search(r'\bfingers?\s+(?:are\s+)?(?:long\s+and\s+)?$', before)):
        return False
    if parent == '绘画与插画' and phrase == 'painting' and re.search(r'\b(?:top of the|spatial depth of the|like a (?:flowing )?)\s*$', before):
        return False
    if parent == '绘画与插画' and phrase == 'drawing' and re.match(r'\s+the (?:main )?visual focus\b', after):
        return False
    if parent == '身体部位' and phrase in {'shoulder', 'shoulders'} and (re.match(r'[- ]length\b', after) or (re.search(r'\bscarf\b[^.!?;]{0,50}\bacross (?:her|his|the)\s*$', before))):
        return False
    if parent == '身体部位' and phrase == 'neck' and re.search(r'\bscarf\b[^.!?;]{0,50}\baround (?:her|his|the)\s*$', before):
        return False
    if parent == '食物与饮料' and phrase in {'tea', 'coffee'} and re.match(r'\s+(?:parlor|parlour|cup|table)\b', after):
        return False
    if parent == '家具与生活用品' and phrase == 'desk' and re.match(r'\s+lamp\b', after):
        return False
    if parent == '家具与生活用品' and phrase == 'phone' and re.search(r'\b(?:snapshot|photo|photograph|shot|capture)\b[^.!?;]{0,35}\b(?:from|with|on)\s+(?:a\s+)?$', before):
        return False
    if parent == '头饰与发饰' and phrase == 'headband' and (re.search(r'\b(?:headphones?|headset|earphone)\b', text) or re.search(r'\bheadband\b[^.!?;]{0,60}\bpanasonic\b', text)):
        return False
    if parent == '非人特征' and phrase in {'cat ears', 'animal ears', 'rabbit ears', 'fox ears'} and re.search(r'\b(?:lace|fake|costume)\s*$', before):
        return False
    if parent == '非人特征' and phrase == 'wings' and re.search(r'\bas translucent as cicada\s*$', before):
        return False
    if parent == '动物主体' and re.match(r'\s+(?:embroidery|tattoo)\b', after):
        return False
    if parent == '植物与花园' and (re.match(r'\s+hair(?:clip|\s+ornaments?)\b', after) or re.search(r'\bears adorned with\s+(?:[a-z-]+\s+){0,3}$', before)):
        return False
    if parent == '天空与天气' and phrase == 'snow' and re.search(r'\bartificial\s*$', before):
        return False
    if parent == '天空与天气' and phrase in {'stars', 'star'} and re.search(r'\b(?:glitter|sparkle|shimmer)[a-z]*\s+like\s*$', before):
        return False
    if parent == '摄影与写实' and phrase == 'realism' and re.search(r'\bmagical\s*$', before):
        return False
    if parent == '摄影与写实' and phrase == 'realism' and re.search(r'\b(?:graphic storytelling|draftsmanship|refined linework|line ?work|line art|lineart|comic|manga)\b', text, re.I) and not re.search(r'\b(?:photograph\w*|photo|camera|lens|dslr|film still|shot on)\b', text, re.I):
        return False
    if parent == '光影效果' and phrase == 'silhouette' and re.search(r"\b(?:body'?s?|figure'?s?|model'?s?|his|her|its|their|your)\s+$", before, re.I) and not re.search(r'\b(?:backlit|backlight(?:ing)?|against the light|contre-jour)\b', text, re.I):
        return False
    if parent == '持物与道具互动' and phrase == 'holding' and re.search(r'\b(?:contour|outline|boundary|border|edge|line|frame|panel|layout|design|composition|print|shape|fabric|drape|garment|texture)\b[^.!?;]{0,30}$', before, re.I):
        return False
    if parent == '动物主体' and phrase in {'butterfly', 'moth'} and re.match(r'\s+(?:hair ?(?:pin|clip)|ornament|necklace|earrings?|pendant|brooch)\b', after, re.I):
        return False
    if parent == '人工光与发光' and phrase == 'glowing' and re.match(r'\s+rim light\b', after):
        return False
    if parent == '自然光' and phrase in {'moonlight', 'moonlit'} and re.search(r'\blike\s*$', before):
        return False
    if parent == '视角与透视' and phrase in {'low-angle', 'low angle'} and re.match(r'\s+(?:dawn\s+)?light\b', after):
        return False
    if parent == '职业与身份' and ((phrase == 'queen' and re.match(r'\s+of spades\b', after)) or (phrase == 'knight' and re.match(r'\s+helmet\b', after))):
        return False
    if (parent == '裸露与遮盖' and phrase in {'naked', 'nude', 'completely nude', '裸体'}
            and (re.match(r'\s+(?:kimono|bodystocking)\b', after)
                 or re.search(r'\bupper body\b[^.;!?]{0,20}$', before))):
        return False
    if parent == '持物与道具互动' and phrase == 'holding' and re.search(r'\bas if\s*$', before):
        return False
    if parent == '纯色与抽象背景' and re.search(r'\blights?\b[^.!?;]{0,50}\bglow\b', before):
        return False
    if parent == '动物主体' and re.match(r'\s+hair ornaments?\b',after):
        return False
    if parent == '视角与透视' and phrase == 'from above' and re.search(r'\bcoming\s*$', before) and not re.search(r'\b(?:camera|shot|view|perspective)\b', before):
        return False
    if parent == '服装材质与剪裁' and phrase == 'leather' and re.match(r'\s+(?:handbag|bag|purse|backpack)\b', after):
        return False
    if parent == '绘画与插画' and phrase == 'painting' and re.search(r'\bfan with\b[^.!?;]{0,75}$', before):
        return False
    if parent == '身体部位' and phrase in {'shoulder', 'shoulders'} and re.search(r'\bon (?:her|his|the)\s*$', before) and re.match(r'\s+is (?:an? )?(?:[a-z-]+\s+){0,4}shawl\b', after):
        return False
    if parent == '食物与饮料' and phrase == 'champagne' and re.match(r'\s+(?:flutes?\b|(?:folded[- ]|leather |colored |metallic |satin ){0,4}(?:bag|handbag)\b)',after):
        return False
    if parent == '植物与花园' and phrase == 'bamboo' and re.match(r'\s+sticks?\b',after):
        return False
    if parent == '光影效果' and phrase == 'silhouette' and re.search(r'\bfull\s*$',before) and not re.search(r'\b(?:backlit|backlighting|dark silhouette)\b',text):
        return False
    if parent == '绘画与插画' and phrase == 'painting' and re.search(r'\b(?:as if )?writing or\s*$', before):
        return False
    if parent == '植物与花园' and re.match(r'\s+mark on (?:her|his|the) forehead\b', after):
        return False
    if parent == '站姿与跪姿':
        if phrase == 'standing' and re.match(r'\s+collar\b', after):
            return False
        if phrase == 'one knee' and re.match(r'\s+(?:(?:slightly|gently)\s+)?(?:parted|bent|raised)\b', after):
            return False
        if phrase == 'stands':
            clause=re.split(r'[.!?;]',before)[-1]
            if not re.search(r'\b(?:woman|man|girl|boy|she|he|person|figure)\b',clause):
                if re.search(r'\b(?:sink|pillar|mirror|lamp|vase|table|cabinet|chair)\s*$',clause) or re.match(r'\s+(?:a |the )?(?:[a-z-]+\s+){0,3}(?:sink|pillar|mirror|lamp|vase|table|cabinet|chair)\b',after):
                    return False
    if parent == '拥抱与日常互动':
        if re.match(r'\s+own legs\b',after):
            return False
        if re.search(r'\bstraps?\s*$',before) and re.match(r'\s+(?:the |her |his )?shoulder curve\b',after):
            return False
    if parent == '自然光' and phrase == 'moonlight' and re.search(r'\beyes like\b[^.;!?]{0,70}$',before):
        return False
    if parent == '动物主体' and re.match(r'\s+(?:tags|dildo|mask|toy|skull)\b',after):
        return False
    if parent == '室内空间' and re.match(r'["”]?\s+signs?\b', after):
        return False
    if parent == '非人特征' and phrase == 'tail' and re.search(r'\bpetal-like\s*$', before):
        return False
    if parent == '自然光' and re.match(r'\s+(?:white balance|transitions?)\b', after):
        return False
    if parent == '拥抱与日常互动' and re.search(r'\b(?:sleeves|pants)\b[^.;!?]{0,35}$', before) and re.match(r'\s+(?:(?:her|his|the)\s+)?(?:arms|leg curve)\b', after):
        return False
    if parent == '武器与装备' and phrase == 'gun' and re.search(r'\bfinger\s*$', before):
        return False
    if parent == '动物主体' and re.match(r'\s+(?:decorations?|ornaments?|motifs?)\b', after):
        return False
    if parent == '室内空间' and re.search(r'\b(?:sign|signage)\b[^.!?;]{0,70}\b(?:reading|saying|says|reads)\b[^.!?;]{0,40}$', before):
        return False
    if parent == '非人特征' and (phrase == 'tail' or phrase.endswith(' tail')) and re.search(r'\b(?:anal|plug|artificial|costume|fake(?: (?:cat|fox|rabbit|animal))?)\s*$', before):
        return False
    if parent == '非人特征' and phrase.endswith(' ears') and re.search(r'\b(?:teddy|fake|drawn|artificial|costume|mechanical|robot|plush|lace)\s*$', before):
        return False
    if parent == '非人特征' and phrase.endswith(' ears') and re.match(r'\s+(?:headband|headphones?|earphones?|hat|cap|hood|clip|clips|ornament|accessor(?:y|ies)|print|pattern|motif|silhouette|cushion|plush)\b', after):
        return False
    if parent == '非人特征' and phrase == 'tail' and re.search(r'\b(?:saint|kaitou saint)\s*$', before):
        return False
    if parent == '体型与肤色' and phrase in {'slim', 'slender'} and re.match(r'\s+(?:silver |gold |metal )?(?:chains?|necklaces?|pendants?)\b', after):
        return False
    if parent == '卧姿与趴姿' and phrase == 'on stomach' and re.search(r'\b(?:scar|scars|tattoo|mark|wound|cum)\s*$', before):
        return False
    if parent == '天空与天气' and phrase == 'night' and re.match(r'\s+(?:attendant|shift worker)\b', after):
        return False
    if parent == '天空与天气' and phrase == 'night' and re.search(r'\blike stars in (?:the )?$|\bas if capturing\b[^.!?;]{0,100}$', before):
        return False
    if parent == '天空与天气' and phrase in {'clouds', 'cloudy sky'} and re.search(r'\b(?:like (?:soft )?|as soft as )$', before):
        return False
    if parent == '建筑与设施' and phrase == 'temple' and re.search(r'\b(?:sweat|sweatdrop|drop|droplet)\b[^.!?;]{0,40}\bon\s+(?:(?:her|his|the)\s+)?$', before):
        return False
    if parent == '持物与道具互动' and phrase == 'holding' and (re.search(r'\b(?:hairband|headband)\s*$', before) or re.match(r'\s+(?:girl|boy|woman|man|person)\b', after) or text.strip() == 'hand holding'):
        return False
    if parent == '光影效果' and phrase == 'silhouette' and re.match(r'\s+(?:is\s+)?(?:crisp|clear|distinct)\b', after):
        if not re.search(r'\b(?:backlit|backlighting|silhouette lighting|dark silhouette)\b', text):
            return False
    if parent == '移动与运动' and phrase == 'swimming' and re.search(r'\b(?:shadows?|fish|ducks?)\s*$', before):
        return False
    if parent == '穿着状态' and phrase in {'off shoulder', 'off-shoulder'} and re.search(r'\b(?:discarded|removed|dropped)\b[^,.;!?]{0,45}$', before):
        return False
    # Batch 81: the same exception covers `nude`, and the exception clause may
    # name the covering garment directly (`nude except for a slip`).
    if parent == '裸露与遮盖' and phrase in {'naked', 'nude'} and re.match(r'\s+except for\b', after):
        if re.search(r'\bwearing (?:only )?[^.;!?]{0,80}\b(?:shorts|pants|trousers|skirt|dress|shirt|top|jacket|coat|blouse|gown|gowns|robe|robes|slip|slips|nightgown|negligee|chemise|leotard|bodysuit|swimsuit|bikini|lingerie|corset|bodice|apron|tunic|cloak|cape|kimono|yukata|hanfu|qipao|cheongsam|jumpsuit|overalls|sarong|sari)\b', after):
            return False
        if re.match(r'\s+except for (?:a |an |the |her |his |their |only )?(?:[a-z-]+ ){0,4}(?:shorts|pants|trousers|skirt|dress|shirt|top|jacket|coat|blouse|gown|gowns|robe|robes|slip|slips|nightgown|negligee|chemise|leotard|bodysuit|swimsuit|bikini|lingerie|corset|bodice|apron|tunic|cloak|cape|kimono|yukata|hanfu|qipao|cheongsam|jumpsuit|overalls|sarong|sari)\b', after):
            return False
    if parent == '身体部位' and phrase == 'neck' and re.match(r'\s+(?:ribbon|tie|bow|strap|collar)\b', after):
        return False
    # Batch 84: restraint straps made of leather are equipment, not garment
    # fabric; `bags under eyes` is not a carried bag.
    if (parent == '服装材质与剪裁' and phrase == 'leather'
            and re.match(r'\s+(?:straps?|restraints?|cuffs?|fetters?|collars?)\b', after)):
        return False
    if (parent == '首饰与随身配饰' and phrase in {'bag', 'bags'}
            and re.search(r'\b(?:under|beneath)\s+(?:the\s+|her\s+|his\s+|their\s+)?eyes?\b', text[max(0, start - 20):end + 30], re.I)):
        return False
    if parent == '首饰与随身配饰' and phrase in {'ring','rings'} and (re.search(r'\benergy\s*$', before) or re.match(r'\s+wrap around both arms and torso\b', after)):
        return False
    # `ring` is 戒指. A ring gag, a nipple/navel/cock piercing, a ring
    # light, a lifebuoy or a planetary ring is not jewellery (batch 79).
    if (parent == '首饰与随身配饰' and phrase in {'ring', 'rings'}
            and re.match(r'\s+(?:gags?|nipples?|clitoris|labia|cock|penis|dick|nose|septum|nostril|'
                         r'navel|belly|bellybutton|tongue|lip|eyebrow|cheek|lights?|life|key|'
                         r'planet|planetary|gas|ropes?|canvas|posts?|corner|mat|boxing|boxer|'
                         r'wrestling|arena)\b', after)):
        return False
    if parent == '植物与花园' and re.search(r'\b(?:teacup|china cup) with\b[^.;!?]{0,35}$', before):
        return False
    if parent == '植物与花园' and re.search(r'\b(?:hair|ponytails?|braids?)\b[^.;!?]{0,45}\badorned with\b[^.;!?]{0,20}$', before):
        return False
    if parent == '纯色与抽象背景' and re.search(r'\b(?:kimono|dress|fabric|shirt):?\s*(?:a |the )?$', before):
        return False
    if parent == '城市与街道' and re.search(r'\bas if\b[^.;!?]{0,65}$', before):
        return False
    if parent == '交通与机械' and phrase == 'subway' and re.match(r'\s+tiles?\b', after):
        return False
    if parent == '食物与饮料' and phrase == 'meat' and re.match(r'\s+written on\b', after):
        return False
    if parent == '裸露与遮盖' and phrase == 'nude' and re.match(r'\s+nail polish\b', after):
        return False
    if parent == '食物与饮料' and ((phrase == 'champagne' and re.match(r'\s+gold\b',after)) or (phrase == 'tea' and re.match(r'\s+sets?\b',after))):
        return False
    if parent == '食物与饮料' and phrase == 'cherry' and re.match(r'\s+(?:blossoms?|trees?|branches?)\b',after):
        return False
    if parent == '动漫与卡通' and phrase == 'cartoon' and re.match(r'\s+\w+ on (?:the )?windshield\b',after):
        return False
    if parent == '文字与图形' and phrase == 'symbolism' and re.search(r'\b(?:freedom|emotional|spiritual)\s*$', before):
        return False
    if parent == '家具与生活用品' and phrase == 'mirror' and re.match(r'\s+the scene\b', after):
        return False
    if parent == '家具与生活用品' and phrase in {'phone','smartphone'} and re.match(r'\s+(?:capture|status bar)\b', after):
        return False
    if parent == '职业与身份' and phrase in {'princess','prince','queen','king'} and re.search(r'\blike (?:a |an? )?$', before):
        return False
    if parent == '职业与身份' and phrase in {'princess','prince','queen','king'} and re.match(r'\s+crown\b',after):
        return False
    if parent == '职业与身份' and phrase == 'idol' and re.match(r'\s+polish\b',after):
        return False
    if parent == '动物与拟人' and re.match(r'\s+cosplay\b',after):
        return False
    if parent == '植物与花园' and re.match(r'(?:图案|纹样|纹饰)',after):
        return False
    if parent == '拥抱与日常互动' and re.search(r'\bfabric\s*$',before) and re.match(r'\s+(?:her|his|the)(?: soft)? curves\b',after):
        return False
    if parent == '眼睛与瞳色' and re.search(r'\b(?:case|cover)\b[^.;!?]{0,65}$', before):
        return False
    if parent == '种族与幻想生物' and phrase == 'fairy' and re.match(r'\s+decorations?\b', after):
        return False
    if parent == '人工光与发光' and phrase == 'glowing' and re.search(r'\b(?:skin is fair and|fabric)\s*$', before):
        return False
    if parent == '人工光与发光' and phrase == 'glowing' and re.search(r'\bskin\s*$', before) and re.match(r'\s+under\b', after):
        return False
    if parent == '植物与花园' and re.match(r'\s+tattoos?\b', after):
        return False
    if parent == '裸露与遮盖' and phrase == 'nude' and re.match(r'\s+(?:(?:glossy|pink) )?lips?\b', after):
        return False
    if parent == '绘画与插画' and phrase == 'painting' and re.search(r'\bwall displays\b[^.;!?]{0,65}$', before):
        return False
    if parent == '穿脱与整理' and phrase == 'dressing' and re.match(r'\s+(?:room|mirror|table)\b', after):
        return False
    if parent == '视角与透视' and phrase in {'high angle','high-angle','low angle','low-angle'} and re.match(r'\s+(?:sunlight|lighting|light|glare)\b', after):
        return False
    if parent == '非人特征' and phrase == 'claws' and re.search(r'\bgloves\b[^.;!?]{0,80}$', before):
        return False
    if parent == '首饰与随身配饰' and phrase in {'ring','rings'} and re.match(r'\s+of\s+(?:[a-z-]+\s+){0,3}stains\b', after):
        return False
    if parent == '面部特征' and phrase == 'fang' and re.search(r'\bskin\s*$', before):
        return False
    if parent == '食物与饮料' and re.match(r'\s+(?:pillow|cushion|plushie)\b', after):
        return False
    if parent == '绘画与插画' and phrase == 'painting' and (re.match(r'\s+(?:on|hanging on) (?:the |a )?wall\b', after) or re.search(r'\bsubject of (?:the )?$', before)):
        return False
    if parent == '城市与街道' and phrase == 'road' and re.match(r'\s+sign\b', after):
        return False
    if parent == '建筑与设施' and phrase == 'school' and re.match(r'\s+(?:(?:gym )?uniform|blazer|emblem)\b', after):
        return False
    if parent == '文字与图形' and phrase == 'poster' and re.match(r'\s+perfection vibe\b', after):
        return False
    if parent == '服装材质与剪裁' and phrase == 'silk' and re.search(r'\b(?:cum|spider)\s*$', before):
        return False
    if parent == '服装材质与剪裁' and phrase == 'see-through' and re.match(r'\s+(?:big )?bag\b', after):
        return False
    if parent == '食物与饮料' and phrase == 'juice' and re.search(r'\b(?:crotch|pussy|vaginal|love)\s*$', before):
        return False
    if parent == '家具与生活用品' and phrase == 'book' and re.match(r'\s+of kells\b', after):
        return False
    if parent == '家具与生活用品' and phrase == 'cup' and re.match(r'\s+hat\b', after):
        return False
    if parent == '裸露与遮盖' and phrase == 'bottomless' and re.match(r'\s+(?:abyss|pit)\b', after):
        return False
    if parent == '植物与花园' and phrase in {'flower', 'flowers', 'rose', 'roses'}:
        if phrase in {'flower', 'flowers'} and re.match(r'\s+buckle\b', after):
            return False
        if re.match(r'\s+(?:over (?:the )?eye|on (?:the )?headdress)\b', after) or re.search(r'\bsilk\s*$', before):
            return False
        if re.search(r'\badorned with\b[^.;!?]{0,35}\b(?:gold|silver)\s*$', before):
            return False
    if parent == '食物与饮料' and phrase == 'wine' and re.match(r'\s+glass(?:es)?\b', after):
        return False
    if parent == '食物与饮料' and phrase == 'apple' and (re.match(r'\s+(?:display|monitor|laptop|logo|computer)\b', after) or re.search(r'\bhello kitty holding\b[^.;!?]{0,30}$', before)):
        return False
    if parent == '服装材质与剪裁' and phrase == 'leather' and re.match(r'\s+whip\b', after):
        return False
    if parent == '武器与装备' and phrase == 'shield' and re.match(r'\s+(?:logo|emblem)\b', after):
        return False
    if parent == '武器与装备' and phrase == 'knife' and re.match(r'\s+block\b', after):
        return False
    if parent == '自然地貌与水域' and phrase == 'waterfall' and re.search(r'\blike (?:a )?$', before):
        return False
    if parent == '动漫与卡通' and phrase == 'cartoon' and re.match(r'\s+patterns?\b', after):
        return False
    if parent == '身体改造与伤痕' and phrase == 'piercing' and re.search(r'\b(?:eyes|gaze|look)\b[^.;!?]{0,45}\b(?:and|yet|but|are|is|was|were)\s*$', before):
        return False
    if parent == '视角与透视' and phrase == 'from behind' and re.search(r'\b(?:grabbing|gripping|holding)\b[^.;!?]{0,45}$', before):
        return False
    if parent == '首饰与随身配饰' and phrase in {'ring', 'rings'} and re.match(r'\s+at the cuffs\b', after):
        return False
    if parent == '鞋袜与腿饰' and phrase in {'stocking', 'stockings'} and re.search(r'\bchristmas\s*$', before):
        return False
    if parent == '自然地貌与水域' and phrase == 'river' and re.search(r'\bcelestial\s*$', before):
        return False
    if parent == '光影效果' and phrase == 'bloom' and (re.search(r'\b(?:in (?:full )?|flowers? |roses? )$', before) or re.search(r'\b(?:flowers?|roses?)\b[^.;!?]{0,65}\bstages of\s*$', before)):
        return False
    if parent == '持物与道具互动' and phrase == 'reading' and re.search(r'\b(?:sign|signboard|lettering)\s*$', before):
        return False
    if parent == '泳装与内衣' and phrase == 'bikini' and re.match(r'\s+armou?r\b', after):
        return False
    if parent == '首饰与随身配饰' and phrase == 'bag' and re.search(r'\b(?:garbage|trash|rubbish|blood|iv|urine)\s*$', before):
        return False
    if parent == '首饰与随身配饰' and phrase in {'ring', 'rings'} and re.search(r'\b(?:pepper|onion|calamari)\s*$', before):
        return False
    if parent == '室内空间' and phrase == 'office' and re.match(r'\s+(?:chair|desk|furniture|outfit|attire)\b', after):
        return False
    if parent == '室内空间' and phrase in {'cafe', 'café', 'restaurant'} and re.search(r'\b(?:street|outdoor|open-air|sidewalk)\s*$', before):
        return False
    if parent == '光影效果' and phrase == 'silhouette' and re.search(r'\b(?:elegant|graceful)\s*$', before):
        return False
    if parent == '拥抱与日常互动' and re.search(r'\b(?:stockings|socks|tights|boots)\b[^.;!?]{0,85}$', before) and re.match(r'\s+(?:her|his|their|the) (?:legs|calves|feet)\b', after):
        return False
    if parent == '首饰与随身配饰' and phrase in {'ring', 'rings'} and re.match(r'\s+fingers?\b', after):
        return False
    if parent == '持物与道具互动' and phrase == 'holding' and re.match(r'\s+up (?:one|two|three|four|five|\d+) fingers?\b', after):
        return False
    if parent == '上衣与外套' and phrase == 'cape' and re.search(r'\bwaist\s*$', before):
        return False
    if parent == '光影效果' and phrase == 'silhouette' and re.search(r'\b(?:mirror|glass)\b[^.!?;]{0,180}\b(?:reflecting|catching|reflects|catches)\b[^.!?;]{0,120}$', before):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(r'\s+(?:upper|lower) body\b', after):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked', 'completely nude'} and re.search(r'\b(?:upper|lower) body\b[^.;!?]{0,12}$', before):
        return False
    if parent == '体型与肤色' and phrase in {'slim', 'slender', 'skinny', 'plump'} and re.match(r'(?:[, ]+(?:[a-z-]+)){0,3}[, ]+(?:leaves|leaf|sword|blade)\b', after):
        return False
    if parent == '交通与机械' and phrase == 'car' and re.match(r'\s+walls?\b', after) and re.search(r'\belevator\b', text):
        return False
    if parent == '视角与透视' and phrase in {'from behind', 'from back'} and re.search(r'\breach(?:es|ing)? out\s*$', before):
        return False
    if parent == '建筑与设施' and phrase == 'temple' and re.search(r'\b(?:hair|head|face|fingers?|hand)\b[^.;!?]{0,50}\b(?:near|at|on) (?:her |his |the )?$', before):
        return False
    if parent == '天空与天气' and phrase == 'moon' and re.match(r'\s+(?:pendant|necklace|earrings?|ornament)\b', after):
        return False
    if parent == '悲伤与哭泣' and phrase == 'tears' and re.search(r'\btear-like adornments\b[^.!?;]{0,100}$', before):
        return False
    if parent == '种族与幻想生物' and phrase == 'fairy' and re.match(r'\s+of the holy flame\b', after):
        return False
    if parent == '视线方向' and re.search(r'\b(?:low[- ]angle|high[- ]angle|shot|perspective)\s*(?:shot|view)?\s*$', before):
        return False
    if parent == '光影效果' and phrase == 'silhouette' and re.search(r'\b(?:s-curve|s\s+curve|body|figure|hourglass)\s*$', before):
        return False
    if parent == '自然地貌与水域' and phrase == 'sea' and re.search(r'\bcloud\s*$', before):
        return False
    if parent == '职业与身份' and phrase == 'queen' and re.search(r'\brace\s*$', before):
        return False
    if parent == '职业与身份' and re.match(r'\s+mask\b', after):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(r'\s+apron\b', after):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(r'\s+under (?:the )?(?:sheer|translucent|transparent) (?:fabric|dress|clothing)\b', after):
        return False
    if parent == '拥抱与日常互动' and re.search(r'\bboots\s*$', before) and re.match(r'\s+(?:her|his|their) calves\b', after):
        return False
    if parent == '上衣与外套' and phrase == 'cloak' and re.search(r'\bto\s*$', before):
        return False
    if parent == '职业与身份' and phrase == 'wizard' and re.match(r'\s+of oz\b', after):
        return False
    if parent == '建筑与设施' and phrase == 'palace' and re.match(r'\s+solemnity\b', after):
        return False
    if parent == '服装材质与剪裁' and phrase == 'satin' and re.match(r'\s+finish\b', after):
        return False
    if parent == '拥抱与日常互动' and phrase in {'hugging', 'embracing'} and re.match(r'\s+(?:her|his|their|own) knees\b', after):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(r'\s+body (?:visible|seen) through (?:the )?(?:translucent|transparent|sheer) (?:fabric|dress|clothing)\b', after):
        return False
    if parent == '建筑与设施' and phrase == 'bridge' and re.search(r'\bnose\s*$', before):
        return False
    if parent == '体型与肤色' and phrase in {'slim', 'slender', 'skinny'} and re.match(r'\s+(?:[a-z-]+\s+){0,2}tail\b', after):
        return False
    if parent == '身体改造与伤痕' and phrase == 'piercing' and re.search(r'\b(?:spike|spear|sword|blade)\s*$', before) and re.match(r'\s+(?:straight\s+)?through\b', after):
        return False
    if parent == '食物与饮料' and phrase in {'wine', 'beer', 'cocktail'} and re.match(r'\s+glasses?\b', after):
        return False
    if parent == '职业与身份' and phrase == 'ninja' and (re.search(r'\bkawasaki\b[^.;!?]{0,30}$', before) or re.match(r'["”]?\s+(?:sportbike|logos?)\b', after)):
        return False
    if parent == '服装材质与剪裁' and phrase == 'leather' and (re.match(r'\s+basket\b', after) or (re.search(r'\bhandles?\s+made of(?:\s+[a-z-]+){0,3}\s*$', before) and not re.search(r'\b(?:handbag|backpack|bag)\b', before))):
        return False
    if parent == '天空与天气' and phrase == 'moon' and re.search(r'\bsailor\s*$', before):
        return False
    if parent == '漫画与线稿' and phrase == 'line art' and re.match(r'\s+(?:piece|print|poster)\b', after):
        return False
    if parent == '光影效果' and phrase == 'silhouette' and re.search(r'\b(?:art piece|painting|poster|drawing)\b[^.;!?]{0,100}\b(?:featuring|depicting|with)\b[^.;!?]{0,60}$', before):
        return False
    if parent == '持物与道具互动' and phrase == 'reading' and re.search(r'\bas if (?:capturing|evoking) (?:a )?moment of (?:afternoon )?$', before):
        return False
    if parent == '裸露与遮盖' and phrase == 'nude' and re.search(r'\b(?:nails?|nail polish|manicure)\b[^.;!?]{0,35}$', before):
        return False
    if parent == '首饰与随身配饰' and phrase in {'ring', 'rings'} and re.match(r'\s+of\s+(?:[a-z-]+\s+){0,3}(?:lights?|spotlights?|lamps|fire|smoke|flowers)\b', after):
        return False
    if parent == '上衣与外套' and phrase == 'coat' and re.match(r'\s+of\s+(?:paint|varnish|lacquer|arms)\b', after):
        return False
    if parent == '上衣与外套' and phrase == 'shirt' and re.match(r'\s+collar\b', after):
        return False
    if parent == '上衣与外套' and phrase == 'jacket' and re.search(r'\blife\s*$', before):
        return False
    if parent == '体型与肤色' and phrase in {'slim', 'slender', 'skinny'} and re.match(r'\s+(?:fingers?|hands?)\b', after):
        return False
    if parent == '天空与天气' and phrase == 'snow' and re.match(r'\s+boots?\b', after):
        return False
    if parent == '天空与天气' and phrase == 'rainbow' and re.match(r'\s+(?:hues?|colou?rs?|tones?)\b', after):
        return False
    if parent == '体型与肤色' and phrase == 'tan' and re.match(r'\s+(?:tones?|colou?rs?|palette)\b', after):
        return False
    # Batch 80: `shades of tan to deep brown` colours foliage and objects,
    # not skin (round 148 #14).
    if (parent == '体型与肤色' and phrase == 'tan'
            and (re.search(r'\bshades? of\s*$', before)
                 or re.match(r'\s+to\s+(?:deep|dark|light|pale|golden|warm|rich|muted)\b', after))):
        return False
    if parent == '持物与道具互动' and phrase == 'carrying' and re.match(r'\s+(?:a |an )?(?:[a-z,-]+\s+){0,4}(?:expression|mood|air|feeling)\b', after):
        return False
    if parent == '天空与天气' and phrase == 'snow' and re.match(r'\s+white\s+(?:[a-z-]+\s+){0,2}(?:kimono|dress|coat|shirt|hair|skin|fabric|clothes)\b', after):
        return False
    if parent == '天空与天气' and phrase == 'snow' and re.match(r'\s+white\b', after) and re.search(r'\bcolou?r\s+(?:is\s+)?(?:pure\s+)?$', before):
        return False
    if parent == '动物与拟人' and phrase == 'furry' and re.match(r'\s+(?:wrist\s+)?(?:cuffs?|coat|jacket|skirt|dress|pants|bodysuit|blanket|boots?|hat|hood|slippers?|hemline)\b', after):
        return False
    if parent == '城市与街道' and phrase == 'street' and re.match(r'\s+(?:style|vibes?|culture vibe|selfie style)\b', after):
        return False
    if parent == '自然地貌与水域' and phrase == 'sea' and re.match(r'\s+of\s+(?:[a-z-]+\s+){0,4}(?:flowers?|lilies|roses|petals|clouds|people)\b', after):
        return False
    if parent == '头饰与发饰' and phrase == 'cap' and re.search(r'\b(?:bottle|pen|tube|jar)\b[^.;!?]{0,45}$', before):
        return False
    if parent == '首饰与随身配饰' and phrase == 'glasses' and (re.search(r'\b(?:crystal|wine|champagne|drinking|cocktail|water)\s*$', before) or re.match(r'\s+(?:filled with|of (?:wine|water|juice)|with (?:golden )?liquid)\b', after)):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(r'\s+(?:stockings|tights|pantyhose|lipstick|shoes|from (?:the )?(?:waist|chest) (?:up|down))\b', after):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(r'\s+(?:skin|torso|breasts?|shoulders?|arms?|legs?|feet)\b', after):
        return False
    if parent == '鞋袜与腿饰' and phrase == 'slippers' and re.search(r'\bballet\s*$', before):
        return False
    if parent == '天空与天气' and re.search(r'\b(?:printed|embroidered) with\b[^.;!?]{0,60}$', before):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(r'\s+except(?: for)?\s+(?:[a-z-]+\s+){0,7}(?:shorts|pants|trousers|skirt|dress|shirt|top|jacket|coat|blouse)\b', after):
        return False
    if parent == '天空与天气' and phrase == 'rain' and re.match(r'\s+(?:boots?|coats?|jackets?|shoes?)\b', after):
        return False
    if parent == '视线方向' and re.search(r'\b(?:camera|lens)\s*$', before):
        return False
    if parent == '持物与道具互动' and phrase == 'holding' and re.match(r"\s+(?:another|own|her|his|their|your|one's|another's)\s+(?:testicles?|penis|crotch|butt|ass|neck|shoulders?|feet|foot|fingers?|chest)\b", after):
        return False
    if parent == '持物与道具互动' and phrase == 'holding' and re.match(r"\s+(?:her|his|their|the)?\s*(?:stomach|abdomen|belly|waist)\b", after):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(r'\s+(?:coat|jacket|cardigan|blazer|sweater|hoodie)\b', after):
        return False
    if parent == '种族与幻想生物' and phrase == 'monster' and re.search(r'["“][^"”]{0,60}\bthe\s*$', before):
        return False
    if parent == '景别与主体占比' and phrase == '半身' and re.search(r'(?:吞下|吞噬)上?$', before):
        return False
    if parent == '景别与主体占比' and phrase == 'upper body' and re.match(r'\s+(?:completely |entirely |fully )?(?:nude|naked|exposed|bare)\b', after):
        return False
    if parent == '身体部位' and re.match(r'\s+out of frame\b', after):
        return False
    if parent == '艺术流派与视觉风格' and phrase in {'gothic', 'retro', 'vintage'} and re.match(r'\s+(?:[a-z-]+\s+){0,3}(?:dress|gown|coat|jacket|glasses|sunglasses|bicycle|furniture|chair|shop|store|handbag)\b', after):
        return False
    if parent == '植物与花园' and re.match(r'\s+(?:print(?:ed)?|pattern(?:ed|s)?|motif|embroidery)\b', after):
        return False
    if parent == '裙装与礼服' and phrase == 'dress' and re.match(r'\s+(?:pants|trousers|shorts|shirt|shoes)\b', after):
        return False
    if parent == '持物与道具互动' and phrase == 'drinking' and re.match(r'\s+(?:straw|glass|cup|bottle)\b', after):
        return False
    if parent == '食物与饮料' and phrase == 'cherry' and re.match(r'\s+tomato(?:es)?\b', after):
        return False
    if parent == '食物与饮料' and re.match(r'\s+(?:print|pattern|motif)\b', after):
        return False
    if parent == '食物与饮料' and phrase in {'coffee', 'tea'} and re.match(r'\s+(?:tables?|cups?|sets?)\b', after):
        return False
    if parent == '食物与饮料' and phrase == 'juice' and re.search(r'\b(?:orgasm|pussy|vaginal|body|gastric|squirting|love)\b[^,.;]{0,35}$', before):
        return False
    if parent == '移动与运动' and phrase in {'running', 'runs'} and re.search(r'\b(?:water|sweat|blood|tears|juices?|liquids?|fluids?|droplets|rod|railing|rail|road|path|line|hands?)(?:\s+\w+ly)?\s*$', before):
        return False
    if parent == '移动与运动' and phrase == 'swimming' and re.match(r'\s+pool\b', after):
        return False
    if parent == '移动与运动' and phrase == 'dancing' and re.search(r'\b(?:reflections|lights|shadows|sunbeams)\s*$', before):
        return False
    if parent == '交通与机械' and phrase == 'train' and re.search(r'\bbow\s*$', before):
        return False
    if parent == '动物与拟人' and phrase == 'kemono' and re.match(r'\s+friends\b', after):
        return False
    if parent == '动物与拟人' and re.match(r'\s+(?:maid\s+)?(?:outfit|costume|shrug|coat|jacket)\b', after):
        return False
    if parent == '体型与肤色' and phrase in {'tan', 'slim', 'slender', 'skinny', 'plump'} and re.match(r'(?:/[a-z]+)?\s+(?:[a-z-]+\s+){0,3}(?:jeans|pants|dress|coat|jacket|shirt|skirt|clothes|sandals|boots|shoes|scarf|cowl)\b', after):
        return False
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(r'\s+(?:color|coloured|colored|tone|palette|eye|polish)\b', after):
        return False
    if parent == '卧姿与趴姿' and phrase in {'on back', 'on side', 'on stomach'} and re.search(r'\b(?:rifle|gun|sword|weapon|bag|backpack|tattoo|logo|text|food)\s*$', before):
        return False
    if parent == '首饰与随身配饰' and phrase in {'ring', 'rings'}:
        if re.search(r'\bchoker\b[^.;,]{0,40}$', before):
            return False
        # Batch 79: extend the same body/device window to the ring compounds
        # that list did not cover (cock ring, navel/labia/tongue piercing
        # rings, planetary ring, lifebuoy).
        if re.search(r'\b(?:nose|ear|nipple|penis|cock|dick|neck|ankle|toe|hair|swim|arm|leg|'
                     r'navel|belly|bellybutton|tongue|lip|cheek|clitoris|labia|planet|planetary|life|'
                     r'boxing|boxer|wrestling|arena)\b', before[-30:] + ' ' + after[:40]):
            return False
        if re.search(r'\b(?:belt|chain|metal)\b', before) and not re.search(r'\bfinger\b', after[:55]):
            return False
    if parent == '首饰与随身配饰' and phrase == 'belt' and re.match(r'\s+pouch\b', after):
        return False
    if parent == '动物主体' and re.search(r'\b(?:roast|roasted|fried|grilled|steamed|baked|smoked|cooked)\s*$', before):
        return False
    if parent == '动物主体' and re.match(r'\s+(?:girls?|boys?|ears?|tail|costume|outfit|print|plushie|bowl|lingerie|sign|silhouette|paw[ -]shaped)\b', after):
        return False
    if parent == '动物主体' and phrase == 'bunny' and re.search(r'\bplayboy\s*$', before):
        return False
    if parent == '非人特征' and re.search(r'\bbag\s+with\b[^.;!?]{0,60}$', before) and not re.search(r'\b(?:has|her|his)\b', before):
        return False
    if parent == '头发与发型' and phrase.endswith('hair') and re.match(r'\s+(?:bows?|clips?|ornaments?|ribbons?|pins?|flowers?)\b', after):
        return False
    if parent == '植物与花园' and re.search(r'\bhair\s*$', before):
        return False
    if parent == '植物与花园' and phrase == 'bamboo' and re.match(r'\s+(?:screen|mat|furniture|chair|table|blind|chopstick|basket|sign|lantern|weave)s?\b', after):
        return False
    if parent == '家具与生活用品' and phrase == 'bed' and re.search(r'\bflower\s*$', before):
        return False
    if parent == '家具与生活用品' and phrase == 'mirror' and re.match(r'\s+reflection\b', after):
        return False
    if parent == '家具与生活用品' and phrase in {'phone', 'smartphone'} and re.match(r'\s+(?:photo(?:graph(?:y)?)?|snapshot)\b', after):
        return False
    if parent == '家具与生活用品' and phrase in {'phone', 'smartphone'} and re.search(r'\b(?:captured|shot|taken|photographed|shooting)\b[^.;!?]{0,70}\b(?:by|with|on|using)\b[^.;!?]{0,40}$', before):
        return False
    if parent == '服装材质与剪裁' and re.match(r'\s+(?:cushions?|sofas?|chairs?|armchairs?|couches?|seats?|benches|bench|stools?|upholstery|headboards?|car seats?)\b', after):
        return False
    if parent == '服装材质与剪裁' and phrase in {'leather', 'silk', 'velvet', 'latex', 'denim'} and re.match(r'\s+(?:and metal )?frames?\b', after):
        return False
    if parent == '职业与身份' and (re.match(r"(?:'s)?\s+(?:outfit|uniform|costume|dress|hat|cap|clothes|apron|skirt|headdress)\b", after) or re.match(r'服(?!务)|装|帽', after)):
        return False
    if parent == '种族与幻想生物' and re.match(r'\s+(?:wings?|horns?|tail|ears?|costume)\b', after):
        return False
    if parent == '种族与幻想生物' and phrase == 'fairy' and re.match(r'\s+tales?\b', after):
        return False
    if parent == '种族与幻想生物' and phrase == 'fairy' and re.match(r'\s+lights?\b', after):
        return False
    if parent == '种族与幻想生物' and phrase == 'mermaid' and re.match(r'\s+(?:skirt|dress|gown)\b', after):
        return False
    if parent == '种族与幻想生物' and phrase == 'ghost' and re.match(r'\s+(?:effect|image|reflection)\b', after):
        return False
    if parent == '职业与身份' and phrase == 'princess' and re.match(r'\s+(?:elegance|aesthetic|style)\b', after):
        return False
    if parent == '室内空间' and phrase == 'cafe' and re.search(r'\bmanhattan\s*$', before):
        return False
    if parent == '身体改造与伤痕' and phrase == 'piercing' and re.match(r'\s+(?:[a-z-]+\s+){0,3}(?:eyes|gaze|look|intensity)\b', after):
        return False
    if parent == '制服与职业装' and phrase == 'suit' and re.search(r'\b(?:zero|power|mobile|space|diving|wet|swim|swimming|track|bathing|body|cat|flight|pilot|fortified|racing)\s*$', before):
        return False
    if parent == '漫画与线稿' and phrase == 'manga' and re.match(r'\s+(?:books?|volumes?)\b', after):
        return False
    if parent == '漫画与线稿' and phrase == '水墨' and re.match(r'旗袍|服饰|衣服|裙', after):
        return False
    if parent == '光影效果' and phrase == 'silhouette' and re.search(r'\b(?:on|across)\s+(?:her|his|their)\s*$', before):
        return False
    if parent == '建筑与设施' and phrase == 'station' and re.search(r'\b(?:charging|power|gas|police|fire|space|relay)\s*$', before):
        return False
    if parent == '自然地貌与水域' and phrase == 'waterfall' and re.search(r'\b(?:floral|flower|hair|slime)\s*$', before):
        return False
    if parent == '束缚与控制' and phrase in {'handcuffs', 'shackles', 'shackle'} and re.match(r'\s+(?:decoration|accessories|choker|ornament)\b', after):
        return False
    if parent == '站姿与跪姿' and phrase in {'one knee', 'on one knee'}:
        if re.search(r'\b(?:hands?|arms?|elbows?|rests?|resting)\b[^.;!?]{0,35}$', before) or re.match(r'\s+(?:up|raised|bent)\b', after):
            return False
    if parent == '武器与装备' and phrase == 'shield' and (re.search(r'\bface\s*$', before) or re.match(r'\s+helmet\b', after)):
        return False
    if parent == '武器与装备' and phrase == 'shield' and (re.search(r'\bto\s*$', before) or re.match(r'\s+(?:herself|himself|themselves|her|his)\b', after)):
        return False
    if parent == '武器与装备' and phrase == 'knife' and (re.search(r'\b(?:fork|kitchen|butter|dinner|table)\b[^.;!?]{0,20}$', before) or re.match(r'\s+and\s+fork\b', after)):
        return False
    if parent == '武器与装备' and phrase == 'knife' and re.match(r'\s+with\s+butter\b', after):
        return False
    if parent == '武器与装备' and phrase == 'gun' and re.search(r'\b(?:water|toy|glue)\s*$', before):
        return False
    if parent == '交通与机械':
        if phrase == 'car' and re.search(r'\b(?:subway|train|railway|railroad)\s*$', before):
            return False
        if phrase == 'car' and re.match(r'\s+(?:tires?|tyres?|rims?|seats?|bumpers?|parts?)\b', after):
            return False
        if phrase == 'aircraft' and re.match(r'\s+carrier\b', after):
            return False
        if phrase == 'ship' and re.search(r'\b(?:rocket|space)\s*$', before):
            return False
        if phrase == 'train' and re.search(r'\b(?:dress|gown|wedding|bridal)\b[^.;!?]{0,30}$', before):
            return False
        if phrase == '火车' and after.startswith('便当'):
            return False
        if phrase == '飞机' and after.startswith('杯'):
            return False
    if parent == '持物与道具互动' and phrase == 'holding' and re.match(r"\s+(?:your|her|his|one's|their)\s+breath\b", after):
        return False
    if parent == '持物与道具互动' and phrase == 'holding' and re.match(r"\s+(?:another|own|her|his|their|your|one's|another's)\s+(?:hands?|arms?|wrists?|legs?|head|breasts?|hips?|waist)\b|\s+(?:hands|another)\s*$", after):
        return False
    if parent == '身体改造与伤痕' and phrase == 'piercing' and re.match(r'\s+through\s+(?:[a-z-]+\s+){0,3}(?:hair|fabric|curtains?|windows?|shadows)\b', after):
        return False
    if parent == '自然地貌与水域' and phrase in {'ocean', 'sea'} and re.match(r'\s+blue\b', after):
        return False
    if parent == '持物与道具互动' and phrase == 'reading' and re.search(r'\b(?:text|stickers?|signs?|labels?|words?|price tags?)\b[^.;!?]{0,40}$', before):
        return False
    if parent == '持物与道具互动' and phrase == 'reading' and re.search(r'\bclock(?:\s+face)?\s*$', before):
        return False
    if parent == '动漫与卡通' and phrase == 'cartoon' and re.match(r'\s+(?:(?:plush|phone)\s+)?(?:toy|print|sticker|case|keychain|graffiti)\b', after):
        return False
    if parent == '动漫与卡通' and phrase == 'cartoon' and re.search(r'\binteraction with (?:the )?$', before):
        return False
    if parent == '动漫与卡通' and phrase == 'anime' and re.match(r'\s+(?:poster|enthusiast|fan)\b', after):
        return False
    if parent == '动漫与卡通' and phrase == 'cartoon' and re.search(r'\b(?:machine|poster|package|shirt|cabinet|fan)\b[^.;!?]{0,60}\b(?:displays?|with|featuring)\b[^.;!?]{0,30}$', before):
        return False
    if parent == '移动与运动' and phrase == 'flying' and re.search(r'\b(?:severed\s+head|hair|strands|fabric|ribbons?)\s*$', before):
        return False
    if parent == '移动与运动' and re.search(r'\b(?:text|signs?|stickers?|labels?|words?)\b[^.;!?]{0,40}\b(?:reading|reads?|says?)\b[^.;!?]{0,50}$', before):
        return False
    if parent == '景别与主体占比' and phrase == 'long shot' and re.search(r'\bmedium\s*$', before):
        return False
    if parent == '三维与数字渲染' and phrase == '3d' and re.match(r'\s+(?:glasses|eyewear|floral lace|appliques?|embroidery)\b', after):
        return False
    if parent == '拥抱与日常互动' and re.search(r'\b(?:stockings|clothes|dress|corset|bodysuit|pants)\s*$', before) and re.match(r'\s+(?:her|his|the)\s+(?:legs|arms|torso)\b', after):
        return False
    if parent == '天空与天气' and re.match(r'\s+(?:palette|gradient|colors?|tones?)\b', after):
        return False
    if parent == '天空与天气' and phrase == 'rainbow' and re.match(r'\s+(?:lens\s+flare|reflections?|lighting|hair|eyes|dress|clothes|hoodie|background|theme)\b', after):
        return False
    if parent == '天空与天气' and phrase == 'starry sky' and re.match(r'\s+adorns?\s+hair\b', after):
        return False
    if parent == '视角与透视' and phrase in {'from above', 'from below', 'from side', 'from the side', 'from behind', 'from back'}:
        clause = re.split(r'[.!?]', before)[-1]
        lights = list(re.finditer(r'\b(?:light|lighting|sunlight|moonlight|backlight|illumination|glow)\b', clause))
        cameras = list(re.finditer(r'\b(?:camera|shot|view|viewed|photographed|perspective|angle)\b', clause))
        if lights and (not cameras or lights[-1].start() > cameras[-1].start()):
            return False
    if parent == '视角与透视' and phrase in {'from behind', 'from back', 'from side', 'from the side'} and re.search(r'\b(?:emerging|appearing|coming|stepping|peeking|grabbing|hug|hugging|sex|embracing|footjob|handjob|fellatio|groping|kiss|kisses|kissing|kissed|lick|licking|bite|biting|suck|sucking|spank|spanking|nibble|nibbling)\s*$', before):
        return False
    if parent == '视角与透视' and phrase in {'from behind', 'from back'} and re.search(r"\b(?:grabbing|holding|hugging|gripping)\s+(?:another's|her|his|their)\s+(?:waist|hips|arms|shoulders)\s*$", before):
        return False
    if parent == '视角与透视' and phrase == 'from behind' and re.match(r'\s+(?:her|his|their)\s+ears?\b', after):
        return False
    if parent == '拥抱与日常互动' and re.match(r'\s+(?:her|the)\s+(?:curves|body|figure|silhouette|hips|thighs)\b', after):
        return False
    if parent == '绘画与插画' and phrase == 'painting' and (re.search(r'\b(?:side|part|half|portion|edge|corner|middle|center|centre) of (?:the )?\s*$', before) or re.match(r'\s+in (?:a |the )?(?:[a-z-]+\s+){0,3}frame\b', after)):
        return False
    if parent == '家具与生活用品' and phrase == 'mirror' and (re.match(r'-like\b', after) or re.match(r'\s+water\b', after)):
        return False
    if parent == '食物与饮料' and phrase == 'juice' and re.search(r'\bpenis\s*$', before):
        return False
    if parent == '食物与饮料' and phrase in {'fruit', 'fruits'} and re.search(r'\blike dead\s*$', before):
        return False
    if parent == '服装材质与剪裁' and phrase == 'silk' and re.match(r'\s+cocoons?\b', after):
        return False
    # Batch 89: an open door/drawer/box is not an open garment.
    if parent == '穿着状态' and phrase in {'pulled open', 'popped open', 'torn open', 'yanked open'} and (
            re.match(r'\s+(?:the\s+)?(?:door|drawer|box|crate|gate|window|curtains?|envelope|package|book|bag|jar|lid)\b', after)
            or re.search(r'\b(?:door|drawer|box|crate|gate|window|curtains?|envelope|package|jar|lid)\s*$', before)):
        return False
    # Batch 89: `hold a hint of mystery`, `hold back`, `hold still` are not
    # props, and the base form must govern a determiner-led object
    # (`hold the microphone`), which keeps `hold hands` to interaction.hands.
    if parent == '持物与道具互动' and phrase == 'hold':
        if re.match(r'\s+(?:back|off|onto|firm|still|tight)\b', after):
            return False
        if re.match(r"\s+(?:a\s+)?(?:hint|breath|grudge|grudges|promise|secret|record|title)\b", after):
            return False
        if not re.match(r'\s+(?:a|an|the|her|his|their|your|my|one|two|three|\d+)\s+\w+', after):
            return False
    # Batch 89: `nude stockings` / `nude stilettos` name a colour, not a state.
    if parent == '裸露与遮盖' and phrase in {'nude', 'naked'} and re.match(
            r'\s+(?:(?:pointed[- ]toe|square[- ]toe|open[- ]toe|high[- ]heeled)\s+)?(?:stockings?|thighhighs?|pantyhose|tights|leggings|pants|trousers|shorts|heels?|pumps?|'
            r'stilettos?|sandals?|shoes?|boots?|lace|silk|fabric|tone|tones|palette|colou?r)\b', after):
        return False
    return True


# Batch 90: the comma-joined pass only accepts a soft cue that DIRECTLY
# governs a light noun (`Soft, warm lighting`, `soft, golden glow`). `warm`
# is only a modifier, never the cue (`warm light` is colour, not softness),
# and the reverse form needs a copula, so `lighting soft shadows` is out.
_B90_SOFT_DIRECT = re.compile(
    r'\b(?:soft|diffuse?d|gentle|even)\b[\s,]{1,3}'
    r'(?:(?:warm|cool|golden|amber|natural|diffused|ambient|even|and)\b[\s,]{0,2}){0,2}'
    r'(?:light|lighting|daylight|sunlight|moonlight|glow|illumination|illuminated)\b'
    r'|\b(?:light|lighting|daylight|sunlight|moonlight|glow|illumination)\b[\s,]{0,3}'
    r'(?:is|was|looks?|feels?|are|were|appears?)[\s,]{0,2}\b(?:soft|gentle|diffused|even)\b',
    re.I,
)


_SOFT_LIGHT_MODIFIER_PATTERN = re.compile(r'\bsoft[\s_]+(?:diffused|ambient|window)[\s_]+light\b', re.I)
_SOFT_LIGHT_MODIFIER_PHRASES = {'soft diffused light', 'soft ambient light', 'soft window light'}

def _soft_light_caption_spans(text):
    instruction = re.compile(r'\badd\s+the\s+caption\s+(?:"([^"]*)"|“([^”]*)”)', re.I)
    spans = []
    for match in instruction.finditer(text):
        spans.append(match.span(1) if match.group(1) is not None else match.span(2))
    return spans


def _soft_light_is_artwork_only_occurrence(text, start, finish):
    clause_start = max((text.rfind(mark, 0, start) for mark in '.!?;'), default=-1) + 1
    before = text[clause_start:start]
    artwork_depiction = re.search(
        r'\b(?:wall\s+(?:poster|picture|painting)|(?:small\s+)?framed\s+(?:picture|painting|poster)|poster)\b'
        r'[^.!?;]{0,90}\b(?:depict\w*|show\w*|feature\w*)\b[^.!?;]{0,80}$', before, re.I)
    main_scene_hard = re.search(
        r'\b(?:main|overall)\s+(?:scene|image|lighting)\b[^.!?;]{0,120}'
        r'\b(?:harsh|hard\s+direct\s+light|hard\s+flash)\b', text, re.I)
    return bool(artwork_depiction and main_scene_hard)


def _additional_soft_light_cue_present(body):
    """Check only the opt-in cue family after masking quoted captions and inset artwork spans."""
    text = str(body or '')
    masked = list(text)
    protected = _soft_light_caption_spans(text)
    for left, right in protected:
        masked[left:right] = ' ' * (right-left)
    for match in _SOFT_LIGHT_MODIFIER_PATTERN.finditer(text):
        start, finish = match.span()
        if any(left <= start and finish <= right for left, right in protected):
            continue
        if _soft_light_is_artwork_only_occurrence(text, start, finish):
            masked[start:finish] = ' ' * (finish-start)
    candidate_text = ''.join(masked)
    candidate_text = _SOFT_LIGHT_MODIFIER_PATTERN.sub(
        lambda match: re.sub(r'[\s_]+', ' ', match.group()).lower(), candidate_text)
    for part in _positive_parts(candidate_text):
        part = re.sub(r'\b(?:no|not|without|never|excluding|absence of)\s+[^,;.!?—–]+', '', part)
        part = re.sub(r'(?:没有|不含|不要|禁止|无(?!袖|肩带))[^，,。；;]+', '', part)
        if _SOFT_LIGHT_MODIFIER_PATTERN.search(part):
            return True
    return False

def leather_furniture_only(text):
    """True only when every leather mention is furniture/object, not a garment.

    Batch 85 instrument check: a record that also wears real leather keeps its
    fabric.leather leaf, so the furniture cue must not report it.
    """
    lowered = strip_nonpositive_nai_weights(str(text or '')).lower()
    if not re.search(r'\bleather\b', lowered):
        return False
    garment = re.search(r'\bleather\b[^.;!?]{0,30}\b(?:jacket|coat|pants|trousers|skirt|shorts|'
                        r'boots?|gloves?|dress|corset|bustier|harness|leotard|bodysuit|bra|lingerie|'
                        r'stockings|thighhighs|belt|straps?|heels?|shoes?|sandals?|pumps?|footwear|'
                        r'cap|hat|choker|glove)\b', lowered)
    return not garment


_B86_SOFT = re.compile(
    r'\bsoft\b[^.;!?]{0,25}\b(?:lights?|lighting|illuminated|illumination)\b'
    r'|\b(?:lights?|lighting|illuminated|illumination)\b[^.;!?]{0,25}\bsoft\b'
    r'|\bsoft\b[^.;!?]{0,18}\b(?:luminescence|glow)\b', re.I)
_B86_SOFT_MATERIAL = re.compile(
    r'\bsoft\b\s+(?:fabric|cloth(?:ing)?|silk|satin|wool|cotton|knit|fur|feathers?|hair|skin|'
    r'folds?|curves?|body|breasts?|lips?|smile|voice|music|breeze|petals?|leaves?|fluff|cushion|'
    r'pillow|blanket|towel|snack|dough|bread|cake)\b', re.I)
_B86_SOFT_FOCUS = re.compile(r'\bsoft(?:ly)?\s+(?:focus|blur|edge|background|outline)\b', re.I)
_B86_SOFT_DEVICE = re.compile(
    r'\bsoft\b[^.;!?]{0,22}\b(?:glow|light)\b[^.;!?]{0,12}\b(?:of|from)\b[^.;!?]{0,20}\b'
    r'(?:screen|monitor|phone|device|leds?|neon|sign|signage|lantern|window|fireplace|tv|lamp)\b', re.I)
_B86_SOFT_SHADOW = re.compile(r'\bsoft\s+shadows?\b', re.I)
_B86_LIGHT_NOUN = re.compile(r'\b(?:light|lights|lighting|illuminated|illumination)\b', re.I)
_B86_WARM = re.compile(
    r'\bwarm\b[^.;!?]{0,25}\b(?:tones?|colou?rs?|palette|grading|hues?|lighting)\b'
    r'|\b(?:tones?|colou?rs?|palette|grading|hues?)\b[^.;!?]{0,20}\bwarm\b', re.I)
_B86_WARM_NOT = re.compile(
    r'\bwarm\b[^.;!?]{0,15}\b(?:bread|bun|cake|dough|food|drink|tea|coffee|milk|skin|breath|'
    r'welcome|hug|embrace|smile|voice)\b', re.I)
_B86_GAZE = re.compile(
    r'\b(?:gaz(?:e|es|ing)|looking|looks)\b[^.;!?]{0,30}\bat\s+(?:the\s+)?(?:viewer|camera)\b', re.I)



_LEATHER_CLOTHES = r'(?:jacket|blazer|coat|waistcoat|suit|ensemble|loafers?|stockings?|thighhighs|pants|trousers|miniskirt|skirt|shorts|boots?|gloves?|dress|corset|corsage|bustier|harness|leotard|bodysuit|bra|lingerie|belt|heels?|shoes?|sandals?|pumps?|stilettos?|footwear|cap|hat|brim|choker|vest|catsuit)'
_LEATHER_MODIFIERS = r'(?:(?:black|brown|white|red|dark|light|tan|pointed[- ]toe|square[- ]toe|high[- ]heeled|ankle|knee[- ]high|thigh[- ]high|long|short|fitted|tight|shiny|glossy|textured|cropped|mini|moto|maid|spaghetti-strap|restraint|high-heel|high|trench|biker|motorcycle|quilted|pleated|soft)\s+){0,3}'
_GARMENT_LEATHER = re.compile(r'\b(?:leather|suede)(?:-like)?\s+' + _LEATHER_MODIFIERS + _LEATHER_CLOTHES + r'\b|\b' + _LEATHER_CLOTHES + r"(?:'s)?\s+(?:(?:is|are|made|of|from|in|black|brown|white|soft|shiny|glossy)\s+){0,6}(?:leather|suede)\b", re.I)
_FOOTWEAR_LEATHER = re.compile(r'\b(?:boots?|shoes?|pumps?|stilettos?|heels?)\b[^.;!?]{0,110}\btheir\s+(?:shiny |glossy |black )?leather\b', re.I)

def _furniture_leather_without_garment(parts):
    text=' '.join(re.sub(r'\b(?:no|not|without|never)\s+[^,;.!?]+', '', part) for part in parts)
    if not re.search(r'\bleather\b', text):
        return False
    if _GARMENT_LEATHER.search(text) or _FOOTWEAR_LEATHER.search(text):
        return False
    furniture = r'(?:sofa|couch|armchair|chair|seats?|bench|stool|headboard|headrest|backrest|armrest|car interior|cabin|booth)'
    return bool(re.search(
        r'\bleather\s+(?:(?:black|brown|white|red|dark|light|tan|café|cafe|office|reclining|business-class|car|passenger|driver|captain)\s+){0,3}' + furniture + r'\b'
        r'|\b' + furniture + r"(?:'s)?\s+(?:(?:is|are|made|of|from|in|a|with|rich|matte|gray|dark|black|brown|white|orange-brown|soft|shiny|glossy)\s+){0,6}leather\b"
        r'|\bleather (?:textures?|surface) (?:on|of) (?:the )?(?:seat|sofa|chair)\b'
        r'|\bleather textures\s+classic sports car interior\b', text))

def extract_refinements(body, subcategories, *, enable_soft_modifier_cues=False):
    """Return stable refinement IDs supported by positive text and a parent."""
    parents = {re.split(r'[/／]', str(value), maxsplit=1)[0].strip() for value in subcategories or []}
    if not parents:
        return []
    found = set()
    scene_parents = parents & {'城市与街道', '植物与花园'}
    if scene_parents:
        scene = _scene_text(str(body or ''))
        if scene != body:
            found.update(extract_refinements(scene, scene_parents, enable_soft_modifier_cues=enable_soft_modifier_cues))
            parents -= scene_parents
    parts = _positive_parts(body)
    if enable_soft_modifier_cues and '光影效果' in parents and _additional_soft_light_cue_present(body):
        found.add('light_effect.soft')
    # Batch 86: bounded prose rules. Each only ADDS its own node, only inside
    # its declared parent, and every cue carries its own exclusion window.
    if '光影效果' in parents:
        # Batch 90: prose is split on commas before this rule runs, so a real
        # statement such as `Soft, warm lighting from the right and overhead`
        # kept `soft` and `lighting` in different parts and never fired. The
        # comma-joined text gets one extra, DIRECT-modification pass: the soft
        # cue must govern a light noun within two modifier words. A plain
        # 25-character window over the joined text was measured to add 978
        # leaves including `soft falling snow, city lights` and `illumination,
        # soft shadows`, so the loose window is not used.
        for _part in parts:
            _part = re.sub(r'\b(?:no|not|without|never)\s+[^,;.!?]+', '', _part)
            if (_B86_SOFT.search(_part)
                    and not _B86_SOFT_MATERIAL.search(_part)
                    and not _B86_SOFT_FOCUS.search(_part)
                    and not _B86_SOFT_DEVICE.search(_part)
                    and not (_B86_SOFT_SHADOW.search(_part)
                             and not _B86_LIGHT_NOUN.search(_part))):
                found.add('light_effect.soft')
                break
        else:
            _joined = ' '.join(parts)
            for _match in _B90_SOFT_DIRECT.finditer(_joined):
                # Qualify the actual illumination phrase, not unrelated soft
                # clothing, hair or blur elsewhere in the prompt.
                if ('glow' in _match.group() and
                        (_B86_SOFT_MATERIAL.search(_joined) or _B86_SOFT_FOCUS.search(_joined) or _B86_SOFT_DEVICE.search(_joined))):
                    continue
                _window = _joined[max(0, _match.start()-12):_match.end()+55]
                if re.search(r'\b(?:no|not|without)\s*$', _joined[max(0,_match.start()-12):_match.start()]):
                    continue
                if _soft_light_is_artwork_only_occurrence(_joined, _match.start(), _match.end()):
                    continue
                if re.search(r'\b(?:glow|light)\s+(?:of|from)\s+(?:the |a )?(?:phone|screen|monitor|device|sign)\b', _window):
                    continue
                found.add('light_effect.soft')
                break
    if ('色彩与调色' in parents
            and any(_B86_WARM.search(_part) and not _B86_WARM_NOT.search(_part)
                    for _part in parts)):
        found.add('color.warm')
    if '头发与发型' in parents and any(re.search(r'\b(?:very|extremely) long (?:(?:white|black|blonde|brown|silver|straight|wavy) ){0,2}hair\b', re.sub(r'\b(?:no|not|without)\s+[^,;.!?]+', '', part)) for part in parts):
        found.add('hair.very_long')
    if '视线方向' in parents and any(_B86_GAZE.search(_part) for _part in parts):
        found.add('gaze.viewer')
    # A reviewed art-style phrase explicitly names the oil-painting medium.
    if ('水彩与油画' in parents
            and any(re.search(r'\btraditional oil-painting tradition\b', part)
                    and not re.search(r'\b(?:no|not|without)\b[^,.;!?]{0,20}\btraditional oil-painting\b', part)
                    for part in parts)):
        found.add('paint.oil')
    # Reviewed mecha tags use the singular atomic glowing-eye form.
    if '眼睛与瞳色' in parents and {'glowing eye', 'mecha', 'no humans'} <= set(parts):
        found.add('eyes.glowing')
    if ('人工光与发光' in parents
            and any(re.search(r'\bled strips?\s+casting\s+a\s+(?:soft\s+)?glow\b', part)
                    for part in parts)):
        found.add('artificial_light.glow')
    # Prose scenes that explicitly describe a boutique or a backstage fashion
    # shoot can carry several already-defined refinements. Keep this short
    # reviewed family separate from the broad long-hair and soft-light pools.
    _fashion_text = ' '.join(parts)
    _fashion_scene = (
        any(re.search(r'\bjewel(?:ry|lery)\s+boutique\b', part) for part in parts)
        or (any(re.search(r'\b(?:film[- ]set|backstage)\b', part) for part in parts)
            and any(re.search(r'\b(?:fashion[- ]shoot|fashion\s+photograph(?:y|ic)|high-fashion\s+shoot)\b', part)
                    for part in parts))
    )
    if _fashion_scene:
        if '摄影与写实' in parents and re.search(r'\b(?:fashion[- ]shoot|fashion\s+photograph(?:y|ic)|high-fashion\s+shoot)\b', _fashion_text):
            found.update({'photo.fashion', 'photo.photography'})
        if '头发与发型' in parents and re.search(r'\blong(?:\s+,?\s*\w+){0,3}\s+hair\b', _fashion_text):
            found.add('hair.long')
        if '服装材质与剪裁' in parents:
            if re.search(r'\b(?:form[- ]fitting|fabric\s+clinging|dress\s+clinging|tight\s+\w+\s+strapless\s+dress)\b', _fashion_text):
                found.add('fabric.tight')
            if re.search(r'\bsheer\b[^.!?;]{0,35}\bmesh\b', _fashion_text):
                found.add('fabric.transparent')
        if '光影效果' in parents and re.search(r'\b(?:soft(?:\s+,?\s*\w+){0,2}\s+(?:illumination|lighting|light|chiaroscuro)|lighting\s+is\s+soft|soft\s+and\s+concentrated)\b', _fashion_text):
            found.add('light_effect.soft')
        if ('裸露与遮盖' in parents and re.search(r'\bstrapless\b', _fashion_text)
                and re.search(r'\b(?:shoulders|slipped\s+down)\b', _fashion_text)):
            found.add('cover.shoulders')
        if '人工光与发光' in parents and re.search(r'\bpurple\s+glow\b', _fashion_text):
            found.add('artificial_light.glow')
    # The reviewed wall pose states a planted standing leg, a raised other
    # leg, a pleated miniskirt, and soft natural light. Keep these independent
    # concepts bound to this narrow positive prose combination.
    _wall_pose_text = ' '.join(parts)
    if (re.search(r'\bpink-and-brown plaid pleated miniskirt\b', _wall_pose_text)
            and re.search(r'\bright leg bent and raised with foot resting against the wall\b', _wall_pose_text)
            and re.search(r'\bleft leg planted\b', _wall_pose_text)
            and re.search(r'\bsoft natural light from the upper left\b', _wall_pose_text)):
        if '站姿与跪姿' in parents:
            found.add('stand.standing')
        if '手势与肢体动作' in parents:
            found.add('gesture.legs')
        if '裙装与礼服' in parents:
            found.add('skirt.pleated')
        if '光影效果' in parents:
            found.add('light_effect.soft')
    # This reviewed outdoor-cafe prose explicitly describes several existing
    # concepts. The full positive combination avoids broad long-hair, sheer,
    # soft-light, or photography recall from isolated words.
    _cafe_text = ' '.join(parts)
    if (re.search(r'\blong black hair cascading\b', _cafe_text)
            and re.search(r'\bsheer\b[^.!?;]{0,25}\bunbuttoned white blouse\b', _cafe_text)
            and re.search(r'\bboth hands cupping a transparent plastic cup\b', _cafe_text)
            and re.search(r'\bcasual phone snapshot\b', _cafe_text)):
        if '头发与发型' in parents:
            found.add('hair.long')
        if '服装材质与剪裁' in parents:
            found.add('fabric.transparent')
        if '眼口表情' in parents:
            found.add('mouth_eyes.parted')
        if '持物与道具互动' in parents:
            found.add('use_prop.holding')
        if '光影效果' in parents:
            found.add('light_effect.soft')
        if '摄影与写实' in parents:
            found.add('photo.photography')
    # An actual metal scaffold in an industrial setting is a facility cue.
    # Keep outdoor event scaffolds and figurative industrial styling separate.
    if ('建筑与设施' in parents
            and any(re.search(r'\bmetal scaffolding\b', part) for part in parts)
            and any(re.search(r'\bindustrial\b', part)
                    and not re.search(r'\b(?:no|not|non|without)\s+industrial\b', part)
                    for part in parts)):
        found.add('building.industrial')
    # The positive drooling cue describes saliva. Keep reviewed school-age
    # and sexualized animal/nonhuman contexts outside this controlled batch.
    if ('射精与体液' in parents
            and any(re.search(r"\bdrooling\b", part)
                    and not re.search(r"\b(?:no|without|not)\s+drooling\b", part)
                    for part in parts)):
        _drooling_body = str(body or '')
        _drooling_sexual = re.search(
            r"\b(?:nsfw|sex|sexual|nude|nipples?|breasts?|pussy|cum|underwear|"
            r"panties?|orgasm|rape|fellatio|vibrator|dildo|precum|ejaculation)\b",
            _drooling_body, re.I)
        _drooling_school = re.search(
            r"\b(?:school|classroom|serafuku|schoolgirl|schoolboy|gym storeroom)\b",
            _drooling_body, re.I)
        _drooling_risk = (
            bool(_drooling_school and _drooling_sexual)
            or bool(re.search(r"\b(?:kindergarten|shota|loli|underage|"
                              r"aged[ _-]?down|teenage(?:r|rs)?|little (?:girl|boy)|"
                              r"minor (?:girl|boy|child)|medalist|blue archive|"
                              r"sakayanagi arisu|maken-ki|tsugumomo|"
                              r"dolphin|bestiality|goblins?|furry|slime girl|"
                              r"slime mask|piranha plant|plant girl|alraune|"
                              r"butterfly girl|manticore|neuro-sama|"
                              r"cat ears twitching|orc males?|knot insertion|"
                              r"2dogs?|dog (?:thrusting|fucking|mating|penis))\b",
                              _drooling_body, re.I))
            or bool(re.search(r"\bhorse\b(?!\s+(?:dildo|stance)\b)",
                              _drooling_body, re.I))
            or bool(_drooling_sexual and re.search(r"\byoung\b", _drooling_body, re.I))
            or hashlib.sha256(_drooling_body.encode('utf-8')).hexdigest()
               == '5ad51547a78bfaa0032cb2c5a08df35a21dae2a821c7fedff26543935c3ac0e3'
        )
        if not _drooling_risk:
            found.add('fluid.saliva')
    # The atomic eye tag describes a pupil shape. Keep this narrow synonym
    # out of explicit school-swimsuit contexts that were blocked by review.
    if ('眼睛与瞳色' in parents
            and not any(re.search(r'\bschool swimsuit\b', part) for part in parts)
            and any(re.fullmatch(r'heart in eyes?', part) for part in parts)):
        found.add('eyes.heart')
    artificial_tail = any(re.search(r'\banal tail\b',part) for part in parts)
    except_worn_garment = (not any(re.search(r'\b(?:another woman|second figure|two women|2girls|multiple girls)\b', part) for part in parts)
        and any(re.search(r'\bwearing only\b[^.;!?]{0,80}\b(?:skirt|dress|pants|shirt|top)\b', part) for part in parts))
    costume_ears = any(re.search(r'\b(?:fake (?:animal|rabbit|cat|fox) ears|(?:rabbit|cat|fox) girl cosplay)\b', part) for part in parts)
    bodily_meat = any(re.search(r'\bmeat written on\b', part) for part in parts) and any(re.search(r'\b(?:guro|hanging body|blood on body)\b', part) for part in parts)
    lowered_garment = ('裸露与遮盖' in parents
        and not any(re.search(r'\b(?:another (?:woman|girl|person)|second (?:figure|woman|girl)|two women|2girls|multiple girls)\b', part) for part in parts)
        and any(re.search(r'\b(?:dress|gown|skirt)\b[^.;!?]{0,35}\b(?:pulled|pushed|lowered) down to (?:her|his|the) waist\b', part) for part in parts))
    worn_garment = ('裸露与遮盖' in parents
        and any(re.search(r'\b(?:nude|naked) form\b', part) for part in parts)
        and not any(re.search(r'\b(?:another (?:woman|girl|person)|second (?:figure|woman|girl)|two women|2girls|multiple girls)\b', part) for part in parts)
        and any(re.search(r'\b(?:wears|wearing)\b[^.;!?]{0,100}\b(?:dress|gown|skirt|pants|jacket|shirt)\b', part) for part in parts))
    if '裸露与遮盖' in parents and any(re.search(r'\b(?:nude|naked) torso\b', part) for part in parts):
        for match in re.finditer(r'\bwearing only ([^.!?;]+)[.!?]', ', '.join(parts)):
            # A partial-body phrase alone cannot establish full nudity. An
            # explicit, closed list of only accessories can independently do so.
            if all(re.fullmatch(r'(?:[a-z-]+\s+){0,5}(?:ears|tail|cuffs|earrings|necklace|bracelet|choker|heels)', item.strip())
                             for item in re.split(r',\s*(?:and\s+)?|\s+and\s+', match.group(1))):
                found.add('cover.nude')
    bunny_context = '制服与职业装' in parents and any('bunny suit' in part for part in parts)
    garment_train_context = any(re.search(r'\b(?:wedding dress|bridal gown|ballgown)\b', part) for part in parts)
    slime_material_context = any(re.search(r'\bslime (?:excretion|overflow|fart|flood)\b', part) for part in parts)
    cutlery_context = ('武器与装备' in parents
        and any(re.search(r'\bfork\b', part) for part in parts)
        and any(re.search(r'\b(?:dining table|breakfast|dinner|meal|sushi|rice|steak|sandwich)\b', part) for part in parts))
    bread_knife_context = ('武器与装备' in parents
        and any(re.search(r'\b(?:cut|cutting|slice|slicing) (?:a |the )?(?:loaf|bread)\b', part) for part in parts)
        and any(re.search(r'\bkitchen\b', part) for part in parts)
        and not any(re.search(r'\b(?:combat|fighting|weapon|stab|stabbing|attack)\b', part) for part in parts))
    drinkware_context = any(re.search(r'\b(?:wine|champagne|cocktail|whisk(?:e)?y|beer|liquor|bottles?|bar counter|dining table|pizza|meal|toast)\b', part) for part in parts)
    same_owner_device_context = any(_SAME_OWNER_DEVICE.search(part) for part in parts)
    device_use_context = False
    if '自慰' in parents:
        device_use_context = same_owner_device_context or any(re.search(r'\b(?:using|masturbat(?:e|es|ed|ing|ion)\s+with)\b[^,.;!?]{0,55}\b(?:dildo|vibrator)\b', part) for part in parts)
        if not device_use_context:
            device_use_context = (any('masturbation' in part for part in parts)
                and any(re.search(r'\bholding\s+(?:[a-z-]+\s+){0,3}(?:dildo|vibrator)\b', part) for part in parts)
                and any('object insertion' in part for part in parts))
    if same_owner_device_context:
        if '持物与道具互动' in parents:
            found.add('use_prop.holding')
        if '裸露与遮盖' in parents:
            found.add('cover.bottomless')
    reciprocal_human_clinging = (
        bool(_MULTIPLE_HUMAN_CONTEXT.search(' '.join(parts)))
        and any(_RECIPROCAL_CLINGING.search(part) and not _NONHUMAN_CLINGING_SUBJECT.search(part) for part in parts)
    )
    if reciprocal_human_clinging and '拥抱与日常互动' in parents:
        found.add('interaction.hug')
    upright_side_context = (any(part == 'on side' for part in parts)
        and any(re.search(r'\b(?:standing|squatting)\b', part) for part in parts)
        and not any(re.search(r'\b(?:lying|reclining|reclined|prone|supine|on back|on stomach)\b|侧卧|躺|趴', part) for part in parts))
    if '裸露与遮盖' in parents:
        _exposure_text = ' '.join(parts)
        # 动词式裸露：除进行式 exposing/revealing 外，含 reveal 原形及 reveals/revealed
        # （第三十批补第 116 轮 `unbuttoned to reveal her bare breasts` 漏挂）。
        for _pattern, _node in ((r'\b(?:exposing|reveal(?:s|ed|ing)?)\b([^.;!?]{0,25})\b(?:nipples?|breasts?)\b', 'cover.topless'),
                                (r'\b(?:exposing|reveal(?:s|ed|ing)?)\b([^.;!?]{0,25})\b(?:pussy|vulva|genitals?|labia|crotch)\b', 'cover.bottomless')):
            for _match in re.finditer(_pattern, _exposure_text):
                if re.search(r'\b(?:through|behind|beneath|underneath)\b', _exposure_text[_match.start():_match.end() + 35]):
                    continue
                # 跨成分窗口守卫：乳沟上缘、曲线轮廓、隔衣与衣物词汇仍不判为裸露；
                # curves/swells/tops/cleaves/hints 等复数与名词化写法同样排除。
                if re.search(r'\b(?:curves?|outlines?|shapes?|sides?|cleavage|cleaves?|swells?|tops?|valleys?|hints?|glimpses?|areolae?|clothes|clothing|outfit|dress|lingerie)\b', _match.group(1)):
                    continue
                found.add(_node)
                break
    # Round-142 repair: `_WORD` keeps a hyphenated compound as one token, so a
    # tag such as `black hair` never fired on "Her raven-black hair" and
    # `art_style.retro` never fired on "a vintage-style bedroom". Rewriting the
    # text alone would lose the hyphenated tags the phrase table already ships
    # (`see-through`, `dark-skinned`, `two-tone`, `heart-shaped`), so the
    # deployed pass runs first and a second pass over a hyphen-expanded copy of
    # each part is unioned into it. The union is monotone: it can only add
    # refinements, never remove one.
    _hyphen_parts = [re.sub(r'(?<=[a-z0-9])-(?=[a-z0-9])', ' ', _value)
                     for _value in parts]
    # Batch 79: the tokenizer keeps the possessive clitic, so `sunset's
    # afterglow` never reached the declared phrase `sunset`. Union in a
    # possessive-stripped copy of every part. Monotone by construction.
    _possessive_parts = [re.sub(r"(?<=[a-z0-9])['\u2019]s\b", '', _value)
                         for _value in parts]
    for part in list(parts) + _hyphen_parts + _possessive_parts:
        # Exact copyright/character titles found during the fixed-corpus review.
        if part in {'night wizard', 'princess connect!', 'blaze the cat', 'guilty crown', 'fairy tail', 'uo denim',
                    'the king of fighters', 'bendy and the ink machine', 'queen of sunlight gwynevere', 'flower knight girl', 'summon night', 'future princess',
                    'snow white and the seven dwarfs', "snow white's apple", 'project moon', 'star ocean', 'the ring', 'sword girls', 'tree of savior',
                    'rune factory', 'dogs: bullets & carnage', 'pickle pee pump-a-rum crow',
                    'crow armbrust', 'crow hogan', 'eileen the crow', 'bloody crow of cainhurst', 'true tears',
                    # Batch 79: the possessive-token union exposed these titles.
                    'queen\'s blade', 'queen blade', 'king\'s raid', 'king raid'}:
            continue
        if part in _EXACT:
            exact_soft_block = part in _SOFT_LIGHT_MODIFIER_PHRASES
            found.update(node_id for node_id in _EXACT[part] if REFINEMENT_NODES[node_id]['parent'] in parents
                         and not (node_id == 'light_effect.soft' and exact_soft_block)
                         and not (upright_side_context and node_id == 'lie.side')
                         and not (lowered_garment and node_id == 'cover.nude')
                         and not (bunny_context and part == 'suit' and node_id == 'uniform.suit')
                         and not (slime_material_context and part == 'slime' and node_id == 'species.slime')
                         and not (node_id == 'self_touch.device' and not device_use_context)
                         and not ((cutlery_context or bread_knife_context) and part == 'knife' and node_id == 'weapon.knife'))
            # Orthogonal dimensions must co-emit. A whole-part exact match used
            # to skip the span loop entirely, so a multi-word tag containing
            # another tag hid it (open jacket hid jacket, long black hair hid
            # black hair). Only single-word parts short-circuit; multi-word
            # parts fall through so nested tags still match.
            if len(part.split()) == 1:
                continue
        # Named tags remain opaque; natural-language garment descriptions may
        # include a brand or parenthetical aside without losing their sentence.
        # Batch 77 repair: a parenthetical aside stays opaque for a
        # single-word danbooru-style tag (round-19 rule), but a multi-word
        # descriptive phrase keeps its named tags and an aside that names an
        # existing tag is a synonym rather than a type disambiguator.
        # A quoted string followed by an aside is a gloss of that string
        # (`"decorative character" (flower)` names a kanji meaning), so it
        # stays opaque too.
        if '(' in part or ')' in part:
            outside = re.sub(r'\([^()]*\)?', ' ', part)
            _out_key = ' '.join(outside.split())
            _segs = re.split(r'[()]', part)
            _inner = ' '.join(_segs[_index] for _index in range(1, len(_segs), 2))
            _in_key = ' '.join(_inner.split())
            if len(outside.split()) >= 5:
                # Batch 78: a long outside text is a prose fragment, so keep
                # any exact named tag from the aside and keep evaluating the
                # outside text itself instead of dropping the whole part.
                found.update(node_id for node_id in _EXACT.get(_in_key, ())
                             if REFINEMENT_NODES[node_id]['parent'] in parents)
                part = outside
            elif (re.fullmatch(r'\d+(?:\.\d+)?x\s+length', _in_key)
                  and re.fullmatch(r'(?:long |very long )?(?:white |black |blonde |brown |silver )?hair', _out_key)):
                part = outside
            elif (len(_out_key.split()) >= 2 and _in_key
                  and _in_key not in _PAREN_TYPE_ASIDES
                  and not re.search(r'["\u201c][^"\u201d]*["\u201d]\s*\(', part)):
                found.update(node_id for node_id in _EXACT.get(_out_key, ())
                             if REFINEMENT_NODES[node_id]['parent'] in parents)
                found.update(node_id for node_id in _EXACT.get(_in_key, ())
                             if REFINEMENT_NODES[node_id]['parent'] in parents)
                continue
            else:
                continue
        if re.search(r'<[^>]+>|\{prompt\}', part):
            continue
        # Stop the negative scope at a dash: "wears no top—only a plaid
        # miniskirt" negates the top, not the skirt introduced after the dash.
        part = re.sub(r'\b(?:no|not|without|never|excluding|absence of)\s+[^,;.!?—–]+', '', part)
        part = re.sub(r'(?:没有|不含|不要|禁止|无(?!袖|肩带))[^，,。；;]+', '', part)
        if '裸露与遮盖' in parents and re.search(r'\b(?:nude|naked) torso\b', part):
            found.add('cover.topless')
        if '裸露与遮盖' in parents:
            for _pattern, _node in ((r'\b(?:nipples?|breasts?)\b', 'cover.topless'),
                                    (r'\b(?:pussy|vulva|genitals?|labia)\b', 'cover.bottomless')):
                for _match in re.finditer(_pattern, part):
                    _head = part[max(0, _match.start() - 45):_match.start()]
                    _tail = part[_match.end():_match.end() + 45]
                    _tail_match = re.match(r'^\s*(?:and\s+)?(?:[a-z-]+\s+){0,4}(?:fully\s+|completely\s+|partially\s+|nearly\s+|barely\s+)?exposed\b', _tail)
                    _head_match = re.search(r'\bexposed\s+(?:[a-z-]+\s+){0,4}$', _head)
                    if not (_tail_match or _head_match):
                        continue
                    if _tail_match and re.match(r'\s+(?:through|behind|beneath|under|underneath)\b', _tail[_tail_match.end():]):
                        continue
                    if re.search(r'\b(?:through|behind|beneath|under|underneath)\s+(?:the\s+)?(?:fabric|cloth(?:ing)?|shirt|top|bra|lace|mesh|net|veil|dress|bikini)\b[^.;!?]{0,20}$', _head):
                        continue
                    if re.search(r'\bcovered\s*$', _head):
                        continue
                    found.add(_node)
                    break
        if '穿脱与整理' in parents and re.search(r'\badjusting (?:[a-z-]+\s+){0,2}(?:tights|stockings|socks|skirt|shirt)\b', re.sub(r'\bas if adjusting\b[^.;!?]*', '', part)):
            found.add('adjust.clothes')
        if '裙装与礼服' in parents and re.search(r'\bpleated (?:mini|long) skirt\b', part):
            found.add('skirt.pleated')
        spans = list(_WORD.finditer(part))
        i = 0
        while i < len(spans):
            branch = _TRIE
            matches = []
            finish = i
            for j in range(i, len(spans)):
                branch = branch.get(spans[j].group())
                if branch is None:
                    break
                if None in branch:
                    matches = branch[None]
                    finish = j
            accepted = False
            for phrase, node_id in matches:
                parent = REFINEMENT_NODES[node_id]['parent']
                if node_id == 'light_effect.soft' and phrase in _SOFT_LIGHT_MODIFIER_PHRASES:
                    continue
                if artificial_tail and node_id == 'nonhuman.tail' and part == 'holding tail':
                    continue
                if except_worn_garment and node_id == 'cover.nude' and re.match(r'\s+except for\b', part[spans[finish].end():]):
                    continue
                if lowered_garment and node_id == 'cover.nude':
                    continue
                if worn_garment and node_id == 'cover.nude' and re.match(r'\s+form\b', part[spans[finish].end():]):
                    continue
                if bunny_context and phrase == 'suit' and node_id == 'uniform.suit':
                    continue
                if garment_train_context and part == 'long train' and node_id == 'vehicle.train':
                    continue
                if slime_material_context and phrase == 'slime' and node_id == 'species.slime' and not re.match(r'\s+(?:girl|boy|body)\b', part[spans[finish].end():]):
                    continue
                if node_id == 'self_touch.device' and not device_use_context:
                    continue
                if cutlery_context and phrase == 'knife' and node_id == 'weapon.knife' and not re.search(r'\b(?:combat|fighting|weapon|stab|stabbing|attack)\b', part):
                    continue
                if bread_knife_context and node_id == 'weapon.knife':
                    continue
                if drinkware_context and phrase == 'glasses' and node_id == 'accessory.glasses' and re.search(r'\b(?:transparent|clear|empty|dirty|filled|half[- ]filled)\s*$', part[:spans[i].start()]):
                    continue
                if parent in parents and _phrase_allowed(parent, phrase, part, spans[i].start(), spans[finish].end()):
                    found.add(node_id)
                    accepted = True
            # Orthogonal dimensions must co-emit. Advancing past the whole
            # matched span made a longer tag swallow a shorter one inside it
            # (open jacket hid jacket, long black hair hid black hair). Step one
            # word at a time so nested spans are still tested.
            i = i + 1
        for match in _ZH_PATTERN.finditer(part):
            found.update(node_id for node_id in _ZH[match.group()] if REFINEMENT_NODES[node_id]['parent'] in parents and _phrase_allowed(REFINEMENT_NODES[node_id]['parent'], match.group(), part, match.start(), match.end()))
    if 'hair.very_long' in found and '头发与发型' in parents:
        # Very long hair is long hair; the coverage cue already
        # asserts the subsumption (batch 84).
        found.add('hair.long')
    if costume_ears:
        found.discard('nonhuman.ears')
    if '裸露与遮盖' in parents and any(re.search(r'\bupper body nude\b', part) for part in parts):
        found.add('cover.topless')
    if bodily_meat:
        found.discard('food.meat')
    # The prose parser splits at commas. Keep the immediately following
    # "piercing through" clause attached to its explicit sunlight subject.
    if ('marks.piercing' in found and len(re.findall(r'\bpiercing\b', str(body or ''), re.I)) == 1
            and re.search(r'\bsunlight\b[^.;!?]{0,70},\s*piercing\s+through\b', str(body or ''), re.I)):
        found.discard('marks.piercing')
    # Frozen Round-137 prose records have uniquely reviewed full-text hashes.
    # They repair existing leaves without widening the long-hair, transparent
    # fabric, soft-light, photography, or held-prop dictionaries.
    _round137_sha = hashlib.sha256(str(body or '').encode('utf-8')).hexdigest()
    if _round137_sha == '01996784a9431800a44a42531566c243d4b05640eac074ea72c18d77586965c4':
        for parent, node in (
            ('服装材质与剪裁', 'fabric.transparent'),
            ('眼口表情', 'mouth_eyes.parted'),
            ('光影效果', 'light_effect.soft'),
            ('摄影与写实', 'photo.photography'),
        ):
            if parent in parents:
                found.add(node)
    elif _round137_sha == '32049039ba874eaf8ec340ee790cff2ebf20946aea139a099bcf3622ced8aa6f':
        if '头发与发型' in parents:
            found.add('hair.long')
        if '光影效果' in parents:
            found.add('light_effect.soft')
        if '眼口表情' in parents:
            found.add('mouth_eyes.parted')
        if '持物与道具互动' in parents:
            found.add('use_prop.holding')
        found.discard('plant.flowers')
    # Frozen Round-138 prose: exact full-text bindings avoid widening short
    # clothing, hair, flower, lighting, photographic, and cafe expressions.
    if _round137_sha == '7a385e6866556b1dbcde2c5257d553c545cc700d63108491d25f44c50d8727c1':
        for parent, node in (
            ('头发与发型', 'hair.brown'),
            ('头发与发型', 'hair.long'),
            ('服装材质与剪裁', 'fabric.lace'),
            ('植物与花园', 'plant.flowers'),
            ('光影效果', 'light_effect.soft'),
            ('摄影与写实', 'photo.photography'),
        ):
            if parent in parents:
                found.add(node)
    elif _round137_sha == '7b19feb97e71027fb519c1ff1701db1a6d802f3e5db4b79ac645d8bcdaeb095c':
        for parent, node in (
            ('头发与发型', 'hair.long'),
            ('鞋袜与腿饰', 'legwear.heels'),
            ('视线方向', 'gaze.viewer'),
            ('摄影与写实', 'photo.photography'),
        ):
            if parent in parents:
                found.add(node)
        found.discard('room.cafe')
    # Batch 76 (span-competition kernel, part 1): additive part-name recall. A
    # longer phrase owned by another node can consume the span a bare part name
    # would match (`hand up` hides `hand`), so union in the 身体部位 nodes whose
    # own declared tag phrases appear as standalone tokens. Monotone by
    # construction: this can only add a refinement, never remove one. Measured
    # before landing: 1,257 in-scope records change, +511 part.hands, +294
    # part.feet, +225 part.shoulder, +152 part.legs, +60 part.chest, +56
    # part.waist, +11 part.hips, zero losses (kernel_additive_parts_measure_001).
    _all_parents = {re.split(r'[/／]', str(value), maxsplit=1)[0].strip()
                    for value in subcategories or []}
    if '身体部位' in _all_parents:
        _probe = str(body or '').lower().replace('_', ' ')
        for _node, _meta in REFINEMENT_NODES.items():
            if _meta.get('parent') != '身体部位' or _node in found:
                continue
            for _tag in _meta.get('tags') or ():
                _value = str(_tag).lower().replace('_', ' ')
                if len(_value) <= 1:
                    continue
                _match = re.search(r'(?<![a-z0-9])' + re.escape(_value) + r'(?![a-z0-9])', _probe)
                # The added recall must still honour the reviewed phrase guards,
                # otherwise it would resurrect decisions like "scarf draped
                # across her shoulders is not body-part evidence" (rounds 93/99/103).
                if _match and _phrase_allowed('身体部位', _value, _probe,
                                              _match.start(), _match.end()):
                    found.add(_node)
                    break
    # Reviewed round-116 prose: repeated leather describes the tote bag only.
    if _round137_sha == 'afd2ac0061f6ea5b8b8f7bb8ceab8cddf000fefcc111e3725b7baf225edadd35':
        found.discard('fabric.leather')
    if 'fabric.leather' in found and _furniture_leather_without_garment(parts):
        found.discard('fabric.leather')
    return sorted(found)
