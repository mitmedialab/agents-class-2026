/* =====================================================================
   SIMULACIÓN · clase 341: cuerpo, movimiento por los espacios comunes, ideas que nacen al hablar
   ===================================================================== */
let agents=[],running=true,meets=0,bins=[0],selAgent=null,convs=[],dirtyMem=true,dirtyConv=true,userAgent=null,finished=false;
const CFG={days:3,user:null,goal:3}; // objetivo: hablar con 3 personas distintas antes de que acabe la simulación
const talkedWith=()=>{if(!userAgent)return [];const set=new Map();for(const c of CLOG){if(!c.mine)continue;const o=c.a===userAgent?c.b:c.a;if(!set.has(o.id))set.set(o.id,{a:o,first:c.clk,n:0});set.get(o.id).n++}return [...set.values()]};
const ADOPT=[],DIFF=[],PRES={},CLOG=[];
function randIn(id,m=3){const[x1,y1,x2,y2]=ZONES[id].r;for(let k=0;k<40;k++){const px=rnd(x1+m,x2-m),py=rnd(y1+m,y2-m);if(walkable(px,py))return W(px,py)}const [px,py]=nearestWalkable((x1+x2)/2,(y1+y2)/2);return W(px,py)}
const cafeWait=()=>{const[x1,y1,x2,y2]=ZONES.cafe.r;return W(rnd(x1+5,x2-5),rnd(y1+9,y2-9))};
function nodeOfPoint(p){return {door:p,b:p.x<.8?"E15":"E14",final:p}}
function nodeOfZone(id){const z=ZONES[id];return {door:W(...z.door),b:z.b,final:id==="cafe"?cafeWait():randIn(id)}}
function routeTo(a,toNode){const p=findPath(a.x,a.z,toNode.final.x,toNode.final.z);if(p)a.path=p;else{const A=a.node,pts=[A.door,W(...HUB[A.b])];if(A.b!==toNode.b)pts.push(W(...HUB[toNode.b]));pts.push(toNode.door,toNode.final);a.path=pts}a.state="walk";a.nextNode=toNode}
function goZone(a,id){a.dest=id;routeTo(a,nodeOfZone(id))}
function goPoint(a,p,dest){a.dest=dest;routeTo(a,nodeOfPoint(p))}
function setAct(a,pred,obj){const s=a.scratch;s.act_event=[who(a),pred,obj,`${who(a)} ${pred} ${obj}`];s.act_description=`${pred} ${obj}`}
const TEAMS=(()=>{const m=new Map();for(const p of PROFILES){if(!m.has(p.team))m.set(p.team,{n:p.team,size:0});m.get(p.team).size++}return [...m.values()]})();
Object.defineProperty(window,"POP",{get:()=>PROFILES.length}); // la clase puede crecer con «añadirme»

/* ---------- ideas: nacer, apuntarse, recordar ---------- */
function bornMemory(a,other,idea){
  if(idea.node&&idea.node[a.id])return;idea.node=idea.node||{};
  const t=`Idea con ${who(other)}: ${qt(idea.title)} (nació en ${SP[idea.born.place].n}).`;
  const node=a.a_mem.add_thought(simT,null,who(a),"piensa",qt(idea.title),t,[who(a),qt(idea.title),who(other)],8,[t,LLM_embedding(t)],[]);
  idea.node[a.id]=node.node_id;if(!a.ideas.includes(idea))a.ideas.push(idea);
  own_event(a,"tiene una idea con",who(other),`${who(a)} tiene una idea con ${who(other)}: ${qt(idea.title)}`);
  ADOPT.push({t:simT,day,clk:clock(),who:a,idea,from:other,kind:"born"});
  proposals.stamp(idea.born.x,idea.born.z,.45,28);ghost(idea.born.x,idea.born.z);dirtyMem=true;
}
function joinIdea(a,idea,from){
  if(idea.members.has(a))return;idea.members.add(a);idea.node=idea.node||{};
  const t=`Me apunté a la idea ${qt(idea.title)} con ${who(from)}.`;
  const node=a.a_mem.add_thought(simT,null,who(a),"piensa",qt(idea.title),t,[who(a),qt(idea.title),who(from)],8,[t,LLM_embedding(t)],[]);
  idea.node[a.id]=node.node_id;a.ideas.push(idea);
  own_event(a,"se apunta a la idea",qt(idea.title),`${who(a)} se apunta a la idea ${qt(idea.title)}`);
  ADOPT.push({t:simT,day,clk:clock(),who:a,idea,from,kind:"join"});
  const c=spc3(spaceOf(a.x,a.z)||"cafe");proposals.stamp(c.x,c.z,.35,24);ghost(c.x,c.z);dirtyMem=true;
}
function evolveIdea(idea,evo,by,to){
  const n=idea.versions.length+1,place=spaceOf(by.x,by.z)||"cafe";
  const v={n,kind:evo.kind,t:simT,clk:clock(),place,by:[by,to],part:evo.part||null,who:evo.who||null,evidence:evo.evidence||[],text:evo.kind==="llm"?evo.text:evo.kind==="referral"?`buscar a ${who(evo.who)} (${evo.part})`:evo.kind==="place"?`probarla en ${SP[evo.place].n}`:`añadir ${evo.part}`};
  if(evo.kind==="place")v.place=evo.place;idea.versions.push(v);
  if(evo.kind==="referral")idea.wanted.set(evo.who.id,{by,part:evo.part});
  if(evo.kind==="part")idea.tags.push(evo.part);
  const t=evo.kind==="llm"?`La idea ${qt(ideaTitle(idea))}, versión ${n} con ${who(to)}: ${v.text}`:`La idea ${qt(idea.title)} ahora pasa por ${v.text} (versión ${n}, lo propuso ${who(by)}).`;
  for(const p of [by,to]){const node=p.a_mem.add_thought(simT,null,who(p),"piensa",qt(idea.title),t,[who(p),qt(idea.title)],8,[t,LLM_embedding(t)],evo.evidence||[]);if(p===by)v.node=node.node_id}
  ADOPT.push({t:simT,day,clk:clock(),who:by,idea,from:to,kind:"evo"});
  const c=spc3(place);proposals.stamp(c.x,c.z,.3,22);dirtyMem=true;
}
function knowSpace(a,id,n=2){const fs=[...FACTS[id]].sort(()=>Math.random()-.5).slice(0,n);for(const f of fs){const d=`${SP[id].n} ${f}`;const s=a.scratch,poig=LLM_poignancy_event(d);a.a_mem.add_event(simT,null,SP[id].n,f,"",d,[SP[id].n],poig,[d,LLM_embedding(d)],[]);s.importance_trigger_curr-=poig;s.importance_ele_n+=1}dirtyMem=true}

/* ---------- población: los alumnos de la 341 ---------- */
function makeAgent(i,pf,label,isUser){
  const home="nagashima",p=randIn(home),tex=isUser&&CFG.user&&CFG.user.avatar?spriteFrom(CFG.user.avatar):pf.avatar?spriteFrom(pf.avatar):spriteSet(i);
  const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:tex[0],transparent:true,depthWrite:false}));sp.scale.set(.7,1.05,1);scene.add(sp);
  const sh=new THREE.Mesh(shadowGeo,shadowMat);sh.scale.setScalar(.7);sh.rotation.x=-Math.PI/2;sh.position.y=.012;scene.add(sh);
  const bub=new THREE.Sprite(new THREE.SpriteMaterial({map:bubbleTex,transparent:true,depthWrite:false}));bub.scale.set(.65,.5,1);bub.visible=false;scene.add(bub);
  const sub=document.createElement("div");sub.className="sub";sub.hidden=true;$("subs").appendChild(sub);
  const active=!!isUser||pf.active!==false;
  if(!active){sp.material.color.setHex(0x8C95A2);sp.material.opacity=.75;sh.material=sh.material.clone();sh.material.opacity=.15}
  const a={id:i,label,pf,active,group:pf.team,home,user:!!isUser,x:p.x,z:p.z,sp,sh,bub,sub,tex,node:nodeOfZone(home),dest:home,path:[],state:"work",timer:rnd(.5,8),seen:new Set(),last:{},percT:rnd(0,2),conv:null,onFloor:true,
    a_mem:new AssociativeMemory(),scratch:new Scratch(),s_mem:new Set(),reflections:[],heard:{},heardCount:{},persuadable:rnd(.7,1.3),ideas:[]};
  setAct(a,"está en clase en",SP.r341.n);
  const t=`Mi proyecto va de ${pf.project}; lo mío es ${pf.skills.join(" y ")}; me interesa ${pf.interests.join(" y ")}.`;
  const node=a.a_mem.add_thought(simT,null,who(a),"piensa","el proyecto",t,[who(a),"el proyecto"],6,[t,LLM_embedding(t)],[]);a.projNode=node.node_id;
  nextOuting(a);a.timer*=Math.random();knowSpace(a,"r341",2);
  if(!active){a.state="idle";a.timer=1e9;setAct(a,"está en clase en",SP.r341.n)}
  return a;
}
const profileFor=code=>{const p=PROFILES.find(p=>p.code===code);if(!p)return null;const u=CFG.user&&CFG.user.code===code?CFG.user.over||{}:{};return {...p,...u}};
function init(){
  agents.forEach(a=>{scene.remove(a.sp);scene.remove(a.sh);scene.remove(a.bub);a.sub.remove()});
  pulses.splice(0).forEach(p=>scene.remove(p.m));arcs.splice(0).forEach(p=>scene.remove(p.m));ghosts.splice(0).forEach(p=>scene.remove(p.m));
  stampN=0;stampGeo.setDrawRange(0,0);presenceHeat.clear();proposals.clear();
  simT=0;day=1;dayStart=0;finished=false;meets=0;bins=[0];selAgent=null;ADOPT.length=0;DIFF.length=0;IDEAS.length=0;ideaN=0;CLOG.length=0;for(const k in PRES)delete PRES[k];convs=[];dirtyMem=dirtyConv=true;
  LLM.token++;LLM.pending=0;if(typeof REPORT!=="undefined")REPORT.current=null; // answers still in flight belong to the previous run
  const used=new Set();agents=[];userAgent=null;
  PROFILES.forEach((p0,i)=>{
    const isUser=!!(CFG.user&&CFG.user.code===p0.code),pf=profileFor(p0.code),av=isUser&&CFG.user.avatar?CFG.user.avatar:p0.avatar||avatarIdx(i);
    let label=`la de camiseta ${SHIRTN[av.t%SHIRTN.length]} y ${HAIRN[av.h%HAIRN.length]}`;
    if(used.has(label))label+=` con ${PANTSN[av.p%PANTSN.length]}`;used.add(label);
    const a=makeAgent(i,pf,label,isUser);if(isUser)userAgent=a;agents.push(a)});
  seedEpisodes();
}
const presence=()=>1;
const hourNow=()=>(540+(simT-dayStart)/3)/60%24;
function cafeMult(){const h=hourNow();return (h>=10.4&&h<11)||(h>=12.3&&h<13.5)||(h>=15.4&&h<16)?4:1}
const expo=mean=>-Math.log(1-Math.random())*mean;
// salidas de clase: a la cafetería, al foodcam, al atrio o a dar una vuelta por los pasillos; tu personaje sale más a menudo
const activeN=()=>agents.filter(x=>x.active).length||1;
// con pocas personas activas, salen más a menudo y se quedan más rato, para que lleguen a cruzarse
function nextOuting(a){const k=Math.max(.3,Math.min(1,activeN()/12));a.timer=(a.user?rnd(120,300):expo(400))*k/cafeMult();const r=Math.random();a.outing=r<.5?"cafe":r<.68?"foodcam":r<.82?"atrium":"corr:"+pick(["pasaje","alanorte","swatchc","btc","sur"])}
let presT=0;

