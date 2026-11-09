/* =====================================================================
   FINAL REPORT: when a run ends it becomes a record (ideas, conversations, insights, chart data),
   a newsletter (written by the model through serve.py, or from templates), achievements, and the
   "who talked to whom" chart from visual-summary/ fed with this run. serve.py keeps each record in
   data/runs/, so earlier runs can be reopened from the report.
   ===================================================================== */
const REPORT={current:null,viewing:null,tab:"news",writing:false,list:null};
const hhOf=clk=>clk.replace(/^d\d+ /,"");
// chart time: day start + minutes since 09:00 (3 s of simulation per minute, as in memory.js hhmm)
const tOf=(day,clk)=>{const [h,m]=hhOf(clk).split(":").map(Number);return (day-1)*DAY_LEN+Math.max(0,(h*60+m-540)*3)};
const placeName=id=>lang==="en"&&SP_EN[id]?SP_EN[id]:SP[id].n;
const nameOf=a=>a.user?(a.pf.name||L("you")):(a.pf.name||tr(who(a)));

/* the chart's data, in the shape of visual-summary/narrative-data.js */
function chartData(){
  const list=agents.filter(a=>a.active||a.user),idOf=new Map(list.map((a,i)=>[a,i])),ids=xs=>xs.filter(m=>idOf.has(m)).map(m=>idOf.get(m));
  return {source:`placelab run ${runNo}`,dayLen:DAY_LEN,days:CFG.days,
    agents:list.map((a,i)=>({id:i,code:a.pf.code,team:a.group,group:true,project:a.pf.project,short:shortP(a.pf.project),img:a.tex[0].url,name:nameOf(a),
      label:a.user?`${nameOf(a)} · ${L("you")}`:`${nameOf(a)}’s agent`,role:"student"})),
    convs:CLOG.filter(c=>idOf.has(c.a)&&idOf.has(c.b)).map((c,k)=>({id:"c"+k,t:tOf(c.day,c.clk),day:c.day,clk:hhOf(c.clk),place:placeName(c.place),out:c.out==="agr"?"none":c.out,
      a:idOf.get(c.a),b:idOf.get(c.b),idea:c.idea?c.idea.id:null,topic:c.idea?ideaTitle(c.idea):c.topics?`${c.topics.a} × ${c.topics.b}`:"—",inferred:false,
      lines:(c.lines||[]).filter(l=>idOf.has(l.w)).map(l=>({w:idOf.get(l.w),t:lineText(l)}))})),
    ideas:IDEAS.map(i=>({id:i.id,title:ideaTitle(i),members:ids([...i.members]),born:{t:tOf(i.born.day,i.born.clk),day:i.born.day,clk:i.born.clk,place:placeName(i.born.place)},
      versions:i.versions.map(v=>({n:v.n,kind:v.kind,t:tOf(+(v.clk.match(/^d(\d+)/)||[0,1])[1],v.clk),clk:v.clk,place:placeName(v.place),by:ids(v.by),text:v.kind==="born"&&i.llm?i.llm.pitch:tr(v.text)}))}))};
}
function buildRecord(){
  const code=a=>a.pf.code,last=i=>i.versions[i.versions.length-1];
  const rec={created:new Date().toISOString(),run:runNo,lang,days:CFG.days,model:LLM.on?LLM.model:null,you:userAgent?code(userAgent):null,
    agents:Object.fromEntries(agents.filter(a=>a.active||a.user).map(a=>[code(a),{name:a.pf.name||"",label:tr(who(a)),img:a.tex[0].url,project:a.pf.project,you:!!a.user}])),
    ideas:IDEAS.map(i=>({id:i.id,title:ideaTitle(i),pitch:i.llm?i.llm.pitch:ideaText(i),founders:i.by.map(code),members:[...i.members].map(code),
      born:{day:i.born.day,clk:hhOf(i.born.clk),place:placeName(i.born.place)},versions:i.versions.length,lineage:i.lineage||null,
      latest:i.versions.length>1?(last(i).kind==="llm"?last(i).text:tr(last(i).text)):null})),
    convs:CLOG.map((c,k)=>({id:"c"+k,day:c.day,clk:hhOf(c.clk),place:placeName(c.place),a:code(c.a),b:code(c.b),out:c.out,idea:c.idea?c.idea.id:null,
      insight:c.insight||"",topics:c.topics||null,followup:!!c.followup,mine:!!c.mine})),
    chart:chartData()};
  rec.stats={convs:rec.convs.length,ideas:rec.ideas.length,followups:rec.convs.filter(c=>c.followup).length,model:rec.model};
  rec.achievements=achievementsOf(rec);
  return rec;
}
/* achievements: the "talk with 3 people" goal plus what the reader's agent did with ideas and memory */
function achievementsOf(rec){
  const me=rec.you;if(!me)return [];
  const mine=rec.convs.filter(c=>c.a===me||c.b===me),partners=new Set(mine.map(c=>c.a===me?c.b:c.a)),team=Object.keys(rec.agents).filter(k=>k!==me);
  return [["goal",partners.size>=CFG.goal],["cofound",rec.ideas.some(i=>i.founders.includes(me))],["evolve",mine.some(c=>c.out==="evo")],
    ["followup",mine.some(c=>c.followup)],["lineage",rec.ideas.some(i=>i.lineage&&i.members.includes(me))],["circle",team.length>0&&team.every(k=>partners.has(k))]].map(([k,got])=>({k,got}));
}

