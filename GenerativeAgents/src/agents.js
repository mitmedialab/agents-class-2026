/* =====================================================================
   CLASE 341 · ideas: espacios comunes, perfiles y los "LLM" sustitutos
   (plantillas finitas en español; tr() las traduce por reglas)
   ===================================================================== */
const SP={
  r341:{n:"la sala 341",zone:"nagashima",short:"341",g:"f"},
  cafe:{n:"la cafetería",zone:"cafe",short:"CAFE",g:"f"},
  atrium:{n:"el atrio",zone:"atrium",short:"ATRIO",g:"m"},
  foodcam:{n:"el foodcam",zone:"foodcam",short:"FOOD",g:"m"},
  pasaje:{n:"el pasaje principal",r:[375,128,470,162],short:"PASAJE",g:"m"},
  alanorte:{n:"el ala norte de E15",r:[190,83,408,156],short:"NORTE",g:"f"},
  swatchc:{n:"el pasillo del Swatch Lab",r:[470,40,605,128],short:"SWATCH",g:"m"},
  btc:{n:"el pasillo del BT Lab",r:[470,200,605,300],short:"BT",g:"m"},
  sur:{n:"el pasillo sur",r:[238,250,408,300],short:"SUR",g:"m"}
};
for(const id in SP){const s=SP[id];if(s.zone)s.r=ZONES[s.zone].r}
const SPIDS=Object.keys(SP),TALKZ=["cafe","atrium","foodcam"];
const spaceOf=(x,z)=>{for(const id of ["cafe","foodcam","atrium","r341"])if(inZone(SP[id].zone,x,z))return id;const p=placeOf(x,z);return SPIDS.find(id=>SP[id].n===p)||null};
// centro y puntos pisables de cada espacio (para visitas, calor y mapas)
const SPC={},SPPTS={};
for(const id of SPIDS){const [x1,y1,x2,y2]=SP[id].r,pts=[];for(let y=y1;y<=y2;y+=2)for(let x=x1;x<=x2;x+=2)if(inAllowed(x,y)&&walkable(x,y)&&(SP[id].zone?inZone(SP[id].zone,...Object.values(W(x,y))):placeOf(...Object.values(W(x,y)))===SP[id].n))pts.push([x,y]);
  if(!pts.length)pts.push(nearestWalkable((x1+x2)/2,(y1+y2)/2));SPPTS[id]=pts;const c=pts.reduce((s,p)=>[s[0]+p[0],s[1]+p[1]],[0,0]);SPC[id]=[c[0]/pts.length,c[1]/pts.length]}
const spc3=id=>W(...SPC[id]),spotOf=id=>W(...pick(SPPTS[id]));
const FACTS={
  r341:["tiene mesas y pizarra","es tranquila","es pequeña","está lejos de la cafetería"],
  cafe:["tiene café y comida","pasa gente todo el rato","es ruidosa","está al lado del atrio"],
  atrium:["es grande","tiene mucha luz","tiene eco","está al lado de la cafetería"],
  foodcam:["a veces hay comida gratis","es un sitio de paso","es pequeño","está al lado de la cafetería"],
  pasaje:["pasa todo el mundo","es ruidoso","conecta E14 y E15"],
  alanorte:["es tranquila","tiene ventanas","está lejos de la cafetería"],
  swatchc:["tiene ventanas","es tranquilo","está cerca de los ascensores"],
  btc:["es tranquilo","no tiene ventanas","está cerca de los ascensores"],
  sur:["no pasa casi nadie","es largo","está lejos de todo"]
};
const POSF=/es grande|mucha luz|tranquil|mesas y pizarra|café y comida|comida gratis|al lado de|cerca de los ascensores|pasa todo el mundo|tiene ventanas/;
const NEGF=/es pequeñ|no tiene ventanas|lejos de|ruidos|tiene eco|sitio de paso|no pasa casi nadie|es largo/;
const spaceIn=t=>SPIDS.find(id=>t.includes(SP[id].n))||null;