function discuss(a,b){
  arc(a,b,0xFF4F12);
  a.scratch.chatting_with=who(b);b.scratch.chatting_with=who(a);
  setAct(a,"conversa con",who(b));setAct(b,"conversa con",who(a));
  const place=spaceOf(a.x,a.z)||"cafe";
  // talk.js: Gemini writes it, or offline.js when there is no model; the older templates are the last resort
  try{const c0=convs[0],dur=startModelTalk(a,b,place);a.conv=b.conv=convs[0];return dur}
  catch(err){console.warn("conversation rules failed, using the templates:",err);if(convs[0]&&convs[0].pending&&convs[0].a===a)convs.shift();return templateTalk(a,b,place)}
}
/* the original template conversation (agents.js LLM_utterance): kept as a last resort */
function templateTalk(a,b,place){
  const {chat,ctx}=agent_chat_v2(a,b);
  const lines=chat.map(([w,t,spk,evidence,res])=>({w:spk,t,evidence,pitch:res.pitch||null,born:res.born||null,adopt:res.adopt||null,agree:!!res.agree,evo:res.evo||null}));
  for(const l of lines){if(!l.pitch||l.pitch.kind!=="idea")continue;const S=l.w,Lst=S===a?b:a,I=l.pitch.idea,src=S.heard[I.id]&&S.heard[I.id].t<simT?S.heard[I.id]:null;
    DIFF.push({t:simT,clk:clock(),key:I.id,idea:I,from:S,to:Lst,text:l.t,second:!!src,src:src?src.from:null,adopted:lines.some(x=>x.adopt&&x.adopt.idea===I&&x.w===Lst)});
    I.mentions++;Lst.heardCount[I.id]=(Lst.heardCount[I.id]||0)+1;if(!Lst.heard[I.id])Lst.heard[I.id]={from:S,t:simT,clk:clock(),text:l.t}}
  const c={clk:clock(),place,a,b,lines,start:simT,shown:0,born:ctx.born,adopt:ctx.adopt,agree:ctx.agree,evo:ctx.evo};convs.unshift(c);if(convs.length>80)convs.pop();dirtyConv=true;
  CLOG.push({t:simT,day,clk:clock(),place,out:ctx.born.length?"born":ctx.evo.length?"evo":ctx.adopt.length?"join":ctx.agree?"agr":"none",mine:a.user||b.user,a,b,idea:ctx.born[0]||(ctx.evo[0]&&ctx.evo[0].idea)||(ctx.adopt[0]&&ctx.adopt[0].idea)||null,lines});
  a.conv=b.conv=c;a.scratch.chat=chat;b.scratch.chat=chat;
  [[a,b],[b,a]].forEach(([p,o])=>{
    const op=ctx.props[o.id],born=ctx.born[0],join=ctx.adopt.find(x=>x.who===p),theirs=ctx.adopt.find(x=>x.who===o);
    const d=`Hablé con ${who(o)} en ${SP[place].n}${op&&op.kind==="project"?`; anda con ${o.pf.project}`:op&&op.kind==="idea"?`; está con la idea ${qt(op.idea.title)}`:""}${born?` y nos salió ${qt(born.title)}`:join?` y me apunté a ${qt(join.idea.title)}`:theirs?` y se apuntó a ${qt(theirs.idea.title)}`:ctx.agree?` y estamos en lo mismo`:""}.`;
    const node=p.a_mem.add_chat(simT,null,who(p),"chat with",who(o),d,[who(p),who(o),...(born?[qt(born.title)]:[])],LLM_poignancy_chat(ctx),[d,LLM_embedding(d)],chat.map(([w,t])=>[w,t]));
    p.scratch.importance_trigger_curr-=node.poignancy;p.scratch.importance_ele_n+=1;
    p.a_mem.add_event(simT,null,who(p),"conversa con",who(o),`${who(p)} conversa con ${who(o)}`,[who(p),who(o)],3,[`${who(p)} conversa con ${who(o)}`,LLM_embedding(`${who(p)} conversa con ${who(o)}`)],[node.node_id]);
    reflect_on_convo(p,o,node,{adopt:ctx.adopt,props:ctx.props,agree:ctx.agree,born:ctx.born,evo:ctx.evo});
  });
  return lines.length*LINE_T+1;
}
/* which line is being said: fixed LINE_T per template line; model lines get time to be read (talk.js sets c.ends) */
function lineAt(c){const t=simT-c.start;if(!c.ends)return Math.floor(t/LINE_T);let i=0;while(i<c.ends.length&&c.ends[i]<=t)i++;return i}
function onLine(c,l){if(l.pitch&&l.pitch.kind==="idea"){const sp=spc3(c.place);proposals.stamp(sp.x,sp.z,.15,16)}}
/* ---------- encuentros, como en Generative Agents: percibir → decidir si hablar → conversar ----------
   perceive.py: cada 2 s el personaje ve a quien tiene a ≤ vision_r (4). Si ve a alguien disponible en un espacio común,
   decide si hablarle (generate_decide_to_talk) a partir de lo que recupera sobre esa persona: si ya han hablado hoy,
   qué sabe de ella, su relación. Si decide que sí, los dos se paran y empieza agent_chat_v2. */
