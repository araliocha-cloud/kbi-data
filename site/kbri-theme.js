/* KBRI theme helper : marks page-intro text widgets for styling. Changes no stored content. */
(function(){
 function tc(s){return s.toLowerCase().replace(/\b([a-z])/g,function(m){return m.toUpperCase()}).replace(/\b(And|Of|The|For|In|On)\b/g,function(m,w,i){return i?w.toLowerCase():w}).replace(/\bKbri\b/,'KBRI').replace(/\bWbi\b/,'WBI').replace(/\bKbi\b/,'KBI').replace(/\bWbci\b/,'WBCI').replace(/\bHcx\b/,'HCX')}
 function run(){
  var ws=document.querySelectorAll('#doz_body ._text_wrap, .section_wrap ._text_wrap');
  for(var i=0;i<ws.length;i++){
   var w=ws[i]; if(w.classList.contains('kb-intro')||w.closest('#doz_header_wrap')) continue;
   var ps=w.querySelectorAll('p'); if(!ps.length) continue;
   var t=(ps[0].textContent||'').trim();
   if(!/^[A-Z][A-Z0-9 &'’.,()\-]{4,60}$/.test(t)) continue;
   var r=w.getBoundingClientRect(); if(r.top+window.scrollY>1400) continue;
   w.classList.add('kb-intro');
   var words=tc(t).split(' '); var last=words.pop();
   var cap=document.createElement('span'); cap.className='kb-cap'; var a=document.querySelector('[data-widget-type] .sub-menu a.active, .sub-menu a.active'); cap.textContent=(document.querySelector('#s2026072819fb105033eda a.active')||{}).textContent||'KBRI';
   ps[0].classList.add('kb-t'); ps[0].innerHTML=''; if(words.length){ps[0].appendChild(document.createTextNode(words.join(' ')+' '))} var em=document.createElement('em'); em.textContent=last; ps[0].appendChild(em);
   ps[0].parentNode.insertBefore(cap,ps[0]);
   for(var j=1;j<ps.length;j++){var p=ps[j]; var tx=(p.textContent||'').replace(/\s+/g,'');
    if(!tx){p.style.display='none';continue}
    if(j===1&&p.querySelector('em')){p.classList.add('kb-s');continue}
    p.classList.add('kb-b');}
  }
 }
 if(document.readyState!=='loading')run(); else document.addEventListener('DOMContentLoaded',run);
 window.addEventListener('load',run);
})();

/* pages without their own sub menu get one built from the header menu (no stored content changes) */
(function(){
 function norm(p){try{p=new URL(p,location.origin).pathname}catch(e){}return p.replace(/\/+$/,'').toLowerCase()||'/'}
 function build(){
  if(document.querySelector('.sub-menu, .kb-submenu')) return;
  if(/^\/(admin|_)/.test(location.pathname)) return;
  var here=norm(location.pathname); if(here==='/'||here==='/home') return;
  var nav=document.querySelector('#s2026072819fb105033eda .viewport-nav'); if(!nav) return;
  var tops=nav.querySelectorAll(':scope > li'); var hit=null;
  for(var i=0;i<tops.length&&!hit;i++){var as=tops[i].querySelectorAll('.dropdown-menu a'); for(var j=0;j<as.length;j++){if(norm(as[j].getAttribute('href'))===here){hit=tops[i];break}}}
  if(!hit) return;
  var links=hit.querySelectorAll('.dropdown-menu a'); if(links.length<2) return;
  var bar=document.createElement('nav'); bar.className='kb-submenu'; bar.setAttribute('aria-label','Sub menu');
  var ul=document.createElement('ul');
  for(var k=0;k<links.length;k++){var li=document.createElement('li'); var a=document.createElement('a'); a.href=links[k].getAttribute('href'); var pn=document.createElement('span'); pn.className='plain_name'; pn.textContent=links[k].textContent.trim(); var src=links[k].querySelector('.plain_name'); if(src&&src.getAttribute('data-hover')) pn.setAttribute('data-hover',src.getAttribute('data-hover')); a.appendChild(pn); if(norm(a.getAttribute('href'))===here) a.className='active'; li.appendChild(a); ul.appendChild(li)}
  bar.appendChild(ul);
  var first=document.querySelector('#doz_body .section_wrap, main .section_wrap, .section_wrap.pc_section');
  if(first&&first.parentNode) first.parentNode.insertBefore(bar,first); else return;
 }
 if(document.readyState!=='loading')build(); else document.addEventListener('DOMContentLoaded',build);
 window.addEventListener('load',build);
})();

/* expose the height of the pinned sub menu so floating panels (HCX result bar) can sit below it */
(function(){
 function upd(){var r=document.querySelector('.kb-sub-fixed')||document.querySelector('.kb-submenu');var h=0;if(r){var b=r.getBoundingClientRect();if(r.classList.contains('kb-sub-fixed')||b.top<=parseFloat(getComputedStyle(r).top||0)+1)h=b.height}document.documentElement.style.setProperty('--kbSubH',h+'px')}
 window.addEventListener('scroll',upd,{passive:true});window.addEventListener('resize',upd);window.addEventListener('load',upd);
})();

/* justify every left-aligned paragraph in the content area (designed centred or right-aligned text is left alone) */
(function(){
 var SEL='#doz_body p, #doz_body li, .section_wrap p, .section_wrap li';
 function ok(el){
  if(el.closest('#doz_header_wrap, #doz_footer_wrap, nav, .sub-menu, .kb-submenu, .li_board, .paging-block, .dropdown-menu, button, .board_summary')) return false;
  if(el.closest('li')&&el.tagName==='LI'&&el.closest('ul.li_body, .viewport-nav')) return false;
  var cs=getComputedStyle(el); var ta=cs.textAlign;
  if(/flex|grid/.test(cs.display)) return false;
  if(el.offsetWidth<380) return false;
  if(/(eyebrow|mono|cap|kicker|label|tag|meta|time|date)/i.test(el.className)) return false;
  if(cs.textTransform==='uppercase') return false;
  if(!(ta==='left'||ta==='start'||ta==='justify')) return false;
  if(el.offsetHeight<parseFloat(cs.lineHeight||'20')*1.6) return false;
  return true;
 }
 var t=null;
 function run(){t=null; var ns=document.querySelectorAll(SEL); for(var i=0;i<ns.length;i++){var n=ns[i]; if(!n.classList.contains('kb-j')&&ok(n)) n.classList.add('kb-j')}}
 function soon(){if(!t)t=setTimeout(run,400)}
 if(document.readyState!=='loading')soon(); else document.addEventListener('DOMContentLoaded',soon);
 window.addEventListener('load',soon); window.addEventListener('resize',soon);
 try{new MutationObserver(soon).observe(document.documentElement,{childList:true,subtree:true})}catch(e){}
})();