/* ---------- ideas: nacen al cruzar un proyecto con lo que trae otra persona ---------- */
const IDEAS=[];let ideaN=0;
const qt=t=>`«${t}»`;
const shortP=p=>p.length>48?p.slice(0,46).replace(/\s+\S*$/,"")+"…":p;
function newIdea(a,b,part,place,x,z){
  const title=`${shortP(a.pf.project)} + ${part}`;
  const idea={id:"i"+(++ideaN),title,parts:[{a,text:a.pf.project},{a:b,text:part}],by:[a,b],members:new Set([a,b]),born:{t:simT,day,clk:clock(),place,x,z},mentions:0,tags:[...new Set([...a.pf.interests,...b.pf.interests,part])],llm:null,
    versions:[{n:1,kind:"born",t:simT,clk:clock(),place,by:[a,b],text:`${a.pf.project} + ${part}`,evidence:[]}],wanted:new Map()};
  IDEAS.push(idea);return idea;
}
const ideaTitle=i=>i.llm&&i.llm.title?i.llm.title:i.title;

/* ---------- "LLM" sustitutos ---------- */
function LLM_embedding(text){const m=new Map();for(const w of tokens(text))m.set(w,(m.get(w)||0)+1);return m}
function LLM_poignancy_event(desc){
  if(desc.includes("idle"))return 1;
  if(desc.includes("tiene una idea con")||desc.includes("se apunta a la idea"))return 8;
  if(POSF.test(desc)||NEGF.test(desc))return 4;
  if(desc.includes("va a ver"))return 4;if(desc.includes("conversa con"))return 3;
  if(desc.includes("la cafetería")||desc.includes("el atrio")||desc.includes("el foodcam"))return 3;return 2;
}
function LLM_poignancy_thought(t){if(/^Idea con|^Me apunté|^La idea .* ahora/.test(t))return 8;if(/^Varias personas|^Mucha gente/.test(t))return 7;if(/ sabe de | anda con /.test(t))return 5;return 4}
function LLM_poignancy_chat(ctx){return ctx.born.length?8:ctx.adopt.length?7:ctx.agree?5:4}
function LLM_triple(persona,t){
  const w=SHIRTN.find(c=>t.includes("camiseta "+c));const m=t.match(/«([^»]+)»/);const s=spaceIn(t);
  return [w?"la de camiseta "+w:who(persona),"piensa",m?"«"+m[1]+"»":s?SP[s].n:"el proyecto"];
}
function LLM_focal_points(persona,statements,n){
  const count={};
  const known=new Set();for(const nd of persona.a_mem.seq_thought)if(/ sabe de | anda con | está con la idea /.test(nd.description)){const w=SHIRTN.find(c=>nd.description.includes("camiseta "+c));if(w)known.add("la de camiseta "+w)}
  for(const nd of statements){if(nd.type==="event"&&/ (trabaja en|está en clase|camina por|conversa con|está en|llega a|sale de|está fuera de) /.test(nd.description))continue;
    for(const k of nd.keywords){const kw=k.toLowerCase();if(kw===who(persona)||kw==="el proyecto")continue;count[kw]=(count[kw]||0)+nd.poignancy}}
  const top=Object.entries(count).sort((a,b)=>b[1]-a[1]).map(e=>e[0]),qs=[];
  for(const kw of top){if(qs.length>=n)break;
    if(kw.startsWith("«")){if(!qs.some(q=>q.includes(kw)))qs.push(`¿Quién está con la idea ${kw}?`)}
    else if(kw.startsWith("la de camiseta")){const short="la de camiseta "+(SHIRTN.find(c=>kw.startsWith("la de camiseta "+c))||"");if(known.has(short)&&!qs.some(q=>q.includes(short)))qs.push(`¿Qué sabe hacer ${short}?`)}
    else{const s=SPIDS.find(id=>SP[id].n.toLowerCase()===kw);if(s&&!qs.some(q=>q.includes(SP[s].n)))qs.push(`¿Cómo es ${SP[s].n}?`)}}
  while(qs.length<n)qs.push(["¿Qué ideas están sonando?","¿Con quién podría trabajar?","¿Dónde se habla más?"][qs.length]);
  return qs.slice(0,n);
}
function LLM_insights(persona,numbered,n,focal=""){
  const out=[],bySpace={},byIdea={},byPerson={};
  const fSpace=SPIDS.find(id=>focal.includes(SP[id].n)),fPerson=SHIRTN.find(c=>focal.includes("camiseta "+c)),fm=focal.match(/«([^»]+)»/),fIdea=fm?fm[1]:null;
  for(const {nd} of numbered){
    if(nd.type==="chat")continue;const d=nd.description;
    const s=spaceIn(d);if(nd.type==="event"&&s&&nd.subject===SP[s].n){(bySpace[s]=bySpace[s]||{facts:new Set(),ids:[]});bySpace[s].facts.add(nd.predicate+(nd.object?" "+nd.object:""));bySpace[s].ids.push(nd.node_id)}
    const m=d.match(/«([^»]+)»/);if(m&&nd.type==="thought"){const t=m[1],w=SHIRTN.find(c=>d.includes("camiseta "+c))||who(persona);(byIdea[t]=byIdea[t]||{who:new Set(),ids:[]});byIdea[t].who.add(w);byIdea[t].ids.push(nd.node_id)}
    const pm=d.match(/^La de camiseta (\S+)(.*?) (sabe de|anda con) (.+)\.$/);if(pm&&nd.type==="thought"&&!(d.includes(" sabe de ")&&d.includes(" anda con "))){const w=pm[1];(byPerson[w]=byPerson[w]||{skill:null,proj:null,ids:[]});if(pm[3]==="sabe de")byPerson[w].skill=pm[4];else byPerson[w].proj=pm[4];byPerson[w].ids.push(nd.node_id)}
  }
  for(const [s,v] of Object.entries(bySpace)){const f=[...v.facts].map(x=>x.trim()).filter(Boolean);if(f.length>=2||(f.length&&s===fSpace))out.push([`${cap(SP[s].n)} ${f.slice(0,2).join(" y ")}.`,v.ids.slice(0,4)])}
  for(const [t,v] of Object.entries(byIdea)){if(v.who.size>=3)out.push([`Mucha gente está con la idea «${t}».`,v.ids.slice(0,5)]);else if(v.who.size===2)out.push([`Varias personas están con la idea «${t}».`,v.ids.slice(0,4)]);else if(fIdea===t)out.push([`La de camiseta ${[...v.who][0].replace(/^la de camiseta /,"")} está con la idea «${t}».`,v.ids.slice(0,3)])}
  for(const [w,v] of Object.entries(byPerson)){if(v.skill&&v.proj)out.push([`La de camiseta ${w} sabe de ${v.skill} y anda con ${v.proj}.`,v.ids.slice(0,3)]);else if(fPerson===w&&(v.skill||v.proj))out.push([v.skill?`La de camiseta ${w} sabe de ${v.skill}.`:`La de camiseta ${w} anda con ${v.proj}.`,v.ids.slice(0,2)])}
  const kind=t=>/«/.test(t)?"idea":/ sabe de | anda con /.test(t)?"person":"space";
  const generic=focal.includes("ideas están sonando")?"idea":focal.includes("podría trabajar")?"person":focal.includes("se habla más")?"space":null;
  const about=t=>{const tl=t.toLowerCase();return fSpace?tl.includes(SP[fSpace].n.toLowerCase()):fPerson?tl.includes("camiseta "+fPerson):fIdea?tl.includes(fIdea.toLowerCase()):generic?kind(t)===generic:true};
  return out.filter(([t])=>about(t)).slice(0,n);
}
function LLM_thoughts_on_convo(persona,other,chatNode,o){
  let plan=null,memo=null;
  const born=o.born.find(i=>i.by.includes(persona)&&i.by.includes(other));
  if(born)plan=`Tengo que seguir con ${qt(born.title)} con ${who(other)}.`;
  const join=o.adopt.find(x=>x.who===persona);if(!plan&&join)plan=`Quiero aportar a ${qt(join.idea.title)} lo que sé de ${persona.pf.skills[0]}.`;
  const op=o.props[other.id];
  if(op&&op.kind==="project")memo=`${cap(who(other))} anda con ${other.pf.project}.`;
  else if(op&&op.kind==="idea")memo=`${cap(who(other))} está con la idea ${qt(op.idea.title)}.`;
  else memo=`${cap(who(other))} sabe de ${other.pf.skills[0]}.`;
  return [plan,memo];
}
/* evidencia sobre una idea en las memorias recuperadas */
function ideaEvidence(persona,retrieved,idea){
  let w=0;const ids=[];
  const nodes=[];for(const f in retrieved)for(const n of retrieved[f].nodes)if(!nodes.includes(n))nodes.push(n);
  for(const n of nodes){if(!n.description.includes(idea.title))continue;ids.push(n.node_id);w+=/^Mucha gente/.test(n.description)?2:/^Varias personas/.test(n.description)?1.2:.6}
  return {w,ids};
}
/* ---------- cómo evoluciona una idea al oírla: lo que el oyente aporta sale de lo que recupera de su memoria ----------
   1) un memo «X sabe de S» (S nueva para la idea) → recomienda hablar con X (la idea busca a X: cuando X la oiga, se apuntará)
   2) un hecho de un espacio («el atrio tiene mucha luz») o un insight → propone dónde/cómo probarla
   3) su propia habilidad complementaria → se apunta y la idea gana esa parte
   Cada versión cita los nodos de memoria que la sostienen (evidence), igual que las reflexiones. */
