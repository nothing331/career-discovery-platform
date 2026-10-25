// Serialized into each trusted embedded project document at build/runtime.
window.makeWorkspaceChildBridge = function workspaceChildBridge(config) {
  'use strict';
  const channel = 'fieldnotes-connected-v1';
  const send = (type, data = {}) => parent.postMessage({channel, page: config.id, type, ...data}, '*');
  const frameSections = config.sections || [];
  let requestedRoute = config.route || 'overview';
  let announceTimer, resizeTimer, lastHeight = 0;
  function cleanHash() { return config.id === 'poc' ? requestedRoute : location.hash.slice(1) || 'overview'; }
  function height() {
    // body bounds shrink when another routed view becomes visible; scrollHeight alone cannot.
    const size = Math.ceil(document.body.getBoundingClientRect().height + 5);
    if (size > 50 && Math.abs(size-lastHeight)>1) { lastHeight=size; send('height',{height:size}); }
  }
  function queueHeight() { clearTimeout(resizeTimer); resizeTimer=setTimeout(height,35); }
  function targetFor(route) {
    if (config.id === 'poc') return document.getElementById(route);
    if (config.id === 'workspace' && /^(document|research-report)=/.test(route)) {
      const section = new URLSearchParams(route).get('section');
      return section ? document.getElementById(section) : null;
    }
    return route.startsWith('claim-') ? document.getElementById(route) : null;
  }
  function announce(scroll) {
    clearTimeout(announceTimer);
    announceTimer=setTimeout(()=>{
      height();
      const route=cleanHash();
      send('route',{route,title:document.title});
      if(scroll) { const target=targetFor(route); send('scroll',{y:target ? target.getBoundingClientRect().top+scrollY : 0}); }
    },65);
  }
  function navigate(route, scroll = true) {
    requestedRoute=route || 'overview';
    if(config.id==='poc') {
      announce(scroll);
    } else {
      if(cleanHash()===requestedRoute) {
        // DOM initialization already routed the page; announce once more after sizing.
        announce(scroll);
      } else location.replace(location.href.split('#')[0]+'#'+requestedRoute);
    }
  }
  function pathKey(url) {
    const name=decodeURIComponent(url.pathname.split('/').pop() || '');
    return config.files[name] || null;
  }
  function workspaceRouteFor(url, href) {
    const path=decodeURIComponent(url.pathname), hash=url.hash.slice(1);
    if(/\.(?:md|json)$/i.test(path)) {
      let key=path;
      const rootMarker='/career-discovery-platform/';
      if(path.includes(rootMarker)) key=path.split(rootMarker).pop();
      // Normalize repository-relative references independently of the exported file's folder.
      else if(!/^(?:[a-z][a-z\d+.-]*:|\/)/i.test(href)) key=decodeURIComponent(new URL(href,'https://workspace.local/product-workspace/'+config.file).pathname.slice(1));
      else if(config.rootPath && path.startsWith(config.rootPath)) key=path.slice(config.rootPath.length);
      key=key.replace(/^\//,'');
      const params=new URLSearchParams({document:key,from:config.parentNav || 'research'});
      if(hash)params.set('section',hash);
      return params.toString();
    }
    return null;
  }
  document.addEventListener('click',event=>{
    const link=event.target.closest('a[href]');if(!link)return;
    const href=link.getAttribute('href');if(!href||/^(?:https?:|mailto:|tel:|blob:|data:)/i.test(href))return;
    if(href.startsWith('#')) {
      event.preventDefault();
      if(config.id==='poc') navigate(href.slice(1),true);
      else send('navigate',{destination:config.id,route:href.slice(1)});
      return;
    }
    let url;try{url=new URL(href,config.baseURL)}catch{return;}
    const page=pathKey(url);
    if(page) {event.preventDefault();send('navigate',{destination:page,route:url.hash.slice(1)||'overview'});return;}
    const route=workspaceRouteFor(url, href);
    if(route){event.preventDefault();send('navigate',{destination:'workspace',route});}
  },true);
  addEventListener('hashchange',()=>announce(true));
  function readPocState() {
    const result={};
    for(const id of ['model','documents','calls','input-tokens','output-tokens','retry']) {
      const field=document.getElementById(id);if(field)result[id]=field.value;
    }
    return result;
  }
  function restorePocState(values) {
    if(config.id!=='poc'||!values)return;
    for(const [id,value] of Object.entries(values)) {
      const field=document.getElementById(id);if(!field||typeof value!=='string')continue;
      const before=field.value;field.value=value;
      if(field.tagName==='SELECT'&&!field.value)field.value=before;
      if(field.tagName==='INPUT'&&!field.checkValidity())field.value=before;
    }
    document.getElementById('model')?.dispatchEvent(new Event('input',{bubbles:true}));
  }
  if(config.id==='poc') {
    restorePocState(config.pageState);
    document.getElementById('cost-form')?.addEventListener('input',()=>send('page-state',{state:readPocState()}));
    document.getElementById('reset-cost')?.addEventListener('click',()=>send('page-state',{state:readPocState()}));
    const observer=new IntersectionObserver(entries=>{
      const top=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];
      if(top)send('section',{route:top.target.id});
    },{rootMargin:'-5% 0px -65% 0px',threshold:0});
    // Parent scroll drives the chapter navigation; this observer helps standalone-size hosts.
    document.querySelectorAll('main>section[id]').forEach(section=>observer.observe(section));
  }
  if(config.id==='archive') {
    document.querySelectorAll('form input,form textarea,form select,form button,#task-list input,#export-workspace').forEach(field=>field.disabled=true);
    document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>event.preventDefault(),true));
  }
  const status=document.getElementById('save-state');
  if(config.id==='workspace'&&status) {
    const sync=()=>send('draft-status',{text:status.textContent});new MutationObserver(sync).observe(status,{childList:true,subtree:true,characterData:true});sync();
  }
  const toast=document.getElementById('toast');
  if(config.id==='workspace'&&toast)new MutationObserver(()=>{if(!toast.hidden&&toast.textContent)send('toast',{text:toast.textContent});}).observe(toast,{attributes:true,childList:true,subtree:true,characterData:true});
  addEventListener('message',event=>{
    if(event.source!==parent||event.data?.channel!==channel||event.data.page!==config.id)return;
    const message=event.data;
    if(message.type==='navigate')navigate(message.route,message.scroll!==false);
    if(message.type==='print')window.print();
    if(message.type==='snapshot') {
      try {const state=config.id==='workspace'?window.workspaceStateApi.getState():readPocState();send('snapshot-result',{requestId:message.requestId,state});}
      catch(error){send('snapshot-result',{requestId:message.requestId,error:String(error.message||error)});}
    }
    if(message.type==='positions'&&config.id==='poc')send('positions',{sections:frameSections.map(section=>({id:section.id,y:document.getElementById(section.id)?.getBoundingClientRect().top+scrollY||0}))});
  });
  new ResizeObserver(queueHeight).observe(document.body);
  document.fonts?.ready.then(queueHeight);
  addEventListener('resize',()=>{queueHeight();if(config.id==='poc')send('positions',{sections:frameSections.map(section=>({id:section.id,y:document.getElementById(section.id)?.getBoundingClientRect().top+scrollY||0}))});});
  send('ready');navigate(requestedRoute,false);setTimeout(()=>announce(true),100);
};
