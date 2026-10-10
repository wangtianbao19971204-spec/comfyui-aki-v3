"""Exercise editor HTTP operations against an independent upstream Document.

Writes a fresh private receipt and synthetic fixtures. Real SAM/depth and the
three-image style matrix have separate acceptance runners; no downloads here.
"""
import argparse
import asyncio
import importlib
import json
from pathlib import Path
import types

from aiohttp import web, FormData
from aiohttp.test_utils import TestClient, TestServer
import numpy as np
from PIL import Image

from compare_upstream import package


async def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    package('candidate', Path(__file__).resolve().parents[1])
    package('original', args.upstream / 'stocking')
    store=importlib.import_module('candidate.studio_store')
    api=importlib.import_module('candidate.studio_api')
    original=importlib.import_module('original.document')
    look=importlib.import_module('original.look')
    h,w=320,256
    y,x=np.mgrid[:h,:w]
    left=(x>25)&(x<117)&(y>20)&(y<299)
    right=np.fliplr(left).copy()
    art=np.full((h,w,3),210,np.uint8)
    art[left|right]=np.stack([80+20*np.sin(y[left|right]/31)]*3,axis=1).astype(np.uint8)
    art[:,126:130]=12
    Image.fromarray(art).save(args.out/'synthetic.png')
    params=dict(look.DEFAULTS, density=65, sparkle_depth=0, sparkle_bright=0, sparkle_even=0,
                sparkle_link=False, strength_auto=False)
    ref=original.Document.from_snapshot(art,'synthetic.png',None,
        [('左腿',original.PALETTE[0],left),('右腿',original.PALETTE[1],right)],
        [(np.array([[32,90],[72,82],[108,90]]),0)],look=params,color_exclude=False)
    ref.disparity=(.3+.4*np.sin(x/256*np.pi)+.1*y/h).astype(np.float32)
    ref.sparkle=np.where((x>60)&(x<85)&(y>70)&(y<170),255,0).astype(np.uint8)
    assets=args.out/'assets'
    project=store.snapshot(ref,assets,depth_enabled=True,dark_adapt=False)
    users=types.SimpleNamespace(get_request_user_filepath=lambda request,file:str(args.out/'user'/file))
    manager=api.StudioServer(types.SimpleNamespace(user_manager=users),assets,
                            {'sam':args.out/'no-model','depth':args.out/'no-model'})
    app=web.Application(client_max_size=store.MAX_PROJECT_BYTES)
    app.router.add_post(api.PREFIX,manager.create)
    app.router.add_get(api.PREFIX+'/{sid}/',manager.handle)
    app.router.add_route('*',api.PREFIX+'/{sid}/{tail:.*}',manager.handle)
    app.on_shutdown.append(manager.shutdown)
    rows=[]
    async with TestClient(TestServer(app)) as client:
        async def request(method,path,data=None):
            response=await client.request(method,path,json=data)
            content=await response.read()
            assert response.status==200,(method,path,response.status,content[:300])
            return json.loads(content) if 'json' in response.headers.get('Content-Type','') else content
        opened=await request('POST',api.PREFIX,{'project':project,'draft_id':'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'})
        base=opened['url'].rstrip('/')
        own=manager.sessions[opened['session']].studio
        docbase=base+'/api/doc/'+own.doc.id

        def same_document():
            a,b=ref.snapshot(),own.doc.snapshot()
            assert len(a['regions'])==len(b['regions'])
            for r,s in zip(a['regions'],b['regions']):
                assert r[:2]==s[:2];np.testing.assert_array_equal(r[2],s[2])
            assert len(a['strokes'])==len(b['strokes'])
            for r,s in zip(a['strokes'],b['strokes']):
                np.testing.assert_array_equal(r[0],s[0]);assert r[1]==s[1]
            for key in ('dividers','erased'):
                assert len(a[key])==len(b[key]),key
                for r,s in zip(a[key],b[key]):np.testing.assert_array_equal(r,s)
            assert ref.color_exclude==own.doc.color_exclude

        async def edit(name,method,path,body,reference):
            reference()
            result=await request(method,docbase+'/'+path,body)
            same_document();rows.append({'feature':name,'http':True,'upstream_equal':True})
            return result

        a,b=[r.id for r in ref.regions]
        await edit('region add','POST','regions',{'name':'细节'},lambda:ref.add_region('细节'))
        c=ref.regions[-1].id
        await edit('region rename','PATCH',f'regions/{c}',{'name':'修边'},lambda:ref.rename_region(c,'修边'))
        await edit('pixel paint claims overlap','POST',f'regions/{c}/paint',{'pts':[75,200,90,204],'radius':9},lambda:ref.paint(c,[75,200,90,204],9))
        await edit('pixel eraser','POST',f'regions/{c}/paint',{'pts':[80,200],'radius':4,'erase':True},lambda:ref.paint(c,[80,200],4,True))
        await edit('undo','POST','undo',{},ref.undo)
        await edit('redo','POST','redo',{},ref.redo)
        await edit('clear region','POST',f'regions/{c}/clear',{},lambda:ref.clear_region(c))
        await edit('delete region','DELETE',f'regions/{c}',None,lambda:ref.delete_region(c))
        await edit('undo region delete','POST','undo',{},ref.undo)
        await edit('redo region delete','POST','redo',{},ref.redo)
        await edit('mirror strokes','POST',f'regions/{a}/mirror',{'into':b},lambda:ref.mirror_strokes(a,b))
        await edit('draw direction','POST','strokes',{'pts':[35,230,75,222,110,230],'hint':a},lambda:ref.add_stroke([35,230,75,222,110,230],a))
        sid=ref.strokes[-1].id
        await edit('delete direction','DELETE',f'strokes/{sid}',None,lambda:ref.delete_stroke(sid))
        line=[27,157,70,159,116,160]
        await edit('manual divider','POST','dividers',{'pts':line},lambda:ref.add_divider(line))
        await edit('remove divider','POST','walls/remove',{'x':70,'y':159,'tol':8},lambda:ref.remove_wall_at(70,159,8))
        await edit('undo divider removal','POST','undo',{},ref.undo)
        await edit('manual cut','POST',f'regions/{a}/split',{'pts':[25,180,116,180],'snap':0},lambda:ref.split_region(a,[[25,180],[116,180]],0))
        await edit('undo cut','POST','undo',{},ref.undo)
        await edit('snap cut','POST',f'regions/{a}/split',{'pts':[25,181,116,179],'snap':6},lambda:ref.split_region(a,[[25,181],[116,179]],6))
        await edit('undo snap cut','POST','undo',{},ref.undo)
        await edit('merge','POST',f'regions/{b}/merge',{'into':a},lambda:ref.merge_region(b,a))
        await edit('automatic split','POST',f'regions/{a}/split',{},lambda:ref.split_region(a))
        await edit('undo auto split','POST','undo',{},ref.undo)
        await edit('undo merge','POST','undo',{},ref.undo)
        await edit('color exclusion on','PUT','coverage/exclude',{'on':True},lambda:ref.set_color_exclude(True))
        await edit('color exclusion off','PUT','coverage/exclude',{'on':False},lambda:ref.set_color_exclude(False))
        assert await asyncio.to_thread(ref.wait_idle,120)
        await asyncio.to_thread(own.wait_ready)
        for aa,bb in zip(ref.fields(),own.doc.fields()):np.testing.assert_array_equal(aa,bb)
        rows.append({'feature':'solved direction fields','upstream_equal':True})
        for rid in (a,b):
            for action in ('mask','courses','neighbours'):
                await request('GET',docbase+f'/regions/{rid}/{action}')
        for action in ('coverage','coverage/stats','look'):
            await request('GET',docbase+'/'+action)
        variants=[(style,dict(params,style=style)) for style in look.STYLES]
        variants += [(name,dict(params,**changes)) for name,changes in [
            ('density minimum',{'density':60}),('density maximum',{'density':160}),
            ('tilt minimum',{'tilt':0}),('tilt maximum',{'tilt':60}),
            ('automatic strength',{'strength_auto':True}),('manual zero strength',{'strength':0}),
            ('manual maximum strength',{'strength':200}),('depth sparkles',{'sparkle_depth':150}),
            ('bright sparkles',{'sparkle_bright':150}),('even sparkles',{'sparkle_even':150}),
            ('painted PSD sparkles',{'sparkle_painted':150}),
            ('linked sparkles',{'sparkle_depth':150,'sparkle_bright':50,'sparkle_link':True})]]
        scene=look.scene_from_doc(ref,disparity=lambda:ref.disparity)
        for name,p in variants:
            await request('PUT',docbase+'/look',p)
            expected=scene.render(look.clean_params(p))[0]
            actual=await asyncio.to_thread(lambda:own.render()[0])
            np.testing.assert_array_equal(expected,actual)
            rows.append({'feature':name,'upstream_equal':True,'pixels':w*h})
        await request('PUT',docbase+'/look',params)
        for kind in ('png','cutout','guides'):
            result=await request('POST',docbase+'/export',{'kind':kind,'params':params})
            data=await request('GET',result['url'])
            (args.out/result['file']).write_bytes(data)
            if kind=='guides':
                reopened=original.Document.open(data=data,filename='roundtrip.psd')
                try:
                    np.testing.assert_array_equal(reopened.art,ref.art)
                    assert len(reopened.regions)==len(ref.regions)
                    assert reopened.sparkle is not None
                finally:reopened.close()
                upload=FormData();upload.add_field('file',data,filename='roundtrip.psd')
                response=await client.post(base+'/api/open/upload',data=upload)
                assert response.status==200,await response.text()
            rows.append({'feature':'export '+kind,'http':True,'reopen':True})
        for value in (params,dict(params,style='coil')):
            saved=await request('PUT',base+'/api/look/presets',{'name':'测试预设','params':value})
        await request('DELETE',base+'/api/look/presets',{'name':'测试预设'})
        rows.append({'feature':'preset save overwrite delete','http':True})
        for lang in ('en','zh'):
            result=await request('POST',base+'/api/lang',{'lang':lang});assert result['lang']==lang
        rows.append({'feature':'language switch','http':True})
        applied=await request('POST',base+'/api/apply',{})
        await request('POST',base+'/api/apply/ack',{'ticket':applied['ticket']})
        own.doc.rename_region(own.doc.regions[0].id,'未应用草稿')
        own.save_draft()
        await request('POST',base+'/api/close',{})
        restored=await request('POST',api.PREFIX,{'project':applied['project'],'draft_id':'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','restore':True})
        assert restored['restored']
        rows.append({'feature':'apply ack and draft reopen','http':True})
    ref.close()
    result={'pass':True,'upstream':args.upstream.name,'checks':rows,'count':len(rows),
            'limits':['Synthetic controlled input. Real SAM/depth and image comparisons are separate receipts.',
                      'Desktop launcher, installer, OS dialogs and GPU device choice are host adaptations.']}
    (args.out/'ACCEPTANCE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pass':True,'checks':len(rows)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    asyncio.run(run(parser.parse_args()))