const AVAIL=new Set(["walk","wait","visit"]);
function LLM_decide_to_talk(a,b){
  if(simT-(a.last["c"+b.id]??-99)<40)return false;                 // acaban de hablar
  const R=new_retrieve(a,[who(b)],10)[who(b)].nodes;                // lo que recuerda de b
  const chats=R.filter(n=>n.type==="chat").length,knows=R.some(n=>/ anda con | sabe de | está con la idea /.test(n.description));
  let p=.35+(chats===0?.35:0)+(knows?.15:0)+(a.user||b.user?.15:0)-Math.min(.3,chats*.08);
  if(a.state==="wait"&&b.state==="wait")p+=.3;                      // los dos están parados en la cafetería o el atrio
  return Math.random()<p;
}
function maybeTalk(a){
  if(!AVAIL.has(a.state)||a.state==="work")return;const here=spaceOf(a.x,a.z);if(!here||here==="r341")return;
  for(const b of agents){if(b===a||!b.active||!b.onFloor||!AVAIL.has(b.state))continue;
    if(Math.hypot(a.x-b.x,a.z-b.z)>a.scratch.vision_r||spaceOf(b.x,b.z)!==here)continue;
    if(!LLM_decide_to_talk(a,b)){a.last["c"+b.id]=Math.max(a.last["c"+b.id]??-99,simT-30);continue}  // no por ahora: no insistir en 10 s
    a.last["c"+b.id]=b.last["c"+a.id]=simT;const [A,B]=b.user?[b,a]:[a,b];const dur=discuss(A,B);
    [a,b].forEach(p=>{p.waitLeft=p.state==="wait"?Math.max(0,p.timer-dur*.5):0;p.path=[];p.state="talk";p.timer=dur;p.scratch.chatting_end_time=simT+dur});
    return}
}
function encounter(a,b){
  const k=Math.min(a.id,b.id)+"-"+Math.max(a.id,b.id);if(simT-(a.last[k]??-99)<60)return;a.last[k]=b.last[k]=simT;
  const mx=(a.x+b.x)/2,mz=(a.z+b.z)/2,pl=placeOf(mx,mz);
  meets++;bins[bins.length-1]++;stamp(mx,mz);arc(a,b,0xFF4F12);
  [[a,b],[b,a]].forEach(([p,o])=>{p.state="chat";p.timer=2.2;setAct(p,"conversa con",who(o))});
}
function endDay(){
  day++;dayStart=simT;
  if(day>CFG.days){finished=true;running=false;onFinish();return}
  for(const a of agents){a.conv=null;a.scratch.chatting_with=null;a.scratch.chat=null;a.sub.hidden=true;a.bub.visible=false;const p=randIn("nagashima");a.x=p.x;a.z=p.z;a.node=nodeOfZone("nagashima");a.path=[];a.state=a.active?"work":"idle";nextOuting(a);a.timer=a.active?a.timer*Math.random():1e9;setAct(a,"está en clase en",SP.r341.n)}
  convs.forEach(c=>c.shown=c.lines.length);dirtyConv=true;
}
function update(dt){
  // while agents wait for the model, a fast-forward or the end of the day waits too, so no answer is lost
  if(LLM.pending&&(ffUntil!==null||simT-dayStart+dt>=DAY_LEN))return;
  simT+=dt;if(Math.floor(simT/12)>=bins.length){bins.push(0);if(bins.length>60)bins.shift()}
  if(simT-dayStart>=DAY_LEN){endDay();if(finished)return}
  for(const a of agents){
    if(!a.onFloor){a.timer-=dt;continue}
    presenceHeat.stamp(a.x,a.z,(inZone("cafe",a.x,a.z)?.12:.05)*dt);
    const here=placeOf(a.x,a.z);if(here!=="un laboratorio"&&!inLab(a.x,a.z))PRES[here]=(PRES[here]||0)+dt;
    a.percT-=dt;if(a.percT<=0){a.percT=2;perceive(a);reflect(a);if(a.active)maybeTalk(a)}
    if(a.state==="walk"){
      setAct(a,"camina por",here);
      const t=a.path[0];if(!t){a.node=a.nextNode;arrive(a);continue}
      const dx=t.x-a.x,dz=t.z-a.z,d=Math.hypot(dx,dz),sp=2.6*dt;
      if(d<=sp){a.x=t.x;a.z=t.z;a.path.shift()}else{a.x+=dx/d*sp;a.z+=dz/d*sp}
    }else if(a.state==="chat"){a.timer-=dt;if(a.timer<=0)a.state="walk"}
    else if(a.state==="wait"){a.timer-=dt;if(a.timer<=0)leave(a)}
    else if(a.state==="talk"){a.timer-=dt;if(a.timer<=0){if(a.waitLeft>4){a.state="wait";a.timer=a.waitLeft;a.waitLeft=0;a.conv=null;a.scratch.chatting_with=null;a.scratch.chat=null;setAct(a,"está en",SP[spaceOf(a.x,a.z)||"cafe"].n)}else leave(a)}}
    else if(a.state==="visit"){a.timer-=dt;if(a.timer<=0)goZone(a,a.home)}
    else if(a.state==="work"){a.timer-=dt;if(a.timer<=0){a.seen.clear();goOut(a)}}
  }
  for(const c of convs){if(c.shown>=c.lines.length)continue;const k=Math.min(c.lines.length,lineAt(c)+1);
    while(c.shown<k){onLine(c,c.lines[c.shown]);c.shown++;dirtyConv=true}}
  const on=agents.filter(a=>a.onFloor);
  for(let i=0;i<on.length;i++)for(let j=i+1;j<on.length;j++){const a=on[i],b=on[j];
    if(Math.hypot(a.x-b.x,a.z-b.z)<1.3&&!inZone("cafe",a.x,a.z)&&!inLab(a.x,a.z)&&(a.state==="walk"||a.state==="visit")&&(b.state==="walk"||b.state==="visit")&&(a.state==="visit"||b.state==="visit"||Math.random()<.02))encounter(a,b)}
}
function arrive(a){
  if(typeof a.dest==="string"&&a.dest.startsWith("corr:")){const id=a.dest.slice(5);a.state="visit";a.timer=rnd(8,18);setAct(a,"está en",SP[id].n);own_event(a,"va a ver",SP[id].n,`${who(a)} va a ver ${SP[id].n}`);knowSpace(a,id,2);return}
  if(a.dest==="atrium"||a.dest==="foodcam"){const k=Math.max(1,Math.min(2.2,12/activeN()));a.state="wait";a.timer=(a.dest==="foodcam"?rnd(8,14):rnd(15,30))*k;setAct(a,"está en",ZONES[a.dest].n);if(!a.s_mem.has(SP[a.dest].n))knowSpace(a,a.dest,2);return}
  if(a.dest==="cafe"){const k=Math.max(1,Math.min(2.2,12/activeN()));a.state="wait";a.timer=(a.user?rnd(25,45):rnd(22,42))*k;setAct(a,"está en","la cafetería");if(!a.s_mem.has("la cafetería"))knowSpace(a,"cafe",2);return}
  if(a.dest==="exit"){own_event(a,"sale de","la planta",`${who(a)} sale de la planta por el ascensor`);setAway(a);return}
  a.state="work";nextOuting(a);setAct(a,"está en clase en",SP.r341.n);
}
function leave(a){a.conv=null;a.scratch.chatting_with=null;a.scratch.chat=null;goZone(a,a.home)}
function goOut(a){const o=a.outing||"cafe";if(o.startsWith("corr:")){const id=o.slice(5);goPoint(a,spotOf(id),o)}else goZone(a,o)}
/* ---------- avance rápido ---------- */
let ffUntil=null;
function fastForward(toEndOfRun){
  ffUntil=toEndOfRun?Infinity:dayStart+DAY_LEN;$("ff-bar").hidden=false;running=true;
  const step=()=>{
    if(finished||ffUntil===null||simT>=ffUntil){ffUntil=null;$("ff-bar").hidden=true;renderAll();return}
    const t0=performance.now();while(performance.now()-t0<28&&!finished&&simT<ffUntil){update(0.1);evidTick(0.1)}
    const total=CFG.days*DAY_LEN,pct=Math.min(100,100*simT/total);$("ff-fill").style.width=pct+"%";$("ff-txt").textContent=`${L("ffRun")} · ${clock()}${LLM.pending?` · ${L2("ffThinking")}…`:""}`;
    requestAnimationFrame(step)};
  requestAnimationFrame(step);
}

/* ---------- interacción ---------- */
const ray=new THREE.Raycaster(),mouse=new THREE.Vector2();let downAt=null;
renderer.domElement.addEventListener("pointerdown",e=>downAt=[e.clientX,e.clientY]);
renderer.domElement.addEventListener("pointerup",e=>{
  if(!downAt||Math.hypot(e.clientX-downAt[0],e.clientY-downAt[1])>6)return;downAt=null;
  const r=renderer.domElement.getBoundingClientRect();mouse.set((e.clientX-r.left)/r.width*2-1,-((e.clientY-r.top)/r.height)*2+1);ray.setFromCamera(mouse,camera);
  const hs=ray.intersectObjects(agents.filter(a=>a.onFloor).map(a=>a.sp))[0];
  if(hs){selAgent=agents.find(a=>a.sp===hs.object);hiIds=[];dirtyMem=true;showTab("mem")}
});

/* ---------- monogramas 7×7 y equipos ---------- */
const PIX={A:["010","101","111","101","101"],B:["110","101","110","101","110"],C:["011","100","100","100","011"],D:["110","101","101","101","110"],E:["111","100","110","100","111"],F:["111","100","110","100","100"],G:["011","100","101","101","011"],H:["101","101","111","101","101"],I:["111","010","010","010","111"],L:["100","100","100","100","111"],M:["101","111","111","101","101"],O:["010","101","101","101","010"],P:["110","101","110","100","100"],S:["011","100","010","001","110"],T:["111","010","010","010","010"],V:["101","101","101","101","010"]};
function mono7(two,cls=""){const g=[];for(let r=0;r<7;r++)for(let c=0;c<7;c++){let on=false;if(r>=1&&r<=5){const i=c<3?0:c>3?1:-1;if(i>=0){const ch=PIX[two[i]];if(ch)on=ch[r-1][c-(i?4:0)]==="1"}}g.push(`<i class="${on?"on":""}"></i>`)}return `<span class="mono7 ${cls}" aria-hidden="true">${g.join("")}</span>`}
const GI=Object.fromEntries(TEAMS.map((t,i)=>[t.n,"E"+(i+1)]));
$("band-glyph").innerHTML=mono7("GA");
function renderGroups(){$("groups").innerHTML=TEAMS.map(g=>{const m=agents.filter(a=>a.group===g.n);return `<span>${mono7(GI[g.n]||"EQ","dark")}${g.n}<b>${m.filter(a=>a.onFloor).length}/${g.size}</b></span>`}).join("")}

