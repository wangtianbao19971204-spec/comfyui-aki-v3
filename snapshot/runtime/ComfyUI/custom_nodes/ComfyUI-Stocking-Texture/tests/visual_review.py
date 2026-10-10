"""Private, labelled diagnostic sheets from existing real-image acceptance results.

These are software QA visualizations, not generated/retouched sample artwork.
SAM confidence is not boundary accuracy; the guide masks are conservative manual
annotations, not segmentation ground truth. All inputs stay outside the repo.
"""
import argparse
import importlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from compare_upstream import package


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    package('visual_candidate', Path(__file__).resolve().parents[1])
    package('visual_original', args.upstream / 'stocking')
    engine = importlib.import_module('visual_candidate.engine')
    document = importlib.import_module('visual_original.document')
    look = importlib.import_module('visual_original.look')
    font = ImageFont.truetype(str(args.font), 23)
    small = ImageFont.truetype(str(args.font), 19)

    def panel(canvas, im, box, title, subtitle=''):
        x, y, w, h = box
        draw = ImageDraw.Draw(canvas)
        draw.text((x+12, y+8), title, fill='#e9efff', font=font)
        draw.text((x+12, y+40), subtitle, fill='#adc0d4', font=small)
        fit = ImageOps.contain(im.convert('RGB'), (w-24, h-88))
        canvas.paste(fit, (x+(w-fit.width)//2, y+76+(h-88-fit.height)//2))

    def overlay(art, masks, point=None):
        out = art.copy()
        for i, mask in enumerate(masks):
            color = np.array(((0,220,210),(242,153,43),(196,95,245))[i%3])
            out[mask] = np.round(out[mask] * .56 + color * .44).astype(np.uint8)
            contours,_ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(out,contours,-1,tuple(map(int,color)),2)
        im = Image.fromarray(out)
        if point:
            x,y = point
            d = ImageDraw.Draw(im)
            d.ellipse((x-9,y-9,x+9,y+9),fill='#ff3050',outline='white',width=3)
        return im

    fixtures = json.loads(args.fixtures.read_text(encoding='utf-8'))
    folders = ('models-white','models-black','models-nearblack')
    names = ('白丝 · 屈腿','黑丝 · 交叉腿','近黑 · 站姿')
    for fixture, folder, label in zip(fixtures,folders,names):
        art = np.asarray(Image.open(fixture['image']).convert('RGB'))
        h,w = art.shape[:2]
        model = json.loads((args.results / folder / 'ACCEPTANCE.json').read_text())
        masks = [np.asarray(Image.open(args.results/folder/f'sam-{i}.png'))>0 for i in range(3)]
        canvas = Image.new('RGB',(1600,820),'#141d2c')
        panel(canvas,Image.fromarray(art),(0,0,400,750),label+' / 原图','红点 = 同一处 SAM 提示点')
        for i,size in enumerate(('小','中','大')):
            panel(canvas,overlay(art,[masks[i]],model['point']),((i+1)*400,0,400,750),f'SAM {size}候选',f'面积 {model["sam_areas"][i]:,} px / 置信分 {model["sam_scores"][i]:.3f}')
        ImageDraw.Draw(canvas).text((16,770),'三个候选均与原版逐像素一致。置信分不等于准确率；仍需选择候选、分开部位并修边。',fill='#e9efff',font=small)
        canvas.save(args.out/(fixture['id']+'-selection.png'))

        guides=engine.parse_guides(Path(fixture['guides']).read_text(encoding='utf-8'),w,h)
        manual=[m>0 for m in engine.region_maps(guides)[0]]
        style='coil' if fixture['id']=='white-bent' else 'lines'
        output=Image.open(args.results/'round-1'/(fixture['id']+'-'+style+'.png')).convert('RGB')
        doc=document.Document.from_snapshot(art,fixture['id']+'.png',None,
            [(r['name'],document.PALETTE[i%len(document.PALETTE)],mask)
             for i,(r,mask) in enumerate(zip(guides['regions'],manual))],
            [(np.asarray(p),i) for i,r in enumerate(guides['regions']) for p in r['strokes']],
            dividers=[np.asarray(p) for p in guides['dividers']],color_exclude=True)
        try:
            doc.disparity=np.load(args.results/folder/'depth.npy',allow_pickle=False)
            assert doc.wait_idle(120)
            expected=look.scene_from_doc(doc,disparity=lambda:doc.disparity).render(dict(look.DEFAULTS,style=style,density=65))[0][...,::-1]
            np.testing.assert_array_equal(expected,np.asarray(output))
            reference=Image.fromarray(expected)
            reference.save(args.out/(fixture['id']+'-reference.png'))
        finally:
            doc.close()
        active=np.logical_or.reduce(manual)
        y,x=np.unravel_index(cv2.distanceTransform(active.astype(np.uint8),cv2.DIST_L2,5).argmax(),active.shape)
        x0=max(0,min(w-180,int(x)-90));y0=max(0,min(h-180,int(y)-90));rect=(x0,y0,x0+180,y0+180)
        canvas=Image.new('RGB',(1320,1120),'#141d2c')
        panel(canvas,Image.fromarray(art),(0,0,440,620),label+' / 原图','与以下成品使用同一原图')
        panel(canvas,overlay(art,manual),(440,0,440,620),'人工标注 / 渲染选区','保守内圈示例，未宣称完整边缘精标')
        panel(canvas,output,(880,0,440,620),'插件实际成品','线圈' if style=='coil' else '细线')
        panel(canvas,Image.fromarray(art).crop(rect).resize((360,360),Image.Resampling.NEAREST),(0,620,440,450),'原图局部 / 200%','未锐化、未增强对比度')
        panel(canvas,reference.crop(rect).resize((360,360),Image.Resampling.NEAREST),(440,620,440,450),'原版局部 / 200%','独立原版重新渲染，与插件完全相等')
        panel(canvas,output.crop(rect).resize((360,360),Image.Resampling.NEAREST),(880,620,440,450),'插件局部 / 200%','密度 65；暗部适配关闭')
        ImageDraw.Draw(canvas).text((16,1080),'同图、同标注、同深度、同参数：三轮 × 六样式。近黑纹理很淡，是原算法的暗部限制。',fill='#e9efff',font=small)
        canvas.save(args.out/(fixture['id']+'-effect.png'))
    print(json.dumps({'sheets':len(fixtures)*2,'out':str(args.out)}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('fixtures','results','upstream','out','font'):
        p.add_argument('--'+key,type=Path,required=True)
    run(p.parse_args())
