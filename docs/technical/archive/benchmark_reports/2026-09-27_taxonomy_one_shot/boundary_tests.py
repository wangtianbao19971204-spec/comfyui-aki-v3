from common import *
p,r,t=runtime(STAGE,'boundary_runtime')
fixtures=[
 ('very long white hair','hair.very_long',True),('no very long white hair','hair.very_long',False),
 ('very long sleeves, white hair','hair.very_long',False),('long white hair (1.3x length)','hair.white',True),
 ('no text|multicolored hair','hair.multicolor',True),('-1::multicolored hair::','hair.multicolor',False),
 ('tree pattern, tree girl','plant.tree',False),('tree pattern on her dress, a tree in the background','plant.tree',True),
 ('a belt accentuating her hourglass silhouette','light_effect.silhouette',False),('a silhouette against the bright sky','light_effect.silhouette',True),
 ('nude stockings, nude pointed-toe stilettos','cover.nude',False),('nude woman, pointed-toe stilettos','cover.nude',True),
 ('soft scarf, soft overhead lighting','light_effect.soft',True),('soft hair, harsh overhead lighting','light_effect.soft',False),
 ('soft focus, gentle illumination from overhead','light_effect.soft',True),('no soft light','light_effect.soft',False),
 ('soft shadows, overhead lighting','light_effect.soft',False),('soft glow from the phone screen','light_effect.soft',False),
 ('leather sofa, leather jacket','fabric.leather',True),(read(HERE/'review_cases.json')[41]['prompt'],'fabric.leather',True),
 ('leather sofa, black leather blazer','fabric.leather',True),('leather sofa, beret with a leather brim','fabric.leather',True),
 ('leather sofa, leather corsage','fabric.leather',True),('leather sofa, leather stockings','fabric.leather',True),
 ('leather sofa, a patent leather bodysuit','fabric.leather',True),('leather sofa, soft leather waistcoat','fabric.leather',True),
 ('leather sofa, leather trench coat','fabric.leather',True),('leather sofa, a dress made of leather','fabric.leather',True),
 ('a leather sofa, the grain of the leather visible','fabric.leather',False),
 ('a sofa made of brown leather, white cotton dress','fabric.leather',False),
 ('a leather armchair, a leather strap held in her hand','fabric.leather',False),
 ('leather sofa, leather suit','fabric.leather',True),('leather sofa, leather high-heel boots','fabric.leather',True),
 ('leather sofa, leather mini skirt','fabric.leather',True),('leather sofa, leather moto jacket','fabric.leather',True),
 ('soft hair and car taillights reflect a soft cool glow','light_effect.soft',False),
 ('soft clothing, a teacup glowing with a gentle glow','light_effect.soft',False),
]
results=[]
for body,target,expected in fixtures:
    found=r.extract_refinements(body,list(t.SUBCATEGORY_PARENTS),enable_soft_modifier_cues=True)
    results.append({'body':body,'target':target,'expected':expected,'actual':target in found,'passed':(target in found)==expected})
save(HERE/'boundary_tests_latest.json',{'checks':results,'passed':all(x['passed'] for x in results),'source_sha256':sha(STAGE/'semantic_refinements.py')})
print(json.dumps({'checks':len(results),'failures':[x for x in results if not x['passed']]},ensure_ascii=False))