/* ---------- cuaderno ---------- */
const face=a=>`<img class="face${a.user?" you":""}" alt="" data-a="${a.id}" src="${a.tex[0].url}" title="${esc(tr(who(a)))}${a.pf&&a.pf.name?" · "+esc(a.pf.name):""}${a.user?" · "+L("you"):""}">`;
const youTag=a=>a.user?` <span class="youtag">${L("you")}</span>`:"";
let convUid=0;
function renderConvs(){
  // one card per conversation: who and what each brought, the talk as bubbles (yours on the right), then the insight and idea.
  // the newest and any live one are open; older ones fold to their insight, and the reader can open or fold any card.
  const shortName=a=>a.user?L("you"):a.pf.name?a.pf.name.split(/\s+/)[0]:tr(who(a));
  $("convs").innerHTML=convs.map((c,k)=>{c.uid=c.uid||++convUid;
    const live=c.pending||c.shown<c.lines.length,open=c.open??(live||k===0),right=c.b.user?c.b:c.a.user?c.a:c.b,done=!c.pending&&c.shown>=c.lines.length;
    const idea=c.born[0]||(c.evo&&c.evo[0]&&c.evo[0].idea)||(c.adopt[0]&&c.adopt[0].idea)||null;
    const tag=c.born.length?L("bornTag"):c.evo&&c.evo.length?`${L("evoTag")} ${c.evo[0].idea.versions.length}`:c.adopt.length?L("joinTag"):c.agree?L("agree"):"";
    const person=(a,t)=>`<div class="cv-p">${face(a)}<span><b>${esc(shortName(a))}</b>${t?`<small>${L2("brings")} ${esc(t)}</small>`:""}</span></div>`;
    const bubble=l=>`<div class="cv-l${l.w===right?" r":""}">${face(l.w)}<p>${esc(lineText(l))}${l.evidence&&l.evidence.length?` <button class="ev" data-a="${l.w.id}" data-ids="${l.evidence.join(",")}" title="${L("evTitle")}">${l.evidence.join(" ")}</button>`:""}</p></div>`;
    return `<div class="conv${live?" talking":""}${c.a.user||c.b.user?" mine":""}">
    <div class="cv-head"><b>${c.clk}</b><span>${esc(placeName(c.place))}</span>${tag?`<span class="ok">${tag}</span>`:""}${c.followup?`<span>${L2("followup")}</span>`:""}</div>
    <div class="cv-who">${person(c.a,c.topics&&c.topics.a)}${person(c.b,c.topics&&c.topics.b)}</div>
    ${c.pending?`<div class="cv-l thinking"><span class="pair">${face(c.a)}${face(c.b)}</span><p>${L2("thinking")}</p></div>`:""}
    ${open&&c.lines.length?`<div class="cv-talk">${c.lines.slice(0,c.shown).map(bubble).join("")}${c.shown<c.lines.length?`<div class="cv-l${c.lines[c.shown].w===right?" r":""}">${face(c.lines[c.shown].w)}<p class="dots">…</p></div>`:""}</div>`:""}
    ${done&&c.insight?`<div class="cv-ins${open?"":" clamp"}"><b>${L2("insight")}</b>${esc(c.insight)}</div>`:""}
    ${done&&idea?`<div class="cv-idea"><b>«${esc(ideaTitle(idea))}»</b>${open&&idea.llm&&idea.llm.pitch?`<span>${esc(idea.llm.pitch)}</span>`:""}</div>`:""}
    ${done&&c.lines.length?`<button type="button" class="cv-more" data-u="${c.uid}">${open?L2("hideTalk"):L2("showTalk")(c.lines.length)}</button>`:""}</div>`}).join("")||`<p class="hint">${L("noConvs")}</p>`;
}
let hiIds=[];
$("convs").addEventListener("click",e=>{const m=e.target.closest(".cv-more");if(m){const c=convs.find(x=>x.uid===+m.dataset.u);if(c){c.open=!(c.open??convs[0]===c);renderConvs()}return}
  const f=e.target.closest(".face,.ev");if(!f)return;selAgent=agents[+f.dataset.a];hiIds=f.dataset.ids?f.dataset.ids.split(","):[];dirtyMem=true;showTab("mem")});
const CHIP={event:"event",thought:"thought",chat:"chat"};
const pfLine=a=>`${L("pfProj")}: <b>${esc(a.pf.project)}</b> · ${L("pfSkills")}: ${esc(a.pf.skills.join(", "))} · ${L("pfInt")}: ${esc(a.pf.interests.join(", "))}`;
function renderMem(target){
  const a=target||selAgent;
  if(!a){$("p-mem").innerHTML=`<p class="hint">${L("memHint")}</p>`;return}
  const m=a.a_mem,s=a.scratch,nodes=[...m.seq_event,...m.seq_thought,...m.seq_chat].sort((x,y)=>y.node_count-x.node_count).slice(0,80);
  const pct=Math.max(0,Math.min(100,100*(1-s.importance_trigger_curr/s.importance_trigger_max)));
  const refl=a.reflections[0],STATE=L("STATE");
  const html=`<div class="who"><img alt="" src="${a.tex[0].url}"><div><div class="state">${esc(tr(who(a)))}${youTag(a)} · ${esc(tr(STATE[a.state]?STATE[a.state](a):""))}</div><div class="hint">${mono7(GI[a.group]||"EQ","dark")} ${esc(a.group)} · ${esc(a.pf.code)}${a.pf.name?" · "+esc(a.pf.name):""}</div><div class="hint">${pfLine(a)}</div>${a.ideas.length?`<div class="hint">${L("ideasNow")}: ${a.ideas.map(i=>`«${esc(ideaTitle(i))}»`).join(" · ")}</div>`:""}</div></div>
  <div class="scratch">
    <div><span>vision_r</span><b>${s.vision_r}</b></div><div><span>att_bandwidth</span><b>${s.att_bandwidth}</b></div><div><span>retention</span><b>${s.retention}</b></div>
    <div><span>event</span><b>${m.seq_event.length}</b></div><div><span>thought</span><b>${m.seq_thought.length}</b></div><div><span>chat</span><b>${m.seq_chat.length}</b></div>
    <div class="wide"><span>${L("reflIn")(Math.max(0,s.importance_trigger_curr),s.importance_trigger_max)}</span><i class="meter"><b style="width:${pct}%"></b></i></div>
    <div class="wide"><span>${L("knows")}</span><b class="soft">${[...a.s_mem].map(trp).join(" · ")||"—"}</b></div>
  </div>
  ${refl?`<div class="refl"><div class="rh">${L("lastRefl")} · ${refl.clk}</div>${refl.qs.map(q=>`<div class="q"><div class="qq">${esc(tr(q.q))}</div>${q.insights.length?q.insights.map(i=>`<div class="ins"><span class="nid">${i.id}</span> ${esc(tr(i.text))} <button class="ev" data-a="${a.id}" data-ids="${i.ev.join(",")}">${L("because")} ${i.ev.join(" ")}</button></div>`).join(""):`<div class="ins soft">${L("noEv")}</div>`}</div>`).join("")}</div>`:`<p class="hint">${L("noRefl")}</p>`}
  <div class="mem">${nodes.map(n=>`<div class="m ${n.type}${hiIds.includes(n.node_id)?" hi":""}" id="n-${a.id}-${n.node_id}"><time>${n.clk}</time><span class="chip">${CHIP[n.type]}${n.type==="thought"?" d"+n.depth:""}</span><span><span class="nid">${n.node_id}</span> ${esc(tr(n.description))}<i class="imp" style="width:${n.poignancy*4}px" title="poignancy ${n.poignancy}"></i>${n.filling&&n.filling.length&&n.type!=="chat"?` <button class="ev" data-a="${a.id}" data-ids="${n.filling.join(",")}">← ${n.filling.join(" ")}</button>`:""}${n.type==="chat"?`<div class="fill">${n.filling.map(([w,t])=>`<div><b>${esc(tr(w))}:</b> ${esc(tr(t))}</div>`).join("")}</div>`:""}</span></div>`).join("")}</div>`;
  const el=target?$("p-you"):$("p-mem");el.innerHTML=html;
  const first=hiIds[0];if(first&&!target){const n=$(`n-${a.id}-${first}`);if(n)n.scrollIntoView({block:"center"})}
}
$("p-mem").addEventListener("click",e=>{const f=e.target.closest(".ev");if(!f)return;hiIds=f.dataset.ids.split(",");dirtyMem=true;renderMem()});
function renderYou(){if(!userAgent){$("p-you").innerHTML=`<p class="hint">${L("noUser")}</p>`;return}hiIds=[];renderMem(userAgent)}
let tab="conv";
function showTab(k){tab=k;["conv","mem","you"].forEach(t=>{$("tab-"+t).setAttribute("aria-selected",t===k);$("p-"+t).hidden=t!==k});if(k==="mem")renderMem();if(k==="you")renderYou()}
["conv","mem","you"].forEach(k=>$("tab-"+k).addEventListener("click",()=>showTab(k)));

const sp=$("spark"),sctx=sp.getContext("2d");
function drawSpark(){
  const dpr=window.devicePixelRatio||1,w=sp.clientWidth,h=sp.clientHeight;if(sp.width!==w*dpr){sp.width=w*dpr;sp.height=h*dpr}
  sctx.setTransform(dpr,0,0,dpr,0,0);sctx.clearRect(0,0,w,h);
  const m=Math.max(3,...bins),n=bins.length,step=w/59;
  sctx.fillStyle="rgba(255,79,18,.15)";sctx.strokeStyle="#FF4F12";sctx.lineWidth=1.5;sctx.beginPath();
  bins.forEach((v,i)=>{const x=i*step,y=h-2-(v/m)*(h-6);i?sctx.lineTo(x,y):sctx.moveTo(x,y)});sctx.stroke();
  sctx.lineTo((n-1)*step,h);sctx.lineTo(0,h);sctx.closePath();sctx.fill();
}
const tmpV=new THREE.Vector3();
function placeSub(a){
  const c=a.conv;
  if(!c||a.state!=="talk"||!c.lines.length){a.sub.hidden=true;return}
  const k=Math.min(c.lines.length-1,lineAt(c)),l=c.lines[k];
  if(l.w!==a||camera.position.distanceTo(tmpV.set(a.x,1,a.z))>16){a.sub.hidden=true;return}
  tmpV.set(a.x,1.5,a.z).project(camera);if(tmpV.z>1){a.sub.hidden=true;return}
  const txt=lineText(l);a.sub.hidden=false;if(a.sub.textContent!==txt)a.sub.textContent=txt;
  a.sub.style.left=(tmpV.x+1)/2*vp.clientWidth+"px";a.sub.style.top=(1-tmpV.y)/2*vp.clientHeight+"px";
}
function evidTick(){}

