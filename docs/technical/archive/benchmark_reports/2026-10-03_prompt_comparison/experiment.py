"""Paired prompt-expression test; one model and fixed sampling, isolated outputs."""
import copy,hashlib,json,pathlib,random,statistics,subprocess,sys,time,urllib.request
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import psutil
from PIL import Image,ImageStat,ImageDraw,ImageFont
from manage import BASE,ROOT,OUT,sha,save,get,live

SCENES=[
 {'id':'single','name':'单人全身','checks':['恰好一位成人女性','头到靴底全身入画','短棕发','黄色雨衣与深蓝长裤','棕靴','收拢的红伞','红伞握在人物自己的右手','阴天的岩石海岸小路'],
  'A':'anime illustration, exactly one adult woman, full body from head to boots, short brown hair, yellow raincoat, navy trousers, brown boots, closed red umbrella held in her right hand, standing on a rocky coastal path, overcast daylight',
  'B':'An anime illustration shows exactly one adult woman, with her full body visible from head to boots. She has short brown hair and wears a yellow raincoat, navy trousers and brown boots. She holds a closed red umbrella in her right hand. She stands on a rocky coastal path in overcast daylight.'},
 {'id':'duo','name':'两位成人属性绑定','checks':['恰好两位成人且一女一男','两人全身入画','女性在画面左侧，男性在右侧','女性长黑发','女性红外套与白围巾','男性短金发','男性蓝夹克与黄围巾','浅灰墙前并排站立'],
  'A':'anime illustration, exactly two adults, one adult woman and one adult man, both full body from head to shoes, woman on the viewer\'s left, woman with long black hair, woman wearing a red coat and white scarf, man on the viewer\'s right, man with short blond hair, man wearing a blue jacket and yellow scarf, standing side by side in front of a light gray wall',
  'B':'An anime illustration shows exactly two adults, one woman and one man, both visible from head to shoes. On the viewer\'s left, the woman has long black hair and wears a red coat with a white scarf. On the viewer\'s right, the man has short blond hair and wears a blue jacket with a yellow scarf. They stand side by side in front of a light gray wall.'},
 {'id':'spatial','name':'明确左右与前后关系','checks':['恰好三个主要几何物体','红色立方体','蓝色球体','黄色圆锥','红立方体在蓝球的画面左侧','黄圆锥在蓝球后方且可见','三个物体位于白色桌面','平视镜头与浅灰背景'],
  'A':'anime illustration, still life, exactly three geometric objects on a white table, red cube on the viewer\'s left of a blue sphere, yellow cone behind the blue sphere, yellow cone still visible, eye-level camera, plain light gray background',
  'B':'An anime still-life illustration shows exactly three geometric objects on a white table. A red cube is on the viewer\'s left of a blue sphere. A yellow cone stands behind the blue sphere and remains visible. The camera is at eye level, with a plain light gray background.'},
 {'id':'lighting','name':'复杂背景与照明','checks':['一位成人图书管理员在木柜台后','绿色开衫、米白衬衫、棕裤','两侧高书架','后方中央拱形窗','窗户蓝色入射光','柜台画面左侧橙色台灯','柜台画面右侧盆栽蕨类','蓝色窗光与橙色灯光同时表现'],
  'A':'anime illustration, library interior, exactly one adult librarian standing behind a wooden counter, librarian wearing a green cardigan, ivory shirt and brown trousers, tall bookshelves on both sides, central arched window at the back, blue light entering through the window, orange desk lamp on the viewer\'s left side of the counter, potted fern on the viewer\'s right side of the counter, blue window light and orange lamplight visible together',
  'B':'An anime illustration shows a library interior with exactly one adult librarian standing behind a wooden counter. The librarian wears a green cardigan, an ivory shirt and brown trousers. Tall bookshelves line both sides. A central arched window at the back admits blue light. An orange desk lamp stands on the viewer\'s left side of the counter, and a potted fern stands on its right side. Both the blue window light and the orange lamplight are visible.'}
]
SEEDS=[314159265,271828182,161803398]
def post(route,data):
    request=urllib.request.Request(BASE+route,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=60) as r:
        body=r.read();return json.loads(body) if body else {}
def idle():
    q=get('/queue');assert not q['queue_running'] and not q['queue_pending'],'Queue belongs to another task'
def free():
    idle();post('/free',{'unload_models':True,'free_memory':True})
    time.sleep(15)
    idle()