/* ---------- the newsletter: model-written through serve.py, or from templates ---------- */
function newsContext(rec){
  const h=c=>"@"+c;
  return {lang:rec.lang,you:rec.you?h(rec.you):null,days:rec.days,
    ideas:rec.ideas.map(i=>({id:i.id,title:i.title,pitch:i.pitch,latest_version:i.latest,founders:i.founders.map(h),members:i.members.map(h),
      born:`day ${i.born.day} ${i.born.clk} at ${i.born.place}`,versions:i.versions,builds_on_earlier_run:i.lineage?i.lineage.title:null})),
    insights:rec.convs.filter(c=>c.insight).slice(-40).map(c=>({day:c.day,time:c.clk,place:c.place,between:[h(c.a),h(c.b)],brought:c.topics?[c.topics.a,c.topics.b]:[],insight:c.insight,idea:c.idea,follow_up:c.followup})),
    your_conversations:rec.you?rec.convs.filter(c=>c.mine).map(c=>{const first=c.a===rec.you;return {with:h(first?c.b:c.a),day:c.day,time:c.clk,
      you_brought:c.topics?(first?c.topics.a:c.topics.b):null,they_brought:c.topics?(first?c.topics.b:c.topics.a):null,insight:c.insight,idea:c.idea}}):[]};
}
function templateNews(rec){
  const me=rec.you,mine=rec.convs.filter(c=>c.mine),partners=[...new Set(mine.map(c=>"@"+(c.a===me?c.b:c.a)))];
  return {template:true,headline:L2("tplHead")(rec.ideas.length,rec.convs.length),lede:L2("tplLede")(rec.days,rec.convs.length,rec.stats.followups,rec.ideas.length),
    stories:rec.ideas.slice(0,6).map(i=>({idea_id:i.id,headline:i.title,blurb:i.latest||i.pitch})),
    column_title:L2("tplColumnT"),column:L2("tplColumn")(mine.length,partners.join(", "),mine.map(c=>c.insight).filter(Boolean).pop()||"")};
}
async function finishRun(){
  const rec=buildRecord();REPORT.current=REPORT.viewing=rec;REPORT.tab="news";REPORT.writing=true;renderReport();
  try{rec.newsletter=LLM.on?await postJSON("/api/newsletter",newsContext(rec)):templateNews(rec)}
  catch(e){console.warn("newsletter from templates:",e.message);rec.newsletter=templateNews(rec)}
  REPORT.writing=false;
  if(LLM.server)try{const r=await postJSON("/api/runs",rec);rec.id=r.id;REPORT.list=null}catch(e){console.warn("run not saved:",e.message)}
  if(REPORT.viewing===rec)renderReport();
}

/* ---------- rendering ---------- */
function chip(rec,code){const a=rec.agents[code];if(!a)return esc("@"+code);
  return `<span class="nl-who"><img alt="" src="${a.img}">${esc(a.name||a.label)}${a.you?` <span class="youtag">${L("you")}</span>`:""}</span>`}