/* ---------- esquema de la arquitectura ---------- */
function drawSchema(){
  const T=L("schema");
  const done=c=>!c.pending&&c.lines.length&&c.shown>=c.lines.length;
  const c=convs.find(c=>done(c)&&(c.a.user||c.b.user))||convs.find(c=>done(c)&&c.born.length)||convs.find(done);
  let left=`<div class="traj soft">${T.noConv}</div>`;
  if(c){
    const a=c.a,b=c.b,ln=c.lines,rows=[];
    const push=(cls,lab,txt)=>rows.push(`<div><b class="${cls}">${lab}:</b> ${esc(tr(txt))}</div>`);
    rows.push(`<div><b class="ob">${T.obs}:</b> ${esc(T.enter(tr(who(a)),tr(who(b))))}</div>`);
    if(ln[0])push("th",T.thought,ln[0].t);if(ln[1])push("ob",T.obs,`${who(b)}: ${ln[1].t}`);
    const ps=ln.filter(l=>l.pitch||l.born),pa=ps[0],pb=ps[1],ad=ln.find(l=>l.adopt),ag=ln.find(l=>l.agree);
    if(pa)push("ac",T.action,pa.t);if(pb)push("ob",T.obs,`${who(pb.w)}: ${pb.t}`);
    if(ad)push("ac",T.action,`${who(ad.w)}: ${ad.t}`);if(ag)push("ob",T.obs,`${who(ag.w)}: ${ag.t}`);
    rows.push(`<div><b class="rw">${T.reward}:</b> ${c.born.length?`${esc(T.rewardBorn(c.born[0].title))} ✓`:c.adopt.length?`${esc(T.rewardYes(tr(who(c.adopt[0].who)),c.adopt[0].idea.title))} ✓`:c.agree?esc(T.rewardAgree)+" ✓":esc(T.rewardNo)+" ✗"}</div>`);
    left=`<div class="traj">${rows.join("")}</div>`;
  }
  const ex=userAgent||(c?c.a:agents[0]);
  $("schema").innerHTML=`
    <div class="sb left"><h4>${T.left}<small>${T.leftS}</small></h4>${left}</div>
    <div class="sch-right">
      <div class="sb perc"><h4>${T.perc}<small>${T.percS}</small></h4><p>${T.percIn}</p><p><span class="tag">${T.percOut}</span></p><p>${T.percTok}</p></div>
      <div class="sb prof"><h4>${T.agent}<small>${T.agentS}</small></h4><p><b>${T.prof}${ex.user?" · "+L("you"):""}</b></p><p>${T.goal}</p><p>${T.profG}: ${esc(ex.group)} · ${esc(ex.pf.code)}<br>${pfLine(ex)}<br>${T.profS}: ${ex.ideas.length}</p></div>
      <div class="sb self"><h4>${T.self}</h4><div class="sub2"><div><b>${T.know}</b><p>${T.knowExt}</p><p>${T.knowInt}</p><p>${T.knowCtx}</p></div><div><b>${T.mem}</b><p>${T.stm}</p><p>${T.ltm}</p><p>${T.ret}</p></div></div></div>
      <div class="sb reason"><h4>${T.reason}<small>${T.reasonS}</small></h4><p><b>${T.traj}</b></p><p><span class="tag">${T.trajA}</span><span class="tag">${T.trajB}</span><span class="tag">${T.trajC}</span></p><p>${T.trajR}</p></div>
      <div class="sb evo span2"><h4>${T.evo}<small>${T.evoS}</small></h4><div class="sub2"><div><b>${T.evoMem}</b><p>${T.evoFilt}</p><p>${T.evoRefl}</p></div><div><b>${T.evoStore}</b><p>${T.evoMsg}</p><p>${T.evoAgents}</p></div></div></div>
    </div>`;
}

/* ---------- ahora mismo ---------- */
function liveAgent(){
  if(userAgent&&(userAgent.state==="talk"||userAgent.state==="wait"))return userAgent;
  if(selAgent&&selAgent.onFloor)return selAgent;
  const talking=agents.find(a=>a.onFloor&&a.state==="talk");if(talking)return talking;
  return userAgent||agents.find(a=>a.onFloor)||agents[0];
}
function drawLive(){
  const a=liveAgent();if(!a)return;const T=L("live"),m=a.a_mem,s=a.scratch;
  const row=(clk,txt,extra="")=>`<div class="lr"><time>${clk||""}</time><span>${esc(tr(txt))}${extra}</span></div>`;
  const perc=m.seq_event.slice(0,3).map(n=>row(n.clk,n.description,` <span class="nid">${n.node_id} · p${n.poignancy}</span>`)).join("")||`<div class="lr soft">${T.none}</div>`;
  const stm=m.seq_event.slice(0,5).map(n=>n.node_id).join(" ");
  const ret=a.lastRetrieval?a.lastRetrieval.nodes.map(([n,sc])=>row(n.clk,n.description,` <span class="nid">${n.node_id} · ${sc.toFixed(2)}</span>`)).join(""):`<div class="lr soft">${T.noRet}</div>`;
  const utt=a.lastUtt?row(a.lastUtt.clk,a.lastUtt.t,a.lastUtt.ev.length?` <span class="nid">← ${a.lastUtt.ev.join(" ")}</span>`:""):`<div class="lr soft">${T.noUtt}</div>`;
  const plan=`${T.plan}: ${esc(a.pf.project)}${a.ideas.length?` · ${esc(ideaTitle(a.ideas[a.ideas.length-1]))}`:""}`;
  const act=L("STATE")[a.state]?L("STATE")[a.state](a):"";
  const refl=a.reflections[0]?a.reflections[0].qs.map(q=>`<div class="lr"><time>${a.reflections[0].clk}</time><span><b>${esc(tr(q.q))}</b>${q.insights.map(i=>`<div>${esc(tr(i.text))} <span class="nid">← ${i.ev.join(" ")}</span></div>`).join("")||`<div class="soft">${L("noEv")}</div>`}</span></div>`).join(""):`<div class="lr soft">${T.noRefl}</div>`;
  const stored=a.lastStored?a.lastStored.items.map(t=>row(a.lastStored.clk,t)).join(""):`<div class="lr soft">${T.noStored}</div>`;
  $("live-title").innerHTML=`<span>${esc(tr(who(a)))}${youTag(a)}</span> <span class="soft">· ${esc(a.group)} · ${esc(act)}</span>`;
  $("live-grid").innerHTML=`
    <div class="ab"><div class="abh">${T.perc}<small>${T.percS}</small></div>${perc}</div><div class="arrow">→</div>
    <div class="ab"><div class="abh">${T.mem}<small>${T.memS}</small></div>
      <div class="lr"><time>${T.stm}</time><span class="nid">${stm||"—"}</span></div>
      <div class="lr"><time>${T.ltm}</time><span>event ${m.seq_event.length} · thought ${m.seq_thought.length} · chat ${m.seq_chat.length}</span></div>
      <div class="lr"><time>${T.trig}</time><span><i class="meter"><b style="width:${Math.max(0,Math.min(100,100*(1-s.importance_trigger_curr/s.importance_trigger_max)))}%"></b></i></span></div></div>
    <div class="arrow">→</div>
    <div class="ab"><div class="abh">${T.ret}<small>${T.retS}</small></div>${ret}</div><div class="arrow">→</div>
    <div class="ab"><div class="abh">${T.reason}<small>${T.reasonS}</small></div>${utt}<div class="lr"><time></time><span>${plan}</span></div></div>
    <div class="arrow down">↓</div>
    <div class="ab wide"><div class="abh">${T.evo}<small>${T.evoS}</small></div><div class="two"><div><div class="subh">${T.reflH}</div>${refl}</div><div><div class="subh">${T.storedH}</div>${stored}</div></div></div>`;
}

/* =====================================================================
   RESULTADOS: 1) dónde nacen y se discuten las ideas · 2) cómo van las conversaciones · ideas nuevas
   ===================================================================== */