def build(scene,variant,seed,job):
    return {
      '1':{'class_type':'UNETLoader','inputs':{'unet_name':'Anima\\animayume_v15Base.safetensors','weight_dtype':'default'}},
      '2':{'class_type':'CLIPLoader','inputs':{'clip_name':'anima_baseV10_txt.safetensors','type':'stable_diffusion','device':'default'}},
      '3':{'class_type':'VAELoader','inputs':{'vae_name':'qwen_image_vae.safetensors'}},
      '4':{'class_type':'ModelSamplingAuraFlow','inputs':{'model':['1',0],'shift':3}},
      '5':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':scene[variant]}},
      '6':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':'blurry, low contrast'}},
      '7':{'class_type':'EmptyLatentImage','inputs':{'width':1024,'height':768,'batch_size':1}},
      '8':{'class_type':'KSampler','inputs':{'model':['4',0],'positive':['5',0],'negative':['6',0],'latent_image':['7',0],'seed':seed,'steps':30,'cfg':7,'sampler_name':'res_multistep','scheduler':'beta','denoise':1}},
      '9':{'class_type':'VAEDecode','inputs':{'samples':['8',0],'vae':['3',0]}},
      '10':{'class_type':'SaveImage','inputs':{'images':['9',0],'filename_prefix':'_codex_qa/prompt_comparison/'+job}}
    }
def prepare():
    assert not (OUT/'config.json').exists()
    jobs=[]
    for si,scene in enumerate(SCENES):
        for ji,seed in enumerate(SEEDS):
            order=['A','B'] if (si+ji)%2==0 else ['B','A']
            for variant in order:jobs.append({'id':f'{scene["id"]}_{seed}_{variant}','scene':scene['id'],'seed':seed,'variant':variant})
            a=build(scene,'A',seed,'paired');b=build(scene,'B',seed,'paired');a['5']['inputs']['text']=b['5']['inputs']['text']='COMPARE'
            assert a==b,'Only positive expression may differ'
    manifest=json.loads((ROOT/'benchmark_reports/2026-10-03_runtime_phase2/model_manifest.json').read_text('utf8'))
    for entry in manifest:
        p=pathlib.Path(entry['path']);assert sha(p)==entry['sha256'] and p.stat().st_size==entry['bytes']
    save('model_manifest.json',manifest)
    save('config.json',{'scenes':SCENES,'seeds':SEEDS,'jobs':jobs,'variants':{'A':'tag-like comma fragments with explicit ownership','B':'complete sentences with explicit subjects and relations'},'memory_policy':'Retain same model for all jobs; alternate A/B order by pair. Explicit batch-boundary release only. User-requested production defaults are independent. Times are descriptive, not causal prompt-speed evidence.','deviation_from_model_comparison_runbook':'Single-model prompt comparison rather than cross-model benchmark; do not unload after each image. Both variants share the same residency policy. Text length differs as part of the expression strategy. No score tags, LoRA, hires, sampler or negative changes.','visual_review':'Model visual review, one reviewer, 3 seeds per scene; not a blinded human study or identity LoRA evaluation.'})
    save('environment.json',{'live':live(),'system':get('/system_stats'),'gpu':subprocess.check_output(['nvidia-smi'],text=True,creationflags=subprocess.CREATE_NO_WINDOW),'comfy_commit':subprocess.check_output(['git','-C',str(ROOT/'ComfyUI'),'rev-parse','HEAD'],text=True).strip()})
    save('object_info.json',get('/object_info'))
    print('Prepared 24 jobs and verified model SHA256',flush=True)
def telemetry(stop,rows,pid):
    process=psutil.Process(pid)
    while not stop.is_set():
        v=subprocess.check_output(['nvidia-smi','--id=0','--query-gpu=memory.used,utilization.gpu,power.draw,temperature.gpu','--format=csv,noheader,nounits'],text=True,creationflags=subprocess.CREATE_NO_WINDOW).strip().split(',')
        rows.append({'time':time.time(),'gpu_used_mib':float(v[0]),'gpu_utilization':float(v[1]),'power_watts':float(v[2]),'temperature_c':float(v[3]),'rss_mib':process.memory_info().rss/2**20,'system_available_mib':psutil.virtual_memory().available/2**20})
        stop.wait(.5)
