(()=>{
'use strict';
const CHANNEL='fieldnotes-connected-v1';
const pages=JSON.parse(document.getElementById('workspace-pages').textContent);
const clone=value=>JSON.parse(JSON.stringify(value));
const $=selector=>document.querySelector(selector);
const safeJSON=value=>JSON.stringify(value).replace(/</g,'\\u003c');
const files=Object.fromEntries(Object.entries(pages).map(([id,page])=>[page.file,id]));
const workRoutes={overview:'Overview',brief:'Product brief',plan:'Startup plan',research:'Research library',experiments:'Next experiments',decisions:'Decision log'};
let uiState=JSON.parse($('#connected-state').textContent);
try{const draft=JSON.parse(localStorage.getItem('fieldnotes-connected-state:v1')||'null');if(draft&&draft.poc&&typeof draft.poc==='object'&&Date.parse(draft.updatedAt)>Date.parse(uiState.updatedAt))uiState=draft;}catch{}
const frames=new Map(),requests=new Map();let active,toastTimer,routeSerial=0,pocPositions=[];
function parseRoute(raw=location.hash.slice(1)){
 raw=raw||'overview';
 const slash=raw.indexOf('/'),id=slash<0?raw:raw.slice(0,slash);
 if(['report','strategy','poc','archive'].includes(id))return{page:id,route:slash<0?'overview':raw.slice(slash+1)||'overview',nav:id};
 if(/^(?:document|research-report)=/.test(raw))return{page:'workspace',route:raw,nav:'research'};
 return{page:'workspace',route:Object.hasOwn(workRoutes,raw)?raw:'overview',nav:Object.hasOwn(workRoutes,raw)?raw:'overview'};
}
function hashFor(page,route){return page==='workspace'?'#'+(route||'overview'):'#'+page+'/'+(route||'overview');}
function send(id,type,data={}){frames.get(id)?.element.contentWindow?.postMessage({channel:CHANNEL,page:id,type,...data},'*');}
function toast(text){$('#project-toast').textContent=text;$('#project-toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#project-toast').hidden=true,4200);}
const embedStyle=`html,body{margin:0!important;overflow:hidden!important;background:#f7f5ef!important;}body{min-height:0!important;} .sidebar,.topbar,.footer,.masthead,.toc,.reader-toolbar,#toast,#workspace-links,.skip,.status,#export-workspace{display:none!important;} .shell,.layout{display:block!important;min-height:0!important;} .main{padding:0!important;min-width:0!important;} .page{max-width:none!important;padding:0!important;margin:0!important;} .hero{animation:none!important;padding-top:34px!important;} .view{animation:none!important;padding-top:34px!important;} .view[hidden]{display:none!important;} .help-dialog{max-width:calc(100% - 32px)!important;} @media print{html,body{overflow:visible!important;} .view[hidden]{display:block!important;} body.reading-document .view[hidden]{display:none!important;}}`;
function escapeAttr(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function createFrame(id,route){
 if(frames.has(id))return frames.get(id);
 const page=pages[id],element=document.createElement('iframe');element.className='connected-page';element.dataset.page=id;element.title=page.title;element.hidden=true;
 // These documents are trusted repository content; same-origin preserves existing local drafts.
 element.setAttribute('sandbox','allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-modals allow-downloads');
 const state={element,ready:false,route,height:600};frames.set(id,state);element.style.height='600px';
 const baseURL=new URL(page.file,location.href).href;
 const rootPath=new URL('../',location.href).pathname;
 let html=page.html.replace(/<head([^>]*)>/i,(_match,attrs)=>'<head'+attrs+'><base href="'+escapeAttr(baseURL)+'"><style>'+embedStyle+'</style>');
 if(id==='archive')html=html.replace(/<head([^>]*)>/i,'<head$1><script>try{Object.defineProperty(window,"localStorage",{get(){throw new Error("Historical snapshot is read-only")}})}catch{}<\/script>');
 const config={id,route,files,file:page.file,baseURL,rootPath,parentNav:active?.nav||'research',sections:page.sections,pageState:id==='poc'?uiState.poc:null};
 const bridge='('+window.makeWorkspaceChildBridge.toString()+')('+safeJSON(config)+');';
 html=html.replace(/<\/body>/i,'<script>'+bridge.replace(/<\/script/gi,'<\\/script')+'<\/script></body>');
 $('#page-host').append(element);element.srcdoc=html;
 return state;
}
function renderSectionNav(){
 const page=pages[active.page],sections=page.sections||[];
 $('#page-sections').hidden=active.page==='workspace'||!sections.length;
 $('#page-sections').innerHTML='';
 for(const section of sections){const link=document.createElement('a');link.href=hashFor(active.page,section.id);link.textContent=section.title;link.dataset.section=section.id;if(section.id===active.route)link.setAttribute('aria-current','page');$('#page-sections').append(link);}
}
function setTitle(){const page=pages[active.page];const section=(page.sections||[]).find(section=>section.id===active.route);const title=active.page==='workspace'?(workRoutes[active.route]||'Research reader'):page.title+(section?' / '+section.title:'');$('#page-title').textContent=title;document.title=title+' · Fieldnotes';}
function route(focus=true){
 active=parseRoute();routeSerial++;
 document.querySelectorAll('#project-nav a').forEach(link=>{if(link.dataset.nav===active.nav)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
 setTitle();renderSectionNav();$('#archive-notice').hidden=active.page!=='archive';$('#load-error').hidden=true;
 for(const [id,frame]of frames)frame.element.hidden=id!==active.page;
 const frame=createFrame(active.page,active.route);frame.element.hidden=false;frame.route=active.route;
 $('#page-loading').hidden=frame.ready;
 if(frame.ready)send(active.page,'navigate',{route:active.route,scroll:focus});
 if(active.page==='poc'&&frame.ready)send('poc','positions');
 if(focus){$('#project-main').focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
}
function routeTo(page,subroute){const hash=hashFor(page,subroute);if(location.hash===hash)route(true);else location.hash=hash;}
function scrollToChild(y){const frame=frames.get(active.page);if(!frame)return;const top=frame.element.getBoundingClientRect().top+scrollY;window.scrollTo({top:y>0?Math.max(0,top+y-22):0,behavior:'instant'});}
addEventListener('hashchange',()=>route(true));
addEventListener('message',event=>{
 const data=event.data;if(!data||data.channel!==CHANNEL)return;const frame=frames.get(data.page);if(!frame||event.source!==frame.element.contentWindow)return;
 if(data.type==='ready'){frame.ready=true;if(active.page===data.page){$('#page-loading').hidden=true;send(data.page,'navigate',{route:active.route,scroll:false});if(data.page==='poc')send('poc','positions');}return;}
 if(data.type==='height'&&Number.isFinite(data.height)){frame.height=Math.max(100,Math.min(100000,data.height));frame.element.style.height=frame.height+'px';return;}
 if(data.type==='snapshot-result'){const pending=requests.get(data.requestId);if(pending){clearTimeout(pending.timer);requests.delete(data.requestId);data.error?pending.reject(new Error(data.error)):pending.resolve(data.state);}return;}
 if(data.type==='draft-status'){$('#draft-status').textContent=data.text;return;}
 if(data.type==='page-state'&&data.page==='poc'&&data.state&&typeof data.state==='object'){
   const allowed=['model','documents','calls','input-tokens','output-tokens','retry'];uiState.poc=Object.fromEntries(allowed.filter(key=>typeof data.state[key]==='string').map(key=>[key,data.state[key]]));uiState.updatedAt=new Date().toISOString();try{localStorage.setItem('fieldnotes-connected-state:v1',JSON.stringify(uiState));}catch{}return;
 }
 if(data.type==='positions'&&data.page==='poc'){pocPositions=data.sections;return;}
 if(active.page!==data.page)return;
 if(data.type==='navigate'&&pages[data.destination]){routeTo(data.destination,data.route);return;}
 if(data.type==='route'&&typeof data.route==='string'){
   if(data.route!==active.route){const hash=hashFor(data.page,data.route);if(location.hash!==hash)location.hash=hash;}
   return;
 }
 if(data.type==='scroll'&&Number.isFinite(data.y)){scrollToChild(data.y);return;}
 if(data.type==='toast'&&typeof data.text==='string')toast(data.text);
});
let scrollQueued=false;addEventListener('scroll',()=>{if(active?.page!=='poc'||!pocPositions.length||scrollQueued)return;scrollQueued=true;requestAnimationFrame(()=>{scrollQueued=false;const frame=frames.get('poc');const y=scrollY-frame.element.getBoundingClientRect().top-scrollY+80;const section=pocPositions.filter(section=>section.y<=y).at(-1)||pocPositions[0];document.querySelectorAll('#page-sections a').forEach(link=>{if(link.dataset.section===section.id)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');});});},{passive:true});
function snapshotWorkspace(){return new Promise((resolve,reject)=>{const id='snapshot-'+Date.now()+'-'+Math.random().toString(16).slice(2);const started=Date.now();const submit=()=>{if(!frames.get('workspace')?.ready){if(Date.now()-started>7000){reject(new Error('The editable workspace is still loading. Try exporting again after it opens.'));return;}setTimeout(submit,50);return;}const timer=setTimeout(()=>{requests.delete(id);reject(new Error('The working brief could not be captured. Please reopen Product brief and try again.'));},7000);requests.set(id,{resolve,reject,timer});send('workspace','snapshot',{requestId:id});};submit();});}
$('#export-all').addEventListener('click',async()=>{
 const button=$('#export-all');button.disabled=true;button.textContent='Preparing…';
 try{
   const state=await snapshotWorkspace(),exportPages=clone(pages);
   exportPages.workspace.html=exportPages.workspace.html.replace(/(<script id="workspace-data"[^>]*>)[\s\S]*?(<\/script>)/,(_match,open,close)=>open+safeJSON(state)+close);
   const doc=document.documentElement.cloneNode(true);doc.querySelector('#workspace-pages').textContent=safeJSON(exportPages);doc.querySelector('#connected-state').textContent=safeJSON(uiState);doc.querySelector('#page-host').innerHTML='';doc.querySelector('#project-help').removeAttribute('open');doc.querySelector('#project-toast').hidden=true;doc.querySelector('#export-all').disabled=false;doc.querySelector('#export-all').textContent='Export all pages';doc.querySelector('#draft-status').textContent='Exported copy';
   const blob=new Blob(['<!doctype html>\n'+doc.outerHTML],{type:'text/html;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='index.html';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);toast('Complete workspace exported: all pages, current answers and calculator settings.');
 }catch(error){toast(error.message||'Export failed. Please try again.');}
 finally{button.disabled=false;button.textContent='Export all pages';}
});
$('#print-current').addEventListener('click',()=>send(active.page,'print'));
const help=$('#project-help');$('#open-project-help').addEventListener('click',()=>help.showModal());$('#close-project-help').addEventListener('click',()=>help.close());$('#close-project-help-bottom').addEventListener('click',()=>help.close());help.addEventListener('click',event=>{if(event.target===help){const box=help.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)help.close();}});
$('.skip').addEventListener('click',event=>{event.preventDefault();$('#project-main').focus({preventScroll:true});$('#project-main').scrollIntoView();});
// Capture the original brief in every export, even when another page is opened first.
active=parseRoute();createFrame('workspace',active.page==='workspace'?active.route:'overview');route(false);
})();