function results(){
  const mine=userAgent?IDEAS.filter(i=>i.members.has(userAgent)):[];
  const bornMine=mine.filter(i=>i.by.includes(userAgent)),joined=mine.filter(i=>!i.by.includes(userAgent));
  const others=new Set();for(const i of mine)for(const m of i.members)if(m!==userAgent)others.add(m);
  const byDay={};for(let d=1;d<=CFG.days;d++)byDay[d]=0;for(const i of IDEAS)byDay[i.born.day]=(byDay[i.born.day]||0)+1;
  const talked=talkedWith();
  return {mine,bornMine,joined,others:[...others],byDay,nIdeas:IDEAS.length,myConvs:userAgent?CLOG.filter(c=>c.mine).length:0,talked,goalOK:talked.length>=CFG.goal};
}
function renderResults(){
  const T=L("res"),R=results();
  const n=R.nIdeas;
  const tk=R.talked.length;
  $("res-verdict").innerHTML=(userAgent?`<div class="verdict small ${R.goalOK?"ok":""}"><div class="vbig">${tk} / ${CFG.goal}</div><div><div class="vt">${R.goalOK?T.goalWin:finished?T.goalLose:T.goalPending}</div><div class="hint">${T.goalSub(R.myConvs,tk,CFG.goal)}</div>
    ${tk?`<div class="faces" style="margin-top:6px">${R.talked.map(x=>`<span class="fc" title="${esc(tr(who(x.a)))}${x.a.pf.name?" · "+esc(x.a.pf.name):""}">${face(x.a)}<small>${esc(x.a.pf.name||x.a.pf.code)} · ${x.n}</small></span>`).join("")}</div>`:""}</div></div>`:"")+
  `<div class="verdict small ${n?"ok":""}" style="margin-top:8px"><div class="vbig">${n}</div><div><div class="vt">${T.ideasBorn(n)}</div><div class="hint">${userAgent?T.sub(R.bornMine.length,R.joined.length,R.others.length,finished?CFG.days:day,CFG.days):T.noUser}</div>
    ${userAgent&&R.others.length?`<div class="faces" style="margin-top:6px">${R.others.map(x=>`<span class="fc" title="${esc(tr(who(x)))} · ${esc(x.group)}">${face(x)}<small>${esc(x.pf.name||x.group)}</small></span>`).join("")}</div>`:""}</div></div>`;
  drawDemandAll();renderConvEvo();renderIdeas();
}
/* ---------- 1) mapa de calor: dónde nacen y se discuten las ideas, en el tiempo ---------- */
function demandAt(t){
  const born={},talk={};
  for(const i of IDEAS)if(i.born.t<=t)born[i.born.place]=(born[i.born.place]||0)+1;
  for(const c of CLOG)if(c.t<=t)talk[c.place]=(talk[c.place]||0)+1;
  return {born,talk};
}
function drawDemand(cv,t,small){
  const w=cv.clientWidth,h=w*265/425,dpr=window.devicePixelRatio||1;if(!w)return;
  cv.width=w*dpr;cv.height=h*dpr;cv.style.height=h+"px";const g=cv.getContext("2d");g.setTransform(dpr,0,0,dpr,0,0);
  g.fillStyle="#fff";g.fillRect(0,0,w,h);if(svImg.complete){g.globalAlpha=.55;g.drawImage(svImg,0,0,w,h);g.globalAlpha=1}
  const sx=w/425,sy=h/265,D=demandAt(t),max=Math.max(1,...Object.values(D.born)),maxT=Math.max(1,...Object.values(D.talk));
  // espacios: tinte por conversaciones (suave) y por ideas nacidas (fuerte)
  for(const id of SPIDS){const v=D.born[id]||0,tk=D.talk[id]||0;if(!v&&!tk)continue;
    g.fillStyle=`rgba(255,79,18,${Math.min(.85,.1*tk/maxT+.7*v/max)})`;g.beginPath();for(const [px,py] of SPPTS[id])g.rect((px-185)*sx-sx,(py-40)*sy-sy,2*sx+1,2*sy+1);g.fill()}
  g.drawImage(MASK,0,0,w,h);
  for(const id of SPIDS){const v=D.born[id]||0,tk=D.talk[id]||0,[cx,cy]=SPC[id],X=(cx-185)*sx,Y=(cy-40)*sy;
    if(!small){g.font="bold 9px 'Silkscreen', monospace";g.fillStyle="rgba(0,0,0,.75)";g.fillText(SP[id].short,X-10,Y-6);if(v||tk){g.font="bold 12px 'Silkscreen', monospace";g.fillStyle="#161616";g.fillText(v,X-10,Y+8);g.font="8px Archivo, sans-serif";g.fillStyle="rgba(0,0,0,.6)";g.fillText(`${tk} conv`,X+(v>9?14:8),Y+8)}}
    else if(v){g.font="bold 9px 'Silkscreen', monospace";g.fillStyle="#161616";g.fillText(v,X-4,Y+4)}}
  if(userAgent&&!small)for(const i of IDEAS){if(i.born.t>t||!i.members.has(userAgent))continue;const [px,py]=PX(i.born.x,i.born.z);g.strokeStyle="#161616";g.lineWidth=1.5;g.beginPath();g.arc((px-185)*sx,(py-40)*sy,6,0,6.28);g.stroke()}
}
const simEnd=()=>Math.min(simT,CFG.days*DAY_LEN);
function tLabel(t){const d=Math.min(CFG.days,Math.floor(t/DAY_LEN)+1),m=540+Math.floor((t-(d-1)*DAY_LEN)/3);return L("res").at(d,`${String(Math.floor(m/60)%24).padStart(2,"0")}:${String(m%60).padStart(2,"0")}`)}
let resPlay=null;
function drawDemandAll(){const t=simEnd()*(+$("res-t").value/1000);$("res-tlab").textContent=tLabel(t);drawDemand($("res-map"),t,false)}
$("res-ideas").addEventListener("click",e=>{const f=e.target.closest(".ev,.face");if(!f)return;selAgent=agents[+f.dataset.a];hiIds=f.dataset.ids?f.dataset.ids.split(","):[];dirtyMem=true;showNav("sim");showTab("mem")});
$("res-t").addEventListener("input",()=>{if(resPlay){clearInterval(resPlay);resPlay=null;$("t-resplay").textContent=L("res").play}drawDemandAll()});
$("res-play").addEventListener("click",()=>{
  if(resPlay){clearInterval(resPlay);resPlay=null;$("t-resplay").textContent=L("res").play;return}
  const sl=$("res-t");if(+sl.value>=1000)sl.value=0;$("t-resplay").textContent=L("res").stop;
  resPlay=setInterval(()=>{sl.value=Math.min(1000,+sl.value+8);drawDemandAll();if(+sl.value>=1000){clearInterval(resPlay);resPlay=null;$("t-resplay").textContent=L("res").play}},60);
});
/* ---------- 2) cómo van las conversaciones ---------- */
function renderConvEvo(){
  const T=L("res"),rows=[];
  for(let d=1;d<=CFG.days;d++){if((d-1)*DAY_LEN>=simT&&d>1)break;const cs=CLOG.filter(c=>c.day===d);
    rows.push(`<div class="cday"><span>${L("dayShort")} ${d}</span><div class="cstrip">${cs.map(c=>`<i class="csq ${c.out==="none"?"":c.out}${c.mine?" mine":""}" title="${c.clk} · ${esc(trp(SP[c.place].n))} · ${esc(tr(who(c.a)))} · ${esc(tr(who(c.b)))}${c.idea?" · «"+esc(c.idea.title)+"»":""}"></i>`).join("")}</div><b>${T.dayRow(cs.length,cs.filter(c=>c.out==="born").length,cs.filter(c=>c.out==="evo").length,cs.filter(c=>c.out==="join").length)}</b></div>`)}
  const pct=CLOG.length?Math.round(100*CLOG.filter(c=>c.out==="born"||c.out==="join"||c.out==="evo").length/CLOG.length):0;
  const byPlace={};for(const c of CLOG)byPlace[c.place]=(byPlace[c.place]||0)+1;
  $("res-conv").innerHTML=`${rows.join("")}<p class="hint" style="margin-top:8px">${T.trend(CLOG.length,pct)} ${Object.entries(byPlace).sort((a,b)=>b[1]-a[1]).map(([p,n])=>`${esc(trp(SP[p].n))} ${n}`).join(" · ")}</p>`;
}
/* ---------- ideas nuevas: la lista ---------- */
const pname=a=>a.pf.name||tr(who(a));
function ideaText(i){const T=L("res"),[A,B]=i.by,part=i.parts[1].text;
  const wantsKind=B.pf.skills.includes(part)?"skill":"interest";
  return T.ideaText(A.pf.project,part,pname(A),A.pf.skills.join(T.and),pname(B),B.pf.skills.join(T.and),wantsKind,trp(SP[i.born.place].n))}
function renderIdeas(){
  const T=L("res"),box=$("res-ideas");
  if(!IDEAS.length){box.innerHTML=`<p class="hint">${T.noIdeas}</p>`;return}
  const list=[...IDEAS].sort((a,b)=>b.members.size-a.members.size||a.born.t-b.born.t);
  box.innerHTML=`<div class="ideas">${list.map(i=>`<div class="idea${userAgent&&i.members.has(userAgent)?" mine":""}">
    <div class="it"><b>${esc(ideaTitle(i))}</b><p>${esc(ideaText(i))}</p></div>
    <div class="vers">${i.versions.map(v=>`<div class="ver${v.n===i.versions.length?" cur":""}"><span class="mono">v${v.n} · ${esc(v.clk)} · ${esc(trp(SP[v.place].n))}</span><span>${v.kind==="born"?T.vBorn:esc(tr(v.text))} <i class="pair">${v.by.map(face).join("")}</i>${v.evidence.length?` <button class="ev" data-a="${v.by[0].id}" data-ids="${v.evidence.join(",")}" title="${L("evTitle")}">${v.evidence.join(" ")}</button>`:""}</span></div>`).join("")}</div>
    <div class="im"><span class="mono">${esc(i.born.clk)} · ${esc(trp(SP[i.born.place].n))}</span><span class="pair">${[...i.members].slice(0,8).map(face).join("")}${i.members.size>8?`<i>+${i.members.size-8}</i>`:""}</span><span class="hint">${T.ideaFrom(esc(shortP(i.parts[0].text)),esc(i.parts[1].text))}</span></div></div>`).join("")}</div>`;
}
function onFinish(){renderAll();showNav("results");$("ff-bar").hidden=true;finishRun()}  // report.js: newsletter, chart, saved run

