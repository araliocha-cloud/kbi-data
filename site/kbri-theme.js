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