const withHandles=(rec,s)=>esc(s||"").replace(/@([A-Za-z]{1,3}\d{1,4})\b/g,(m,c)=>rec.agents[c]?chip(rec,c):m);
function newsletterHTML(rec){
  const N=rec.newsletter;if(!N)return `<p class="hint">${L2("writing")}</p>`;
  const idea=id=>rec.ideas.find(i=>i.id===id),me=rec.you,ach=L2("ach");
  const stories=N.stories.map(s=>{const i=idea(s.idea_id);if(!i)return "";
    return `<div class="nl-story"><span class="mono">${L("dayShort")} ${i.born.day} · ${esc(i.born.clk)} · ${esc(i.born.place)}${i.versions>1?` · ${L2("versions")(i.versions)}`:""}</span>
      <h4>${withHandles(rec,s.headline)}</h4><div class="nl-title">«${esc(i.title)}»</div><p>${withHandles(rec,s.blurb)}</p>
      <div class="nl-by">${i.members.map(c=>chip(rec,c)).join("")}</div>${i.lineage?`<div class="hint">${L2("builtOn")} «${esc(i.lineage.title)}» · ${L2("fromRun")(+(String(i.lineage.id).match(/^r(\d+)/)||[0,"?"])[1])}</div>`:""}</div>`}).join("");
  const insights=rec.convs.filter(c=>c.insight).slice(-8).reverse().map(c=>`<li><span class="mono">${L("dayShort")} ${c.day} · ${esc(c.clk)} · ${esc(c.place)}${c.followup?` · ${L2("followup")}`:""}</span>
      <div class="nl-pair">${chip(rec,c.a)}${chip(rec,c.b)}</div><p>${esc(c.insight)}</p>${c.topics?`<div class="hint">${esc(c.topics.a)} × ${esc(c.topics.b)}</div>`:""}</li>`).join("");
  const mine=me?rec.convs.filter(c=>c.mine):[];
  const yourConvs=!me?`<p class="hint">${L2("noYou")}</p>`:mine.length?`<ul class="nl-mine">${mine.slice(-8).reverse().map(c=>{const o=c.a===me?c.b:c.a;return `<li><span class="mono">${L("dayShort")} ${c.day} · ${esc(c.clk)}</span> ${chip(rec,o)}${c.idea&&idea(c.idea)?` <span class="ok">«${esc(idea(c.idea).title)}»</span>`:""}${c.insight?`<p>${esc(c.insight)}</p>`:""}</li>`}).join("")}</ul>${mine.length>8?`<p class="hint">${L2("moreConvs")(mine.length-8)}</p>`:""}`:`<p class="hint">${L2("noYouConvs")}</p>`;
  const badges=rec.achievements.length?`<div class="nl-ach">${rec.achievements.map(a=>{const [t,d]=ach[a.k];return `<div class="badge${a.got?" got":""}"><b>${a.got?"✓":"·"}</b><span><strong>${esc(t)}</strong><small>${esc(typeof d==="function"?d(CFG.goal):d)}</small></span></div>`}).join("")}</div>`:`<p class="hint">${L2("noYou")}</p>`;
  return `<article class="nl">
    <div class="nl-mast">${mono7("GA")}<b>${L2("mast")}</b><span class="mono">${esc(L2("issue")(rec.run,rec.days,rec.stats.convs,rec.stats.ideas))}</span></div>
    <h2 class="nl-head">${withHandles(rec,N.headline)}</h2><p class="nl-lede">${withHandles(rec,N.lede)}</p>${N.template?`<p class="hint">${L2("templNote")}</p>`:""}
    <div class="nl-grid"><section>
      <h3 class="nl-h">${L2("storiesH")}</h3>${stories||`<p class="hint">${L2("noIdeas")}</p>`}
      ${insights?`<h3 class="nl-h">${L2("insightsH")}</h3><ul class="nl-ins">${insights}</ul>`:""}
    </section><section class="nl-side">
      <h3 class="nl-h">${L2("columnH")}</h3><div class="nl-col"><b>${withHandles(rec,N.column_title)}</b><p>${withHandles(rec,N.column)}</p></div>
      <h3 class="nl-h">${L2("yourConvsH")}</h3>${yourConvs}
      <h3 class="nl-h">${L2("achH")}</h3>${badges}
      <h3 class="nl-h">${L2("memH")}</h3><p class="hint">${L2("memLine")(rec.convs.filter(c=>c.insight).length,EPISODES.length)}</p>
    </section></div></article>`;
}
/* the chart page from visual-summary/, embedded: it reads this function from its parent (same origin) */
window.placelabRunData=()=>REPORT.viewing?REPORT.viewing.chart:null;
function loadChart(rec){
  const f=$("rep-frame");if(!f||!rec)return;const key=rec.id||rec.created;if(f.dataset.key===key)return;f.dataset.key=key;
  if(typeof ARCS_HTML!=="undefined")f.srcdoc=ARCS_HTML;else if(f.getAttribute("src"))f.contentWindow.location.reload();else f.src=f.dataset.src;
}
$("rep-frame").addEventListener("load",()=>{const f=$("rep-frame");try{const d=f.contentDocument;
  if(!d.getElementById("chart")){f.dataset.missing="1";$("rep-arcs-wait").textContent=L2("chartMissing");$("rep-arcs-wait").hidden=false;f.style.height="0px";return}
  delete f.dataset.missing;$("rep-arcs-wait").hidden=true;const fit=()=>{f.style.height=Math.ceil(d.body.getBoundingClientRect().height)+8+"px"};fit();new ResizeObserver(fit).observe(d.body)}catch(e){}});