/* ---------- navegación: perfil · simulación · resultados ---------- */
let nav="survey";
function showNav(k){nav=k;["survey","sim","results"].forEach(t=>{$("nav-"+t).setAttribute("aria-pressed",t===k);$("sec-"+t).hidden=t!==k});
  try{if(location.hash!=="#"+k)history.replaceState(null,"","#"+k)}catch(e){}
  if(k==="results"){renderResults();renderReport()}if(k==="sim"){resize();renderAll()}if(k!=="survey"&&typeof camClose==="function")camClose()}
["survey","sim","results"].forEach(k=>$("nav-"+k).addEventListener("click",()=>showNav(k)));
window.addEventListener("hashchange",()=>{const k=location.hash.slice(1);if(["survey","sim","results"].includes(k))showNav(k)});

/* ---------- perfil: elige tu código, acepta que se use tu perfil o modifícalo ---------- */
const YOU_KEY="placelab-341-you";
function saveYou(u){try{localStorage.setItem(YOU_KEY,JSON.stringify(u))}catch(e){}}
function loadYou(){try{const u=JSON.parse(localStorage.getItem(YOU_KEY)||"null");if(u&&PROFILES.some(p=>p.code===u.code))return u}catch(e){}return null}
function forgetYou(){try{localStorage.removeItem(YOU_KEY)}catch(e){}}
const svImg=new Image();svImg.src=PLANTEX;svImg.onload=()=>{if(nav==="results")drawDemandAll()};
function fillCodeOptions(){const sel=$("pf-code");sel.innerHTML=`<option value="">${L("pfChoose")}</option>`+PROFILES.map(p=>`<option value="${esc(p.code)}">${p.name?esc(p.name)+" · ":""}${esc(p.team)} · ${esc(p.code)}${p.active===false?" · "+L("pfInactive"):""}</option>`).join("")+`<option value="__new">${L("pfAdd")}</option>`}
/* añadirte si no estás en la lista: el perfil nuevo se guarda en este navegador y entra en la simulación */
const EXTRA_KEY="placelab-341-extra";
(function loadExtra(){try{const ex=JSON.parse(localStorage.getItem(EXTRA_KEY)||"[]");for(const p of ex)if(!PROFILES.some(q=>q.code===p.code))PROFILES.push(p)}catch(e){}})();
function addYourself(){const name=$("pf-nname").value.trim().slice(0,40),team=$("pf-nteam").value.trim().slice(0,40)||"—",project=$("pf-project").value.trim().slice(0,140),skills=parseList($("pf-skills").value),interests=parseList($("pf-interests").value);
  if(!name||!project||!skills.length||!interests.length){$("pf-err").textContent=L("pfNeed2");return null}$("pf-err").textContent="";
  let n=PROFILES.length+1,code;do{code="S"+String(n++).padStart(2,"0")}while(PROFILES.some(p=>p.code===code));
  const p={code,name,team,interests,skills,project,alt:[],bio:"",site:""};PROFILES.push(p);
  try{const ex=JSON.parse(localStorage.getItem(EXTRA_KEY)||"[]");ex.push(p);localStorage.setItem(EXTRA_KEY,JSON.stringify(ex))}catch(e){}
  fillCodeOptions();$("pf-code").value=code;return code}
const parseList=s=>s.split(/[,;·]/).map(x=>x.trim()).filter(Boolean).slice(0,5);
function pfPreview(){
  const code=$("pf-code").value,p=PROFILES.find(p=>p.code===code),box=$("pf-view");
  $("pf-new").hidden=code!=="__new";
  if(code==="__new"){box.hidden=true;$("pf-actions").hidden=true;$("pf-edit").hidden=false;$("pf-avatar").hidden=false;if(!svAv||svAv.code!=="__new")svAv={code:"__new",...avatarIdx(PROFILES.length)};renderAvatarEditor();$("pf-nname").focus();return}
  if(!p){box.hidden=true;$("pf-actions").hidden=true;$("pf-edit").hidden=true;$("pf-avatar").hidden=true;return}
  const pf={...p,...(CFG.user&&CFG.user.code===code?CFG.user.over||{}:{})},i=PROFILES.indexOf(p);
  if(!svAv||svAv.code!==code)svAv={code,...(CFG.user&&CFG.user.code===code&&CFG.user.avatar?CFG.user.avatar:p.avatar||avatarIdx(i))};
  const tex=spriteFrom(svAv);
  box.hidden=false;$("pf-actions").hidden=false;
  box.innerHTML=`<img alt="" src="${tex[0].url}" style="width:56px;height:84px;image-rendering:pixelated">${mono7(GI[p.team]||"EQ","dark")}<div class="hint"><b>${esc(p.code)}${pf.name?" · "+esc(pf.name):""} · ${esc(p.team)}</b><br>${L("pfProj")}: ${esc(pf.project)}<br>${L("pfSkills")}: ${esc(pf.skills.join(", "))}<br>${L("pfInt")}: ${esc(pf.interests.join(", "))}${pf.bio?`<br><span class="soft">${esc(pf.bio)}</span>`:""}</div>`;
  renderAvatarEditor();
  $("pf-edit").hidden=true;
}
/* avatar: eliges ropa, pelo y piel; el personaje y su descripción («la de camiseta roja y pelo negro») salen de aquí */
let svAv=null;
const AVROWS=[["t",SHIRT,"avShirt"],["h",HAIR,"avHair"],["s",SKIN,"avSkin"],["p",PANTS,"avPants"]];
const avOnly=av=>{const o={t:av.t,h:av.h,s:av.s,p:av.p,hs:av.hs||0,g:av.g||0};if(av.face)o.face=av.face;return o};
function renderAvatarEditor(){const el=$("pf-avatar");if(!el||!svAv)return;el.hidden=false;
  const txtRow=(k,names,lab)=>`<div class="avrow"><span>${lab}</span>${names.map((n,j)=>`<button type="button" class="sw txt${(svAv[k]||0)===j?" on":""}" data-k="${k}" data-j="${j}">${esc(n)}</button>`).join("")}</div>`;
  el.innerHTML=`<div class="lab">${L("pfavatar")}</div>`+AVROWS.map(([k,arr,lab])=>`<div class="avrow"><span>${L(lab)}</span>${arr.map((c,j)=>`<button type="button" class="sw${svAv[k]===j?" on":""}" data-k="${k}" data-j="${j}" style="background:${c}" aria-label="${L(lab)} ${j+1}"></button>`).join("")}</div>`).join("")
    +txtRow("hs",L2("styles"),L2("avStyle"))+txtRow("g",L2("glasses"),L2("avGlasses"))
    +(svAv.face?`<div class="avrow"><span>${L2("avFace")}</span><button type="button" class="btn" data-av="noface">${L2("avFaceClear")}</button></div>`:"")
    +`<div class="ctl" style="gap:8px;flex-wrap:wrap"><button type="button" class="btn orange" data-av="cam">${L2("camBtn")}</button><button type="button" class="btn" data-av="copy">${L2("avCopy")}</button></div>`
    +`<div class="hint">${L("avLabel")}: ${esc(tr(`la de camiseta ${SHIRTN[svAv.t%SHIRTN.length]} y ${HAIRN[svAv.h%HAIRN.length]}`))}</div><div class="hint" id="av-msg"></div>`}
$("pf-avatar").addEventListener("click",e=>{
  const act=e.target.closest("[data-av]");
  if(act&&svAv){const k=act.dataset.av;
    if(k==="noface"){delete svAv.face;pfPreview()}
    if(k==="copy"){const s=`"avatar": ${JSON.stringify(avOnly(svAv))}`;(navigator.clipboard?navigator.clipboard.writeText(s):Promise.reject()).then(()=>$("av-msg").textContent=L2("avCopied"),()=>$("av-msg").textContent=s)}
    if(k==="cam")camOpen(svAv,av=>{const code=svAv.code;svAv={code,...avOnly(av)};pfPreview()});
    return}
  const b=e.target.closest(".sw");if(!b||!svAv)return;svAv[b.dataset.k]=+b.dataset.j;pfPreview()});
$("pf-code").addEventListener("change",pfPreview);
$("pf-accept").addEventListener("click",()=>{const code=$("pf-code").value;if(!code)return;adoptProfile(code,null)});
$("pf-modify").addEventListener("click",()=>{const code=$("pf-code").value,p=PROFILES.find(p=>p.code===code);if(!p)return;const pf={...p,...(CFG.user&&CFG.user.code===code?CFG.user.over||{}:{})};
  $("pf-edit").hidden=false;$("pf-project").value=pf.project;$("pf-skills").value=pf.skills.join(", ");$("pf-interests").value=pf.interests.join(", ");$("pf-project").focus()});
$("pf-cancel").addEventListener("click",()=>{$("pf-edit").hidden=true});
$("pf-save").addEventListener("click",()=>{let code=$("pf-code").value;if(!code)return;
  if(code==="__new"){code=addYourself();if(!code)return;if(svAv)svAv.code=code;adoptProfile(code,null);return}
  const over={project:$("pf-project").value.trim().slice(0,140),skills:parseList($("pf-skills").value),interests:parseList($("pf-interests").value)};
  if(!over.project||!over.skills.length||!over.interests.length){$("pf-err").textContent=L("pfNeed");return}$("pf-err").textContent="";
  adoptProfile(code,over)});
