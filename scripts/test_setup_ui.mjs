// Real Chrome rendering + user events against a local test API; no model inference or user profile.
import { createServer } from 'node:http';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve, join, extname } from 'node:path';
import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
import { CDP, sleep } from './cdp.mjs';

const root = resolve(import.meta.dirname, '..');
const evidence = join(root, '.local', `setup-ui-${Date.now()}`);
mkdirSync(evidence, { recursive: true });
const raw = JSON.parse(readFileSync(join(root, 'config/model-catalog.json'), 'utf8'));
const catalog = Array.isArray(raw) ? raw : raw.models;
const ids = ['qwen35_4b_q5','vieneu_v3_turbo','moss_audio_tokenizer_nano','whisper_small_en'];
let mode = 'normal', state = 'idle', includeAsr = false, started = 0, posts = 0;
const models = () => catalog.filter(m => ids.includes(m.id)).map(m => ({
  model_id:m.id, label_vi:m.label_vi, repo:m.repo, license:m.license, size_bytes:m.size_bytes,
  kind:m.kind, revision:m.revision, state:state==='ready'?'verified':'not_downloaded', active:state==='ready'&&m.id===ids[0],
  download:state==='downloading'&&m.id===ids[0]?{state:'running',bytes_done:12345678,bytes_total:m.size_bytes}:null,
}));
function status() {
  if(state==='downloading' && Date.now()-started>3500) state=mode==='fail'?'failed':'ready';
  return {state,busy:state==='downloading',ready:state==='ready',current_model:state==='downloading'?ids[0]:null,
    error:state==='failed'?'CONNECT_FAILED':null,include_asr:includeAsr,asr_runtime_available:true,models:models()};
}
const server=createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  let data;
  if(url.pathname==='/v1/setup' && req.method==='POST') {
    const chunks=[];for await(const chunk of req) chunks.push(chunk);
    const b=JSON.parse(Buffer.concat(chunks));assert.equal(b.consent,true);
    includeAsr=b.include_asr;const chosen=models().filter(m=>includeAsr||m.model_id!==ids[3]);
    assert.deepEqual(b.accepted_sizes,Object.fromEntries(chosen.map(m=>[m.model_id,m.size_bytes])));
    posts++;state='downloading';started=Date.now();data=status();
  } else if(url.pathname==='/v1/setup/pause'){state='paused';data=status();}
  else if(url.pathname==='/v1/setup')data=status();
  else if(url.pathname==='/v1/settings')data={version:1,value:{playback:{},tts:{},storage:{},translation:{}}};
  else if(url.pathname==='/v1/models')data={models:models(),active_translation:null,translation_state:'stopped'};
  else if(url.pathname==='/v1/env')data={ready:false,items:[]};
  if(data){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));return;}
  const f=url.pathname==='/guide'?(process.env.VIETDUB_TEST_HOME?join(process.env.VIETDUB_TEST_HOME,'HUONG-DAN.html'):join(root,'packaging/windows/HUONG-DAN.html')):join(root,'apps/extension/dist',url.pathname==='/'?'options.html':url.pathname.slice(1));
  if(!f.startsWith(root)||!existsSync(f)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',({'html':'text/html','js':'text/javascript','css':'text/css'})[extname(f).slice(1)]??'application/octet-stream');res.end(readFileSync(f));
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;
const chrome=process.env.CHROME_EXE??'C:/Program Files/Google/Chrome/Application/chrome.exe';
const proc=spawn(chrome,['--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${join(evidence,'profile')}`,'about:blank'],{stdio:'ignore',windowsHide:true});
let cdp;
try {
  const portFile=join(evidence,'profile/DevToolsActivePort');
  for(let i=0; i<60&&!existsSync(portFile);i++) await sleep(300);
  const [port,endpoint]=readFileSync(portFile,'utf8').trim().split('\n');
  cdp=await CDP.connect(`ws://127.0.0.1:${port}${endpoint}`);
  const tab=(await cdp.targets()).find(t=>t.type==='page');const sid=await cdp.attach(tab.targetId);
  cdp.on(m=>{if(m.method==='Runtime.exceptionThrown')console.error('Browser exception:',JSON.stringify(m.params.exceptionDetails));});
  await cdp.send('Runtime.enable',{},sid);
  await cdp.send('Page.enable',{},sid);
  await cdp.send('Page.addScriptToEvaluateOnNewDocument',{source:`window.chrome={tabs:{onActivated:{addListener(){},removeListener(){}},onUpdated:{addListener(){},removeListener(){}}},storage:{session:{get:async()=>({pairing:{broker_url:${JSON.stringify(base)},session_token:'test-only',expires_at:9999999999}})}},runtime:{onMessage:{addListener(){},removeListener(){}},sendMessage:async()=>undefined}};`},sid);
  const wait=async(text)=>{for(let i=0;i<80;i++){if(await cdp.evaluate(sid,`document.body.innerText.includes(${JSON.stringify(text)})`))return;await sleep(150);}throw Error('UI timeout: '+text);};
  const click=async(expression)=>{
    const p=await cdp.evaluate(sid,`(()=>{const e=${expression};if(!e)throw Error('element missing');e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
    await cdp.send('Input.dispatchMouseEvent',{type:'mousePressed',...p,button:'left',clickCount:1},sid);
    await cdp.send('Input.dispatchMouseEvent',{type:'mouseReleased',...p,button:'left',clickCount:1},sid);
  };
  const button=t=>`Array.from(document.querySelectorAll('button')).find(x=>x.textContent.trim()===${JSON.stringify(t)})`;
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false},sid);
  await cdp.send('Page.navigate',{url:base},sid);await wait('Chuẩn bị để sử dụng');
  assert.equal(await cdp.evaluate(sid,`${button('Chuẩn bị để sử dụng')}.disabled`),true);
  assert.equal(await cdp.evaluate(sid,'document.documentElement.scrollWidth<=innerWidth'),true);
  await cdp.screenshot(sid,join(evidence,'first-run-390.png'));
  await click(`Array.from(document.querySelectorAll('label')).find(x=>x.textContent.includes('Tôi đã xem')).querySelector('input')`);
  await click(button('Chuẩn bị để sử dụng'));await wait('Đang tải mô hình');
  await click(button('Tạm dừng sau phần đang kiểm tra'));await wait('Đã tạm dừng');
  await click(button('Tiếp tục chuẩn bị'));await wait('Sẵn sàng dịch và đọc');
  await cdp.screenshot(sid,join(evidence,'ready-390.png'));
  assert.equal(await cdp.evaluate(sid,'document.querySelector("details").open'),false);
  await click('document.querySelector("summary")');await wait('Kiểm tra máy');
  assert.equal(await cdp.evaluate(sid,'document.querySelector("details").open'),true);
  await click('document.querySelector("summary")');
  assert.equal(posts,2);
  mode='fail';state='idle';await cdp.send('Page.reload',{},sid);await wait('Chuẩn bị để sử dụng');
  await click(`Array.from(document.querySelectorAll('label')).find(x=>x.textContent.includes('Tôi đã xem')).querySelector('input')`);
  await click(button('Chuẩn bị để sử dụng'));await wait('Chưa chuẩn bị xong');
  await cdp.screenshot(sid,join(evidence,'download-error-390.png'));
  mode='normal';await click(button('Thử lại'));await wait('Sẵn sàng dịch và đọc');
  await cdp.send('Page.navigate',{url:base+'/guide'},sid);await wait('Mở Chrome và nạp VietDub');
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1000,height:950,deviceScaleFactor:1,mobile:false},sid);
  await cdp.screenshot(sid,join(evidence,'guide-1000.png'));
  if(process.env.VIETDUB_TEST_HOME) assert.equal(await cdp.evaluate(sid,'document.body.innerText.includes("{{EXTENSION_PATH}}")'),false);
  await cdp.evaluate(sid,'window.scrollTo(0,document.body.scrollHeight)');
  await cdp.screenshot(sid,join(evidence,'guide-bottom-1000.png'));
  writeFileSync(join(evidence,'result.json'),JSON.stringify({result:'PASS',scope:'Chrome UI with mock local API; no real AI or native pairing',checks:['consent','pause','resume','ready','network failure','retry','390px no horizontal overflow'],posts},null,2));
  console.log('SETUP_UI_COMPLETE PASS',evidence);
} catch (err) {
  if(cdp){const t=(await cdp.targets()).find(t=>t.type==='page');const s=await cdp.attach(t.targetId);await cdp.screenshot(s,join(evidence,'failed.png'));writeFileSync(join(evidence,'failed.txt'),await cdp.evaluate(s,'document.body.innerText'));}
  console.error('Failed UI evidence:',evidence);
  throw err;
} finally {
  if(cdp){await cdp.send('Browser.close').catch(()=>{});cdp.close();}proc.kill();server.close();
}
