"""Single-model residency experiment; intentionally retain memory within resident group."""
import hashlib,json,pathlib,statistics,subprocess,sys,time,urllib.request
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import psutil
from PIL import Image,ImageStat
from manage import OUT,ROOT,get,save
BASE='http://127.0.0.1:8188'
def post(route,data):
 request=urllib.request.Request(BASE+route,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(request,timeout=60) as r:return json.load(r) if r.headers.get('Content-Length')!='0' else {}
def idle():
 q=get('/queue');assert not q['queue_running'] and not q['queue_pending'],'Another queue owner'
def free():
 idle();post('/free',{'unload_models':True,'free_memory':True});time.sleep(3)
def build(job,release):
 return {
 '1':{'class_type':'UNETLoader','inputs':{'unet_name':'Anima\\animayume_v15Base.safetensors','weight_dtype':'default'}},
 '2':{'class_type':'CLIPLoader','inputs':{'clip_name':'anima_baseV10_txt.safetensors','type':'stable_diffusion','device':'default'}},
 '3':{'class_type':'VAELoader','inputs':{'vae_name':'qwen_image_vae.safetensors'}},
 '4':{'class_type':'ModelSamplingAuraFlow','inputs':{'model':['1',0],'shift':3}},
 '5':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':'one adult traveler, full body, blue hiking jacket, gray trousers, brown boots, standing on a mountain path, distant trees, soft daylight, illustration'}},
 '6':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':'blurry, low contrast'}},
 '7':{'class_type':'EmptyLatentImage','inputs':{'width':768,'height':512,'batch_size':1}},
 # IS_CHANGED on this no-op passthrough forces a real sample with the same seed.
 # All five jobs use the same passthrough; it never frees models or caches.
 '8':{'class_type':'VRAMCleanup','inputs':{'anything':['7',0],'offload_model':False,'offload_cache':False}},
 '9':{'class_type':'KSampler','inputs':{'model':['4',0],'positive':['5',0],'negative':['6',0],'latent_image':['8',0],'seed':314159265,'steps':30,'cfg':7,'sampler_name':'res_multistep','scheduler':'beta','denoise':1}},
 '10':{'class_type':'VAEDecode','inputs':{'samples':['9',0],'vae':['3',0]}},
 '11':{'class_type':'VRAMCleanup','inputs':{'anything':['10',0],'offload_model':release,'offload_cache':release}},
 '12':{'class_type':'SaveImage','inputs':{'images':['11',0],'filename_prefix':'_codex_qa/runtime_phase2/'+job}},
 }
def telemetry(stop,rows,pid):
 proc=psutil.Process(pid)
 while not stop.is_set():
  memory,utilization=subprocess.check_output(['nvidia-smi','--id=0','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True,creationflags=subprocess.CREATE_NO_WINDOW).strip().split(',')
  rows.append({'time':time.time(),'gpu_used_bytes':int(memory)*2**20,'gpu_utilization':int(utilization),'server_rss_bytes':proc.memory_info().rss});stop.wait(.5)
def run(job,release):
 idle();prompt=build(job,release);save('raw/'+job+'_api.json',prompt)
 rows=[];stop=Event();pid=json.loads((OUT/'restart.json').read_text('utf8'))['owner']['pid']
 with ThreadPoolExecutor(1) as pool:
  monitor=pool.submit(telemetry,stop,rows,pid)
  try:
   started=time.perf_counter();answer=post('/prompt',{'prompt':prompt,'client_id':'codex-runtime-residency'});prompt_id=answer['prompt_id']
   save('raw/'+job+'_submission.json',answer);print(job,'submitted',prompt_id,flush=True)
   while True:
    history=get('/history/'+prompt_id)
    if prompt_id in history:history=history[prompt_id];break
    if time.perf_counter()-started>900:raise TimeoutError(job)
    time.sleep(.5)
   elapsed=time.perf_counter()-started
  finally:stop.set();monitor.result()
 save('raw/'+job+'_history.json',history);save('raw/'+job+'_telemetry.json',rows)
 assert history['status']['status_str']=='success',history['status']
 cached=[n for typ,payload in history['status']['messages'] if typ=='execution_cached' for n in payload['nodes']]
 assert '9' not in cached,'Sampler cache would invalidate measurement'
 im=history['outputs']['12']['images'][0];path=ROOT/'ComfyUI/output'/im['subfolder']/im['filename']
 with Image.open(path) as img:
  rgb=img.convert('RGB');pixel_hash=hashlib.sha256(rgb.tobytes()).hexdigest();std=ImageStat.Stat(rgb).stddev
 assert max(std)>5,'Blank/flat output'
 result={'job':job,'release_after_each':release,'wall_seconds':round(elapsed,3),'peak_gpu_used_mib':round(max(x['gpu_used_bytes'] for x in rows)/2**20,1),'end_gpu_used_mib':round(rows[-1]['gpu_used_bytes']/2**20,1),'peak_server_rss_mib':round(max(x['server_rss_bytes'] for x in rows)/2**20,1),'cached_nodes':cached,'sampler_executed':True,'image':str(path),'pixel_sha256':pixel_hash,'image_stddev':std}
 save('raw/'+job+'_result.json',result);print(json.dumps(result),flush=True)
 return result
if __name__=='__main__':
 (OUT/'raw').mkdir(exist_ok=True)
 if sys.argv[1]=='smoke':
  free()
  try:run('release_1',True)
  finally:free()
 elif sys.argv[1]=='rest':
  assert (OUT/'raw/release_1_result.json').exists()
  try:
   free();run('release_2',True);free();run('resident_1',False);run('resident_2',False);run('resident_3',False)
  finally:free()
  results=[json.loads((OUT/'raw'/f'{job}_result.json').read_text('utf8')) for job in ['release_1','release_2','resident_1','resident_2','resident_3']]
  summary={'results':results,'identical_pixels':len({r['pixel_sha256'] for r in results})==1,'release_mean_seconds':statistics.mean(r['wall_seconds'] for r in results[:2]),'resident_warm_mean_seconds':statistics.mean(r['wall_seconds'] for r in results[3:]),'limits':'Single AnimaYume model, 768x512, same prompt/seed/30 steps; 2 released runs, 1 resident cold and 2 resident warm. Device-wide memory includes other processes. No quality or startup A/B claim.'}
  save('measurement.json',summary);print(json.dumps(summary),flush=True)
 elif sys.argv[1]=='warmcheck':
  try:
   free();time.sleep(15)
   for job in ['resident_verify_1','resident_verify_2','resident_verify_3']:run(job,False)
  finally:free();time.sleep(15)
  jobs=['release_1','release_2','resident_1','resident_2','resident_3','resident_verify_1','resident_verify_2','resident_verify_3']
  results=[json.loads((OUT/'raw'/f'{job}_result.json').read_text('utf8')) for job in jobs]
  warm=[r for r in results if not r['release_after_each'] and {'1','2','3','4'}.issubset(r['cached_nodes'])]
  summary={'results':results,'identical_pixels':len({r['pixel_sha256'] for r in results})==1,'verified_warm_jobs':[r['job'] for r in warm],'verified_warm_mean_seconds':statistics.mean(r['wall_seconds'] for r in warm),'limits':'Single-model small sample. Cold/warm classification uses actual loader cache evidence; early resident runs still reloaded. Extra settling time before confirmation block. Device-wide GPU memory. No startup or image-quality A/B claim.'}
  save('measurement.json',summary);print(json.dumps(summary),flush=True)