function adoptProfile(code,over){
  const prev=CFG.user;CFG.user={code,over:over||(prev&&prev.code===code?prev.over:null)||null,history:(prev&&prev.code===code?prev.history:[])||[],avatar:svAv&&svAv.code===code?avOnly(svAv):(prev&&prev.code===code?prev.avatar:null)};
  CFG.user.history.push({stamp:new Date().toISOString().slice(0,16).replace("T"," "),over:CFG.user.over});
  saveYou({...CFG.user,days:CFG.days});
  running=true;init();renderAll();renderYouCard();pfPreview();showNav("sim");setFollow(true);
}
function renderYouCard(){const c=$("you-card");if(!userAgent){c.hidden=true;$("pf-form").hidden=false;return}c.hidden=false;$("pf-form").hidden=true;$("you-face").innerHTML=`<img alt="" src="${userAgent.tex[0].url}">`;
  const H=CFG.user.history||[],vs=H.length>1?`<div class="hint">${L("you2").versions(H.length)}</div>`:"";
  $("you-sub").innerHTML=L("you2").sub(esc(tr(who(userAgent))),esc(userAgent.pf.code)+(userAgent.pf.name?" · "+esc(userAgent.pf.name):""),esc(userAgent.group),esc(userAgent.pf.project))+vs}
$("you-follow").addEventListener("click",()=>{running=!finished;showNav("sim");setFollow(true)});
$("you-edit").addEventListener("click",()=>{$("pf-form").hidden=false;$("you-card").hidden=true;$("pf-code").value=CFG.user.code;pfPreview();$("pf-modify").click()});
$("you-forget").addEventListener("click",()=>{forgetYou();CFG.user=null;setFollow(false);init();renderAll();renderYouCard();$("pf-code").value="";pfPreview()});
function renderYouStrip(R){const st=$("you-strip");if(!userAgent){st.hidden=true;return}st.hidden=false;const a=userAgent;
  if(!st.dataset.id||+st.dataset.id!==a.id){st.dataset.id=a.id;$("ys-face").innerHTML=`<img alt="" src="${a.tex[0].url}">`}
  $("ys-who").textContent=`${L("you")} · ${tr(who(a))} · ${a.pf.code}`;
  const S=L("STATE"),act=a.onFloor?(S[a.state]?S[a.state](a):""):S.away();
  const partner=a.state==="talk"&&a.conv?(a.conv.a===a?a.conv.b:a.conv.a):null;
  $("ys-act").textContent=`${tr(act)}${partner?` · ${tr(who(partner))}`:""} · ${a.pf.project}`;
  $("ys-n").textContent=R?`${R.talked.length} / ${CFG.goal}`:"—";
  const pins=$("ys-pins");if(pins&&R){const key=R.talked.map(t=>t.a.id+":"+t.n).join(",");if(pins.dataset.key!==key){pins.dataset.key=key;pins.innerHTML=R.talked.map(t=>`<span class="pin" title="${esc(t.a.pf.name||tr(who(t.a)))} · ${t.n}">${face(t.a)}</span>`).join("")+Array.from({length:Math.max(0,CFG.goal-R.talked.length)},()=>`<span class="pin empty"></span>`).join("")}}}
let follow=false;
function setFollow(on){follow=!!on;$("follow").setAttribute("aria-pressed",follow);if(follow&&userAgent){const off=camera.position.clone().sub(controls.target);if(off.length()>11)off.setLength(11);controls.target.set(userAgent.x,.5,userAgent.z);camera.position.copy(controls.target).add(off);controls.update()}}
$("follow").addEventListener("click",()=>setFollow(!follow));
["v3d","vtop","vcafe"].forEach(id=>$(id).addEventListener("click",()=>setFollow(false)));

/* ---------- bucle ---------- */
const playIcon=$("playicon");
$("play").addEventListener("click",()=>{if(finished)return;running=!running;playIcon.innerHTML=running?'<rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/>':'<path d="M7 4l13 8-13 8z"/>';$("play").setAttribute("aria-label",running?L("pause"):L("resume"));$("play").title=running?L("pause"):L("resume")});
$("reset").addEventListener("click",()=>{running=true;init();renderAll();renderYouCard()});
$("days").addEventListener("change",()=>{CFG.days=+$("days").value;if(CFG.user)saveYou({...CFG.user,days:CFG.days});if(day>CFG.days&&!finished){finished=true;running=false;onFinish()}renderAll()});
$("ff-day").addEventListener("click",()=>{if(!finished)fastForward(false)});
$("ff-all").addEventListener("click",()=>{if(!finished)fastForward(true)});
function renderAll(){renderConvs();if(tab==="mem")renderMem();if(tab==="you")renderYou();drawSchema();drawLive();renderGroups();renderLLMMode();if(nav==="results"){renderResults();renderReport()}}
let last=performance.now(),lastUI=0,lastHeat=0,lastEvid=0;
const youRing=new THREE.Points(ringGeo,new THREE.PointsMaterial({size:.2,color:0xFF4F12,map:dotTex,transparent:true,depthWrite:false,opacity:.95}));youRing.visible=false;scene.add(youRing);
function loop(now){
  const dt=Math.min(.05,(now-last)/1000);last=now;
  if(ffUntil===null){const k=running&&!finished?+$("speed").value:0;if(k){update(dt*k)}}
  agents.forEach(a=>{
    if(!a.onFloor)return;
    const moving=a.state==="walk",f=moving?[0,1,0,2][Math.floor(now/140)%4]:0;
    if(a.sp.material.map!==a.tex[f]){a.sp.material.map=a.tex[f];a.sp.material.needsUpdate=true}
    const bob=a.state==="talk"?Math.abs(Math.sin(now/180))*.08:0;
    a.sp.position.set(a.x,.52+bob,a.z);a.sh.position.set(a.x,.012,a.z);
    placeSub(a);
    a.bub.visible=(a.state==="talk"||a.state==="chat")&&a.sub.hidden;a.bub.position.set(a.x+.2,1.32+Math.sin(now/300)*.04,a.z);
  });
  if(userAgent&&userAgent.onFloor){youRing.visible=true;youRing.position.set(userAgent.x,.06,userAgent.z);youRing.scale.setScalar(.75+Math.sin(now/300)*.06)}else youRing.visible=false;
  for(let i=pulses.length-1;i>=0;i--){const p=pulses[i];p.t+=dt;p.m.scale.setScalar(.3+p.t*2.2);p.m.material.opacity=Math.max(0,.95-p.t*.95);if(p.t>1){scene.remove(p.m);p.m.material.dispose();pulses.splice(i,1)}}
  for(let i=arcs.length-1;i>=0;i--){const p=arcs[i];p.t+=dt;p.m.material.opacity=Math.max(0,1-p.t*.7);if(p.t>1.5){scene.remove(p.m);p.m.geometry.dispose();p.m.material.dispose();arcs.splice(i,1)}}
  for(let i=ghosts.length-1;i>=0;i--){const p=ghosts[i];p.t+=dt;p.m.scale.setScalar(.7+Math.sin(p.t*2)*.15);p.m.material.opacity=Math.max(0,.95-p.t/8);if(p.t>8){scene.remove(p.m);p.m.material.dispose();ghosts.splice(i,1)}}
  if(now-lastHeat>500){lastHeat=now;if(presenceHeat.on&&presenceHeat.dirty)presenceHeat.render();if(proposals.on&&proposals.dirty)proposals.render()}
  if(follow&&userAgent&&nav==="sim"){const dx=(userAgent.x-controls.target.x)*.12,dz=(userAgent.z-controls.target.z)*.12;controls.target.x+=dx;controls.target.z+=dz;camera.position.x+=dx;camera.position.z+=dz}
  if(nav==="sim"){controls.update();renderer.render(scene,camera)}
  if(now-lastUI>400){lastUI=now;
    $("clock").textContent=hhmm();$("dayn").textContent=`${L("dayShort")} ${Math.min(day,CFG.days)} / ${CFG.days}`;$("count").textContent=L("count")(agents.filter(a=>a.onFloor).length,POP,agents.filter(a=>a.onFloor&&inZone("cafe",a.x,a.z)).length);
    const R=results();$("sConv").textContent=userAgent?`${R.talked.length} / ${CFG.goal}`:`${IDEAS.length}`;$("sMeet").textContent=meets;$("sTalks").textContent=convs.length;
    renderYouStrip(R);
    if(dirtyConv){renderConvs();dirtyConv=false}
    if(dirtyMem&&tab==="mem"){renderMem();dirtyMem=false}
    if(tab==="you"&&dirtyMem){renderYou()}
    drawSpark();if(now-lastEvid>2000){lastEvid=now;drawLive();drawSchema();renderGroups();if(nav==="results")renderResults()}}
  requestAnimationFrame(loop);
}
{const u=loadYou();if(u){CFG.user={code:u.code,over:u.over||null,history:u.history||[],avatar:u.avatar||null};CFG.days=u.days||3;$("days").value=String(CFG.days);if(!$("days").value)$("days").value="3";CFG.days=+$("days").value}}
// ask serve.py first whether the model, earlier runs and memories are available (talk.js); without it, templates
llmInit().finally(()=>{
  init();setView("v3d");resize();applyLang();fillCodeOptions();if(CFG.user)$("pf-code").value=CFG.user.code;pfPreview();renderAll();renderYouCard();renderLLMMode();
  showNav(["sim","results"].includes(location.hash.slice(1))?location.hash.slice(1):"survey");
  if(userAgent&&location.hash.slice(1)==="sim")setFollow(true);
  requestAnimationFrame(loop);
});
function renderLLMMode(){const el=$("llm-mode");if(el)el.textContent=LLM.on?L2("llmOn")(LLM.model):L2("llmOff")}