async function loadRunList(){if(REPORT.list||!LLM.server)return;try{REPORT.list=(await api("/api/runs")).runs||[]}catch(e){REPORT.list=[]}renderReport()}
function renderReport(){
  if(!$("rep-news"))return;
  const live=!REPORT.current,rec=REPORT.viewing||REPORT.current;
  $("t-replab").textContent=L2("repLab");
  $("rep-title").textContent=rec?L2("repTitle")(rec.run,rec.days):`${L2("repTitle")(runNo,CFG.days)} · ${L2("repLive")}`;
  const runs=(REPORT.list||[]).filter(r=>!REPORT.current||r.id!==REPORT.current.id);
  $("rep-runs").innerHTML=`<option value="">${REPORT.current?L2("thisRun"):L2("repLive")}</option>`+runs.slice().reverse().map(r=>`<option value="${esc(r.id)}"${REPORT.viewing&&REPORT.viewing.id===r.id&&REPORT.viewing!==REPORT.current?" selected":""}>${L2("pastRun")(r.n)} · ${esc((r.created||"").slice(0,16).replace("T"," "))}</option>`).join("");
  $("rep-runs").hidden=!runs.length;$("t-reppick").hidden=!runs.length;
  ["news","arcs","detail"].forEach(k=>{$("rt-"+k).setAttribute("aria-selected",REPORT.tab===k);$("rp-"+k).hidden=REPORT.tab!==k});
  [["rt-news","tabNews"],["rt-arcs","tabArcs"],["rt-detail","tabDetail"],["t-again","again"],["t-forget","forget"],["t-reppick","pickRun"],["t-arcsnote","arcsNote"]].forEach(([id,k])=>$(id).textContent=L2(k));
  const pastView=rec&&rec!==REPORT.current;$("rt-detail").hidden=!!pastView;if(pastView&&REPORT.tab==="detail")REPORT.tab="news";
  if(!rec){$("rep-news").innerHTML=`<p class="hint">${L2("repRunning")}</p>`;$("rep-arcs-body").hidden=true;$("rep-arcs-wait").textContent=L2("repRunning");$("rep-arcs-wait").hidden=false}
  else{$("rep-news").innerHTML=REPORT.writing&&rec===REPORT.current?`<p class="hint">${L2("writing")}</p>`:newsletterHTML(rec);$("rep-arcs-body").hidden=false;const miss=$("rep-frame").dataset.missing;$("rep-arcs-wait").hidden=!miss;if(miss)$("rep-arcs-wait").textContent=L2("chartMissing");if(REPORT.tab==="arcs")loadChart(rec)}
  loadRunList();
}
["news","arcs","detail"].forEach(k=>$("rt-"+k).addEventListener("click",()=>{REPORT.tab=k;renderReport();if(k==="detail")renderResults()}));
$("rep-runs").addEventListener("change",async e=>{const id=e.target.value;
  if(!id){REPORT.viewing=REPORT.current;renderReport();return}
  try{REPORT.viewing=await api("/api/runs/"+id);renderReport()}catch(err){console.warn(err)}});
$("rep-again").addEventListener("click",()=>{
  const last=REPORT.current;if(last&&last.id)runNo=+last.id.slice(4)+1;else runNo++;
  REPORT.current=REPORT.viewing=null;REPORT.list=null;CFG.days=+$("days").value;running=true;init();renderAll();renderYouCard();showNav("sim");if(userAgent)setFollow(true)});
$("rep-forget").addEventListener("click",async()=>{if(!confirm(L2("forgetQ")))return;await forgetEpisodes();$("rep-msg").textContent=L2("forgotten");if(REPORT.viewing)renderReport()});