function LLM_evolve(spk,oth,retrieved,idea){
  const R=new_retrieve(spk,[idea.title,idea.parts[0].text],12);const nodes=[];for(const f in R)for(const n of R[f].nodes)if(!nodes.includes(n))nodes.push(n);
  const have=new Set([...idea.tags,...idea.versions.map(v=>v.part).filter(Boolean)]);
  for(const n of nodes){const m=n.description.match(/^La de camiseta (\S+)(.*?) sabe de ([^.]+)\.$/);if(!m||n.type!=="thought"||/ y anda con /.test(n.description))continue;
    const w=("la de camiseta "+m[1]+m[2]).toLowerCase(),skill=m[3];if(have.has(skill)||idea.members.has(spk))continue;
    const who3=agents.find(x=>who(x)===w&&x!==spk&&x!==oth&&!idea.members.has(x));if(!who3)continue;
    return {kind:"referral",who:who3,part:skill,evidence:[n.node_id],utt:`Para ${qt(idea.title)} deberías hablar con ${who(who3)}: sabe de ${skill}.`}}
  for(const n of nodes){const s=spaceIn(n.description);if(!s||n.type==="chat"||s===idea.born.place)continue;if(!POSF.test(n.description))continue;
    if(idea.versions.some(v=>v.kind==="place"&&v.place===s))continue;
    return {kind:"place",place:s,evidence:[n.node_id],utt:`¿Y si lo probáis en ${SP[s].n}? ${n.description.replace(/^[^ ]+ /,m=>m)}`}}
  const cp=compl(oth,spk).filter(x=>!have.has(x));
  if(cp.length&&!idea.members.has(spk))return {kind:"part",part:cp[0],evidence:spk.projNode?[spk.projNode]:[],utt:`Yo le añadiría ${cp[0]}, que es lo mío.`};
  return null;
}
const shared=(a,b)=>a.pf.interests.filter(i=>b.pf.interests.includes(i));
const compl=(a,b)=>[...b.pf.skills.filter(s=>!a.pf.skills.includes(s)),...b.pf.interests.filter(i=>!a.pf.interests.includes(i))];
function LLM_utterance(spk,oth,retrieved,curr_chat,ctx){
  const turn=curr_chat.length;
  const lower=d=>(d.charAt(0).toLowerCase()+d.slice(1)).replace(/\.$/,"");
  const all=[];for(const f in retrieved)for(const n of retrieved[f].nodes)if(!all.includes(n))all.push(n);
  const openerOK=n=>n.type!=="chat"&&!/^(Idea con|Me apunté|Tengo que|Quiero aportar|Mi proyecto|Hablé con)/.test(n.description)&&!/ y yo hemos hablado| y yo ya hemos hablado|apenas la conozco/.test(n.description)&&!(n.type==="event"&&(n.subject===who(spk)||n.subject===who(oth)||/ (conversa con|está en clase|camina por|llega a|sale de|está fuera de|está en) /.test(n.description)))&&!(n.type==="thought"&&(n.description.toLowerCase().includes(who(spk))||n.description.toLowerCase().includes(who(oth))));
  const salient=all.filter(openerOK).sort((a,b)=>b.poignancy-a.poignancy||b.last_accessed-a.last_accessed)[0];
  const place=spaceOf(spk.x,spk.z)||"cafe";
  const tryBorn=(A,B)=>{ // B propone juntar lo de A con lo suyo
    const sh=shared(A,B).length,cp=compl(A,B);if(!cp.length)return null;
    const p=Math.min(.55,(.07+.22*sh+.025*cp.length+(A.user||B.user?.1:0))*B.persuadable);
    if(Math.random()>p)return null;
    const fresh=cp.filter(x=>!IDEAS.some(i=>i.title===`${shortP(A.pf.project)} + ${x}`));if(!fresh.length)return null; // esa combinación ya existe
    const part=pick(fresh),c=spc3(place);return newIdea(A,B,part,place,c.x,c.z)};
  if(turn===0){
    if(salient&&salient.type==="thought")return {utt:`Llevo pensando que ${lower(salient.description)}.`,end:false,evidence:[salient.node_id]};
    if(salient)return {utt:`Vengo de ver que ${lower(salient.description)}.`,end:false,evidence:[salient.node_id]};
    return {utt:"Hoy casi no me he cruzado con nadie.",end:false,evidence:[]};
  }
  if(turn===1){
    if(salient)return {utt:salient.type==="thought"?`Pues yo creo que ${lower(salient.description)}.`:`Yo he visto que ${lower(salient.description)}.`,end:false,evidence:[salient.node_id]};
    return {utt:"Yo acabo de llegar, todavía no me he fijado.",end:false,evidence:[]};
  }
  if(turn===2){
    const mine=spk.ideas.slice(-1)[0];
    if(mine&&Math.random()<.5){ctx.props[spk.id]={kind:"idea",idea:mine,by:spk};const other=[...mine.members].find(m=>m!==spk);
      const lv=mine.versions[mine.versions.length-1],tail=lv.kind==="part"?`, ahora también con ${lv.part}`:lv.kind==="place"?`, que queremos probar en ${SP[lv.place].n}`:lv.kind==="referral"?`; nos falta alguien que sepa de ${lv.part}`:"";
      return {utt:`Estoy con una idea${other?` con ${who(other)}`:""}: ${qt(mine.title)}${tail}.`,end:false,evidence:mine.node&&mine.node[spk.id]?[mine.node[spk.id]]:[],pitch:ctx.props[spk.id]}}
    ctx.props[spk.id]={kind:"project",by:spk};
    return {utt:`Yo estoy dándole vueltas a ${spk.pf.project}; lo mío es ${spk.pf.skills[0]}.`,end:false,evidence:spk.projNode?[spk.projNode]:[],pitch:ctx.props[spk.id]};
  }
  if(turn===3){
    const pa=ctx.props[oth.id];
    if(pa.kind==="idea"){const idea=pa.idea;
      if(idea.members.has(spk)){ctx.agree=true;return {utt:"Ya estoy en esa; cuenta conmigo.",end:true,evidence:[],agree:true}}
      const ev=ideaEvidence(spk,retrieved,idea),aff=idea.tags.filter(t=>spk.pf.interests.includes(t)).length;
      const wanted=idea.wanted.has(spk.id)?1:0;
      const score=(.5*aff+ev.w+Math.min(1.2,(spk.heardCount[idea.id]||0)*.4)+(oth.user?.3:0)+.4+wanted)*spk.persuadable;
      const evo=Math.random()<.7?LLM_evolve(spk,oth,retrieved,idea):null;
      if(evo&&evo.kind!=="part"){evolveIdea(idea,evo,spk,oth);ctx.evo.push({idea,evo,by:spk});return {utt:evo.utt,end:false,evidence:evo.evidence,evo:{idea,kind:evo.kind}}}
      if(score>.85||evo){joinIdea(spk,idea,oth);if(evo)evolveIdea(idea,evo,spk,oth);ctx.adopt.push({who:spk,idea,from:oth});return {utt:evo?`Me apunto, y ${evo.utt.charAt(0).toLowerCase()+evo.utt.slice(1)}`:`Me apunto: yo puedo poner ${spk.pf.skills[0]}.`,end:true,evidence:evo?evo.evidence:ev.ids,adopt:{who:spk,idea,from:oth}}}
      ctx.props[spk.id]={kind:"project",by:spk};
      return {utt:`Lo veo, pero lo mío va por otro lado: ${spk.pf.project}.`,end:false,evidence:[],pitch:ctx.props[spk.id]};
    }
    const idea=tryBorn(oth,spk);
    if(idea){ctx.born.push(idea);return {utt:`¿Y si juntamos lo tuyo, ${oth.pf.project}, con ${idea.parts[1].text}? Podría salir ${qt(idea.title)}.`,end:false,evidence:[],born:idea}}
    ctx.props[spk.id]={kind:"project",by:spk};
    return {utt:`Lo mío va por otro lado: ${spk.pf.project}; sé de ${spk.pf.skills[0]}.`,end:false,evidence:spk.projNode?[spk.projNode]:[],pitch:ctx.props[spk.id]};
  }
  if(turn===4){
    if(ctx.evo.length){const e=ctx.evo[0];return {utt:e.evo.kind==="referral"?`Buena idea, le busco. Lo apunto como versión ${e.idea.versions.length}.`:`Me gusta. Lo apunto como versión ${e.idea.versions.length}.`,end:true,evidence:[]}}
    if(ctx.born.length){const i=ctx.born[0];bornMemory(spk,oth,i);bornMemory(oth,spk,i);return {utt:"Me gusta. Lo apuntamos y seguimos hablando.",end:true,evidence:[],agree:false}}
    const pb=ctx.props[oth.id];
    if(pb&&pb.kind==="project"){const idea=tryBorn(oth,spk);if(idea){ctx.born.push(idea);return {utt:`Pues mira, ¿y si juntamos ${oth.pf.project} con ${idea.parts[1].text}? Saldría ${qt(idea.title)}.`,end:false,evidence:[],born:idea}}}
    return {utt:"Pues seguimos cada uno con lo suyo.",end:true,evidence:[]};
  }
  if(turn===5){
    if(ctx.born.length){const i=ctx.born[0];bornMemory(spk,oth,i);bornMemory(oth,spk,i);return {utt:"Hecho. Lo apuntamos.",end:true,evidence:[]}}
    return {utt:"Hablamos otro día.",end:true,evidence:[]};
  }
  return {utt:"Hablamos otro día.",end:true,evidence:[]};
}