def run(job):
    if (OUT/'raw'/f'{job["id"]}_result.json').exists():return
    idle();scene=next(s for s in SCENES if s['id']==job['scene']);prompt=build(scene,job['variant'],job['seed'],job['id'])
    save('raw/'+job['id']+'_api.json',prompt)
    state=live();expected=json.loads((OUT/'baseline.json').read_text('utf8'))['live']['owners']
    assert state['owners']==expected,'Backend changed'
    rows=[];stop=Event()
    with ThreadPoolExecutor(1) as pool:
        monitor=pool.submit(telemetry,stop,rows,expected[0]['pid'])
        try:
            started=time.perf_counter();answer=post('/prompt',{'prompt':prompt,'client_id':'codex-prompt-comparison'});prompt_id=answer['prompt_id'];save('raw/'+job['id']+'_submission.json',answer)
            print('submitted',job['id'],flush=True)
            while True:
                history=get('/history/'+prompt_id)
                if prompt_id in history:history=history[prompt_id];break
                if time.perf_counter()-started>900:raise TimeoutError(job['id'])
                time.sleep(.5)
            elapsed=time.perf_counter()-started
        finally:stop.set();monitor.result()
    save('raw/'+job['id']+'_history.json',history);save('raw/'+job['id']+'_telemetry.json',rows)
    assert history['status']['status_str']=='success',history['status']
    cached=[n for typ,p in history['status']['messages'] if typ=='execution_cached' for n in p['nodes']];assert '8' not in cached
    img=history['outputs']['10']['images'][0];path=ROOT/'ComfyUI/output'/img['subfolder']/img['filename']
    with Image.open(path) as im:
        assert im.size==(1024,768);rgb=im.convert('RGB');std=ImageStat.Stat(rgb).stddev
        pixel_hash=hashlib.sha256(rgb.tobytes()).hexdigest()
    assert max(std)>5
    result={**job,'wall_seconds':round(elapsed,3),'image':str(path),'image_sha256':sha(path),'pixel_sha256':pixel_hash,'stddev':std,'cached_nodes':cached,'sampler_executed':True,'peak_gpu_mib':max(r['gpu_used_mib'] for r in rows)}
    save('raw/'+job['id']+'_result.json',result)
    completed=len(list((OUT/'raw').glob('*_result.json')))
    save('STATE.json',{'status':'experiment_running','completed':completed,'total':24,'last_job':job['id']})
    print('complete',completed,'/24',job['id'],round(elapsed,2),'s',flush=True)
def sheets():
    config=json.loads((OUT/'config.json').read_text('utf8'));(OUT/'contact_sheets').mkdir(exist_ok=True)
    results=[json.loads((OUT/'raw'/f'{j["id"]}_result.json').read_text('utf8')) for j in config['jobs']]
    save('results.json',results)
    rng=random.Random(9173);mapping=[];font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
    for scene in SCENES:
        for seed in SEEDS:
            variants=['A','B'];rng.shuffle(variants)
            sheet=Image.new('RGB',(2064,816),'#20242b');draw=ImageDraw.Draw(sheet)
            for slot,variant in enumerate(variants):
                r=next(r for r in results if r['scene']==scene['id'] and r['seed']==seed and r['variant']==variant)
                with Image.open(r['image']) as im:sheet.paste(im.convert('RGB'),(slot*1040,48))
                draw.text((slot*1040+12,12),f'{scene["id"]} | seed {seed} | {"X" if slot==0 else "Y"}',font=font,fill='white')
            name=f'{scene["id"]}_{seed}.jpg';sheet.save(OUT/'contact_sheets'/name,quality=96)
            mapping.append({'scene':scene['id'],'seed':seed,'X':variants[0],'Y':variants[1],'sheet':name})
    save('review_mapping.json',mapping)
    save('generation_summary.json',{'completed':len(results),'unique_pixels':len({r['pixel_sha256'] for r in results}),'median_seconds':{v:statistics.median(r['wall_seconds'] for r in results if r['variant']==v) for v in ['A','B']},'peak_gpu_mib':max(r['peak_gpu_mib'] for r in results),'live':live()})
    print('Saved 12 paired sheets',flush=True)
if __name__=='__main__':
    action=sys.argv[1]
    if action=='prepare':prepare()
    elif action=='smoke':
        free()
        for job in json.loads((OUT/'config.json').read_text('utf8'))['jobs'][:2]:run(job)
    elif action=='rest':
        assert (OUT/'smoke_acceptance.json').exists()
        try:
            for job in json.loads((OUT/'config.json').read_text('utf8'))['jobs'][2:]:run(job)
        finally:free()
        sheets()
