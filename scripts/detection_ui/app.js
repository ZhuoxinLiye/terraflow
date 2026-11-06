'use strict';
const $ = id => document.getElementById(id);
let file=null, originalUrl=null, semanticUrl=null, result=null, busy=false, categories=[], detections=[], overlay=true, promptsLoaded=false;
let confirmedCategories=[], resultCategories=[];
const cloneCategories = value => JSON.parse(JSON.stringify(value));
const hasDraftChanges = () => JSON.stringify(categories)!==JSON.stringify(confirmedCategories);
let scale=1, tx=0, ty=0, width=0, height=0, drag=null, gridState=null, activeJob=null;
const palette=[[0,0,0],[230,25,75],[60,180,75],[255,225,25],[0,130,200],[245,130,48],[145,30,180],[70,240,240],[240,50,230],[210,245,60],[250,190,190],[0,128,128],[230,190,255],[170,110,40],[255,250,200],[128,0,0],[170,255,195],[128,128,0],[255,215,180],[0,0,128]];
function color(i){if(palette[i])return `rgb(${palette[i].join(',')})`; const h=(i*0.61803398875)%1,s=.65,v=.95;const f=n=>{const k=(n+h*6)%6;return Math.round((v-v*s*Math.max(0,Math.min(k,4-k,1)))*255)};return `rgb(${f(5)},${f(3)},${f(1)})`;}
const status=(text,kind='')=>{$('status').textContent=text;$('status').className='status '+kind;};
const auth=()=>({});
async function request(url, options={}) {const r=await fetch(url,{...options,headers:{...auth(),...options.headers}});if(!r.ok){let m='服务请求失败';try{m=(await r.json()).error||m}catch(_){}if(r.status===401)m='访问令牌无效，请检查后重试。';throw new Error(m)}return r;}
const validBatch = () => /^\d+$/.test($('batch').value)&&Number.isSafeInteger(Number($('batch').value))&&Number($('batch').value)>0;
function buttons(){ if($('useGraph'))$('useGraph').disabled=busy||!result?.dataset_id; $('run').disabled=busy||!validBatch()||!file||!$('token').value.trim()||!promptsLoaded||hasDraftChanges()||!confirmedCategories.some(c=>c.role==='target'); ['file','batch','token','addCategory','addBackground'].forEach(id=>$(id).disabled=busy); $('promptPanels').querySelectorAll('input,button,select').forEach(e=>e.disabled=busy); ['downloadImage','downloadJson','downloadZip','toggleOverlay','view'].forEach(id=>$(id).disabled=busy||!result); $('confirmCategories').disabled=busy||!promptsLoaded||!hasDraftChanges(); $('revertCategories').disabled=busy||!promptsLoaded||!hasDraftChanges(); updateConfigHints(); }
function renderLegend() {
  $('legend').replaceChildren();
  const displayCategories=result?resultCategories:confirmedCategories;
  displayCategories.forEach((c,i)=>{
    if(c.role!=='target')return;
    const item=document.createElement('span'),swatch=document.createElement('i'),count=document.createElement('b');
    swatch.className='swatch';swatch.style.background=color(i+1);
    const row=result?.class_counts?.find(row=>row.class_id===i+1);
    count.textContent=result?String(row?.count??detections.filter(d=>d.class_id===i+1).length):'—';
    count.className='class-count';item.append(swatch,document.createTextNode(c.label||'未命名'),count);$('legend').append(item);
  });
  $('categoryCount').textContent=categories.filter(c=>c.role==='target').length;
  $('backgroundCount').textContent=categories.filter(c=>c.role==='context').length;
}
function updateConfigHints() {
  const dirty=hasDraftChanges();
  $('promptState').textContent=!promptsLoaded?'等待加载类别':dirty?'有未确认的修改 · 确认后用于下一次识别':'类别已确认';
  $('promptState').classList.toggle('pending',dirty);
  const differs=result && (dirty || JSON.stringify(resultCategories)!==JSON.stringify(confirmedCategories));
  $('resultConfigHint').textContent=differs?'当前显示上次识别结果；新类别在重新识别后更新。':'';
  $('resultConfigHint').hidden=!differs;
}
function invalidate(){renderLegend();buttons();}
function categoryError(value) {
  if(!value.length||value.length>32||!value.some(c=>c.role==='target'))return '请保留至少一个目标类别，类别总数不超过 32。';
  const labels=new Set(['background']);
  for(const c of value){
    if(!c.label.trim()||labels.has(c.label.trim().toLowerCase())||!c.prompts.length||c.prompts.length>40||c.prompts.some(p=>!p.trim())||[c.label,...c.prompts].some(p=>p.length>160||/[,\r\n\x00]/.test(p)))return '请填写唯一的大类名和非空小类提示词（每类 1–40 条，每项最多 160 字，不含逗号或换行）。';
    labels.add(c.label.trim().toLowerCase());
  }
  if(encodeURIComponent(JSON.stringify(value)).length>60000)return '提示词配置过大，请减少类别或提示词。';
  return '';
}
$('confirmCategories').onclick=()=>{
  if(busy||!promptsLoaded)return;
  const error=categoryError(categories);if(error)return status(error,'error');
  categories=categories.map(c=>({...c,label:c.label.trim(),prompts:c.prompts.map(p=>p.trim())}));
  confirmedCategories=cloneCategories(categories);renderPrompts();
  status(result?'类别已确认，当前结果保留；点击开始识别以生成新结果。':'类别已确认，可以开始识别。');
};
$('revertCategories').onclick=()=>{if(busy)return;categories=cloneCategories(confirmedCategories);renderPrompts();status('已撤销未确认的类别修改，当前结果保留。')};
function renderPrompts(openIndex=-1) {
  $('prompts').replaceChildren();$('backgroundPrompts').replaceChildren();
  categories.forEach((category,i)=>{
    const details=document.createElement('details');details.className='category';details.open=i===openIndex;
    const summary=document.createElement('summary'),swatch=document.createElement('i'),label=document.createElement('input'),count=document.createElement('small'),remove=document.createElement('button');
    swatch.className='swatch';swatch.style.background=color(i+1);
    label.value=category.label;label.setAttribute('aria-label',category.role==='context'?'背景大类提示词':'目标大类提示词');
    label.onclick=e=>e.stopPropagation();label.oninput=()=>{category.label=label.value;remove.setAttribute('aria-label','删除 '+label.value);invalidate()};
    count.textContent=category.prompts.length;remove.className='remove';remove.textContent='×';remove.title='删除大类';remove.setAttribute('aria-label','删除 '+category.label);
    remove.onclick=e=>{e.preventDefault();categories.splice(i,1);invalidate();renderPrompts()};
    summary.append(swatch,label,count,remove);details.append(summary);
    const children=document.createElement('div');children.className='children';
    const roleLabel=document.createElement('label'),role=document.createElement('select');roleLabel.className='role-field';roleLabel.append(document.createTextNode('类别用途'));
    for(const [value,text] of [['target','目标 · 显示并计数'],['context','背景 / 对抗 · 仅参与推理']]){const option=document.createElement('option');option.value=value;option.textContent=text;role.append(option)}
    role.value=category.role;role.setAttribute('aria-label','类别用途 '+category.label);role.onchange=()=>{category.role=role.value;invalidate();if(category.role==='context')$('backgroundSettings').open=true;renderPrompts(i)};roleLabel.append(role);children.append(roleLabel);
    category.prompts.forEach((prompt,j)=>{
      const row=document.createElement('div'),input=document.createElement('input'),del=document.createElement('button');row.className='prompt-row';input.value=prompt;input.setAttribute('aria-label','小类提示词');input.oninput=()=>{category.prompts[j]=input.value;invalidate()};
      del.className='remove';del.textContent='×';del.title='删除小类';del.setAttribute('aria-label','删除小类提示词');del.onclick=()=>{category.prompts.splice(j,1);invalidate();renderPrompts(i)};row.append(input,del);children.append(row);
    });
    const add=document.createElement('button');add.textContent='＋ 新增小类提示词';add.className='add-prompt';add.onclick=()=>{if(category.prompts.length>=40)return status('每个大类最多 40 条提示词。','error');category.prompts.push('');invalidate();renderPrompts(i)};
    children.append(add);details.append(children);$(category.role==='context'?'backgroundPrompts':'prompts').append(details);
  });
  renderLegend();buttons();
}
async function loadPrompts(){if(promptsLoaded||!$('token').value.trim())return;try{const data=await(await request('/api/workspace/detection/api/prompts')).json();categories=data.categories.map(c=>({...c,role:c.role||'target'}));confirmedCategories=cloneCategories(categories);promptsLoaded=true;renderPrompts();status(file?'影像已就绪，可以开始识别。':'提示词已加载，请导入影像。');}catch(e){status(e.message,'error')}}
$('batch').addEventListener('input',buttons);
$('token').addEventListener('change',loadPrompts);$('token').addEventListener('input',buttons);
function addCategory(role){if(categories.length>=32)return status('最多支持 32 个大类。','error');categories.push({label:'',prompts:[''],role});invalidate();if(role==='context')$('backgroundSettings').open=true;renderPrompts(categories.length-1);$(role==='context'?'backgroundPrompts':'prompts').lastElementChild.scrollIntoView({block:'nearest'})}
$('addCategory').onclick=()=>addCategory('target');$('addBackground').onclick=()=>addCategory('context');
function transform(){$('scene').style.transform=`translate(${tx}px,${ty}px) scale(${scale})`;$('zoom').textContent=Math.round(scale*100)+'%';}
function fit(){if(!width||!height)return;const v=$('viewport');scale=Math.min((v.clientWidth-50)/width,(v.clientHeight-50)/height);tx=(v.clientWidth-width*scale)/2;ty=(v.clientHeight-height*scale)/2;transform();}
function zoomAt(factor,x=$('viewport').clientWidth/2,y=$('viewport').clientHeight/2){if(!width)return;const next=Math.max(.002,Math.min(16,scale*factor));tx=x-(x-tx)*next/scale;ty=y-(y-ty)*next/scale;scale=next;transform();}
function drawBoxes(){const canvas=$('boxes');const max=4096;const ratio=Math.min(1,max/Math.max(width,height));canvas.width=Math.max(1,Math.round(width*ratio));canvas.height=Math.max(1,Math.round(height*ratio));const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);const line=Math.max(2,Math.max(width,height)/1300);ctx.lineWidth=line;ctx.font=`${Math.max(12,line*5)}px sans-serif`;detections.forEach(d=>{if(!Array.isArray(d.bbox_xyxy))return;const [x,y,x2,y2]=d.bbox_xyxy;ctx.strokeStyle=color(d.class_id);ctx.fillStyle=ctx.strokeStyle;ctx.strokeRect(x,y,x2-x,y2-y);const label=String(d.label);const size=Math.max(12,line*5),tw=ctx.measureText(label).width+8,top=Math.max(0,y-size-7);ctx.fillRect(x,top,tw,size+6);ctx.fillStyle='#fff';ctx.fillText(label,x+4,top+size)});updateOverlay();}
function updateOverlay(){$('boxes').hidden=!overlay||$('view').value!=='boxes';$('semantic').hidden=!overlay||$('view').value!=='semantic'||!semanticUrl;$('toggleOverlay').setAttribute('aria-pressed',String(overlay));$('toggleOverlay').textContent=overlay?'◉ 结果显示':'○ 结果隐藏';}
$('toggleOverlay').onclick=()=>{overlay=!overlay;updateOverlay()};
$('view').onchange=async()=>{updateOverlay();if($('view').value==='semantic'&&result&&!semanticUrl){const current=result;try{const path=current.artifacts['pred_sem_seg_overlay.png'];if(!path)throw new Error('没有可用的语义分割产物');const blob=await(await request('/api/workspace/detection/api/file?path='+encodeURIComponent(path))).blob();if(result!==current)return;semanticUrl=URL.createObjectURL(blob);$('semantic').src=semanticUrl;updateOverlay()}catch(e){status(e.message,'error')}}};
function chooseFile(next){if(busy||!next)return;if(!/\.(jpe?g|png|webp|tiff?)$/i.test(next.name)||!next.size||next.size>100*1024*1024)return status('请选择 100 MB 以内的 JPG、PNG、WEBP 或 TIFF。','error');[originalUrl,semanticUrl].filter(Boolean).forEach(u=>URL.revokeObjectURL(u));file=next;originalUrl=URL.createObjectURL(next);semanticUrl=null;result=null;window.dispatchEvent(new Event('earthmind:result-cleared'));resultCategories=[];detections=[];width=height=0;gridState=null;drawGrid();$('filename').textContent=next.name+' · '+(next.size/1024/1024).toFixed(2)+' MB';$('imageInfo').textContent=next.name;$('count').textContent=$('elapsed').textContent='—';renderLegend();$('scene').hidden=true;$('empty').hidden=true;$('preview').src=originalUrl;$('progressTitle').textContent='切片推理进度';$('percent').textContent='—';$('progressDetail').textContent='等待任务开始';status('影像已就绪，确认提示词后开始识别。');updateOverlay();buttons();loadPrompts();}
$('preview').onload=()=>{width=$('preview').naturalWidth;height=$('preview').naturalHeight;$('scene').style.width=width+'px';$('scene').style.height=height+'px';$('scene').hidden=false;$('empty').hidden=true;$('imageInfo').textContent=`${file?.name||'影像'} · ${width} × ${height} px`;drawBoxes();fit()};
$('preview').onerror=()=>{$('scene').hidden=true;$('empty').hidden=false;$('empty').querySelector('h2').textContent='此格式将在推理后预览';$('empty').querySelector('p').textContent='浏览器无法直接预览该影像，仍可正常识别。'};
$('file').onchange=e=>chooseFile(e.target.files[0]);$('importImage').onclick=()=>$('file').click();
for(const id of ['drop','viewport']){const target=$(id);target.ondragover=e=>{e.preventDefault();if(!busy)target.classList.add('drag')};target.ondragleave=()=>target.classList.remove('drag');target.ondrop=e=>{e.preventDefault();target.classList.remove('drag');chooseFile(e.dataTransfer.files[0])}}
$('viewport').onpointerdown=e=>{if(e.target.closest('button')||!width||e.button!==0)return;drag={x:e.clientX,y:e.clientY,tx,ty};$('viewport').setPointerCapture(e.pointerId);$('viewport').classList.add('panning')};$('viewport').onpointermove=e=>{if(!drag)return;tx=drag.tx+e.clientX-drag.x;ty=drag.ty+e.clientY-drag.y;transform()};for(const name of ['pointerup','pointercancel','lostpointercapture'])$('viewport').addEventListener(name,()=>{drag=null;$('viewport').classList.remove('panning')});
$('viewport').addEventListener('wheel',e=>{if(!width)return;e.preventDefault();const r=$('viewport').getBoundingClientRect();zoomAt(Math.exp(-e.deltaY*.0015),e.clientX-r.left,e.clientY-r.top)},{passive:false});$('viewport').ondblclick=fit;$('fit').onclick=fit;$('zoomIn').onclick=()=>zoomAt(1.25);$('zoomOut').onclick=()=>zoomAt(.8);$('viewport').onkeydown=e=>{if(e.target!==$('viewport'))return;if(['+','=','-','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();if(e.key==='0')fit();else if(e.key==='-')zoomAt(.8);else if(e.key==='+'||e.key==='=')zoomAt(1.25);else {tx+=e.key==='ArrowLeft'?40:e.key==='ArrowRight'?-40:0;ty+=e.key==='ArrowUp'?40:e.key==='ArrowDown'?-40:0;transform()}}};
$('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.querySelector('.workspace').requestFullscreen()}catch(_){status('当前浏览器无法进入全屏，请使用窗口查看。')}};new ResizeObserver(()=>{fit();drawGrid()}).observe($('viewport'));
let gridAnimation=0;
function drawGrid(reveal=1){const c=$('grid'),ctx=c.getContext('2d');c.width=Math.max(200,c.clientWidth*devicePixelRatio);c.height=Math.max(80,c.clientHeight*devicePixelRatio);ctx.clearRect(0,0,c.width,c.height);$('gridEmpty').hidden=!!gridState?.total;if(!gridState?.total)return;const {cols,rows,total,completed=0,batch_size=1}=gridState;const cw=c.width/cols,ch=c.height/rows;const visible=Math.ceil(total*reveal);for(let i=0;i<visible;i++){const done=i<completed,active=!done&&i<completed+batch_size&&gridState.stage==='inference';ctx.fillStyle=done?'#70e1c1':active?'#a0c9c2':'#20333f';const gap=Math.min(2,cw*.12,ch*.12);ctx.fillRect((i%cols)*cw+gap,Math.floor(i/cols)*ch+gap,Math.max(.3,cw-gap*2),Math.max(.3,ch-gap*2));}}
function animateGrid(){cancelAnimationFrame(gridAnimation);const start=performance.now();const frame=t=>{const r=Math.min(1,(t-start)/650);drawGrid(r);if(r<1)gridAnimation=requestAnimationFrame(frame)};gridAnimation=requestAnimationFrame(frame);}
const stages={preparing:'模型已就绪，正在准备影像',waiting:'上传影像 / 等待模型',loading:'正在加载模型',inference:'按批次推理中',outputs:'切片完成，正在融合与生成结果',completed:'识别完成',failed:'任务失败'};
async function pollProgress(job){try{const state=await(await request('/api/workspace/detection/api/progress?job='+job)).json();if(activeJob!==job)return;const newGrid=state.total&&(!gridState||gridState.total!==state.total||gridState.cols!==state.cols);gridState=state;$('progressTitle').textContent=stages[state.stage]||'正在处理';$('percent').textContent=state.total?Math.floor((state.completed||0)/state.total*100)+'%':'—';$('progressDetail').textContent=state.total?`${state.rows} × ${state.cols} 网格 · ${state.completed||0} / ${state.total} 切片 · Batch ${state.batch_size}`:'正在准备，切片数量将由模型动态确定';if(newGrid)animateGrid();else drawGrid();}catch(e){if(activeJob===job)$('progressDetail').textContent='进度连接暂时中断，任务仍在运行';}}
async function download(name){if(!result?.artifacts[name])return;try{const blob=await(await request('/api/workspace/detection/api/file?download=1&path='+encodeURIComponent(result.artifacts[name]))).blob();const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),30000)}catch(e){status(e.message,'error')}}
$('downloadImage').onclick=()=>download($('view').value==='semantic'?'pred_sem_seg_overlay.png':'segearth_candidate_filtered_labeled_bbox.png');$('downloadJson').onclick=()=>download('segearth_candidates.json');$('downloadZip').onclick=()=>download('results.zip');
$('run').onclick=async()=>{if(busy||!file)return;if(!validBatch())return status('每批切片数请输入大于 0 的整数。','error');if(hasDraftChanges())return status('请先确认类别修改，再开始识别。','error');const error=categoryError(confirmedCategories);if(error)return status(error,'error');const runCategories=cloneCategories(confirmedCategories);const encoded=encodeURIComponent(JSON.stringify(runCategories));busy=true;result=null;window.dispatchEvent(new Event('earthmind:result-cleared'));detections=[];renderLegend();if(semanticUrl)URL.revokeObjectURL(semanticUrl);semanticUrl=null;overlay=true;drawBoxes();buttons();$('run').textContent='正在识别…';$('count').textContent='—';const bytes=crypto.getRandomValues(new Uint8Array(16));const job=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');activeJob=job;gridState=null;drawGrid();$('percent').textContent='—';$('progressTitle').textContent='正在准备识别';$('progressDetail').textContent='上传完成后等待模型划分切片';const started=Date.now();status('正在上传影像并准备推理，请保持页面打开。');const clock=setInterval(()=>$('elapsed').textContent=Math.floor((Date.now()-started)/1000)+' s',1000);let polling=false;const timer=setInterval(async()=>{if(polling)return;polling=true;try{await pollProgress(job)}finally{polling=false}},700);
try{const params=new URLSearchParams({filename:file.name,batch:$('batch').value,job});const data=await(await request('/api/workspace/detection/api/detect?'+params,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-SegEarth-Prompts':encoded},body:file})).json();resultCategories=runCategories;result=data;await pollProgress(job);clearInterval(timer);activeJob=null;detections=await(await request('/api/workspace/detection/api/file?path='+encodeURIComponent(data.artifacts['segearth_candidates.json']))).json();if(!$('preview').naturalWidth||$('scene').hidden){const path=data.artifacts['original_preview.png'];if(path){const blob=await(await request('/api/workspace/detection/api/file?path='+encodeURIComponent(path))).blob();URL.revokeObjectURL(originalUrl);originalUrl=URL.createObjectURL(blob);$('preview').src=originalUrl;}}drawBoxes();clearInterval(clock);$('count').textContent=data.detection_count;renderLegend();$('elapsed').textContent=Number(data.provenance.elapsed_seconds).toFixed(1)+' s';$('view').value='boxes';updateOverlay();$('progressTitle').textContent='识别完成';status('识别完成。可以隐藏叠加结果、拖动缩放影像或下载产物。');}
catch(e){result=null;detections=[];drawBoxes();status(e.message||'连接中断；请先检查任务状态，避免重复提交。','error');$('progressTitle').textContent='任务未完成';if(gridState){gridState.stage='failed';drawGrid()}}
finally{clearInterval(timer);clearInterval(clock);activeJob=null;busy=false;$('run').innerHTML='开始识别 <span>↗</span>';buttons();}};
async function health(){try{const response=await fetch('/api/workspace/detection/health');if(!response.ok)throw new Error('offline');const h=await response.json();if(h.error)throw new Error(h.error);$('health').textContent=h.busy?'服务处理中':h.worker?.model_loaded?'服务在线 · 模型已驻留':'服务在线';$('health').className='health ready'}catch(_){$('health').textContent='服务未连接';$('health').className='health'}}health();setInterval(health,10000);buttons();
