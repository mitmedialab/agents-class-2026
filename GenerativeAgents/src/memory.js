/* ---------- utilidades de texto ---------- */
const STOP=new Set("de la el en por a y que con se una un las los al del está es hacia junto para lo le su sus mi me yo tú ya no sí hay ha he como más muy pero o si ni esta este ese esa eso esto aquí ahí allí ahora hoy".split(" "));
const tokens=t=>t.toLowerCase().replace(/[¿?¡!.,;:«»"()]/g," ").split(/\s+/).filter(w=>w&&!STOP.has(w));
const SHIRTN=["azul","roja","verde","amarilla","morada","rosa","turquesa","blanca","negra","naranja"],HAIRN=["pelo negro","pelo castaño oscuro","pelo castaño","pelo rubio","pelo rojizo","pelo azul","pelo gris","pelo blanco"],PANTSN=["pantalón azul marino","pantalón gris","pantalón marrón","pantalón azul","pantalón gris claro","pantalón verde"];
const who=a=>a.label;
const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);

/* ---------- reloj ---------- */
let simT=0,day=1,dayStart=0;
const DAY_LEN=1620; // 09:00 → 18:00 a 20 s de reloj por segundo de simulación
const hhmm=()=>{const m=540+Math.floor((simT-dayStart)/3);return `${String(Math.floor(m/60)%24).padStart(2,"0")}:${String(m%60).padStart(2,"0")}`};
const clock=()=>`d${day} ${hhmm()}`;

/* ---------- associative_memory.py ---------- */
class ConceptNode{
  constructor(node_id,node_count,type_count,type,depth,created,expiration,s,p,o,description,embedding_key,poignancy,keywords,filling){
    Object.assign(this,{node_id,node_count,type_count,type,depth,created,expiration,subject:s,predicate:p,object:o,description,embedding_key,poignancy,keywords,filling});
    this.last_accessed=created;this.clk=clock();
  }
  spo_summary(){return [this.subject,this.predicate,this.object]}
}
class AssociativeMemory{
  constructor(){
    this.id_to_node={};this.seq_event=[];this.seq_thought=[];this.seq_chat=[];
    this.kw_to_event={};this.kw_to_thought={};this.kw_to_chat={};
    this.kw_strength_event={};this.kw_strength_thought={};this.embeddings={};
  }
  _add(type,created,expiration,s,p,o,description,keywords,poignancy,embedding_pair,filling){
    const node_count=Object.keys(this.id_to_node).length+1;
    const seq={event:this.seq_event,thought:this.seq_thought,chat:this.seq_chat}[type];
    const type_count=seq.length+1,node_id=`node_${node_count}`;
    let depth=0;
    if(type==="thought"){depth=1;try{if(filling&&filling.length)depth=1+Math.max(...filling.map(id=>this.id_to_node[id].depth))}catch(e){depth=1}}
    const node=new ConceptNode(node_id,node_count,type_count,type,depth,created,expiration,s,p,o,description,embedding_pair[0],poignancy,keywords,filling||[]);
    seq.unshift(node);
    const kw_to={event:this.kw_to_event,thought:this.kw_to_thought,chat:this.kw_to_chat}[type];
    for(const kw0 of keywords){const kw=kw0.toLowerCase();(kw_to[kw]=kw_to[kw]||[]).unshift(node)}
    if(type!=="chat"&&!(p==="is idle"||o==="idle")){const ks=type==="event"?this.kw_strength_event:this.kw_strength_thought;for(const kw0 of keywords){const kw=kw0.toLowerCase();ks[kw]=(ks[kw]||0)+1}}
    this.embeddings[embedding_pair[0]]=embedding_pair[1];
    this.id_to_node[node_id]=node;
    return node;
  }
  add_event(...a){return this._add("event",...a)}
  add_thought(...a){return this._add("thought",...a)}
  add_chat(...a){return this._add("chat",...a)}
  get_summarized_latest_events(retention){return new Set(this.seq_event.slice(0,retention).map(n=>n.spo_summary().join("|")))}
  get_last_chat(target){const l=this.kw_to_chat[target.toLowerCase()];return l&&l.length?l[0]:false}
  retrieve_relevant_thoughts(s,p,o){const out=new Set();[s,p,o].forEach(i=>{const k=i.toLowerCase();if(this.kw_to_thought[k])this.kw_to_thought[k].forEach(n=>out.add(n))});return out}
}

/* ---------- scratch.py ---------- */
class Scratch{
  constructor(){
    this.vision_r=4;this.att_bandwidth=3;this.retention=5;
    this.importance_trigger_max=100;this.importance_trigger_curr=this.importance_trigger_max;this.importance_ele_n=0;
    this.recency_w=1;this.relevance_w=1;this.importance_w=1;this.recency_decay=0.99;this.thought_count=5;
    this.act_description="";this.act_event=null;
    this.chatting_with=null;this.chat=null;this.chatting_with_buffer={};this.chatting_end_time=null;
  }
}

/* ---------- retrieve.py :: new_retrieve ---------- */
const cosine=(a,b)=>{let d=0,na=0,nb=0;for(const [k,v] of a){na+=v*v;if(b.has(k))d+=v*b.get(k)}for(const v of b.values())nb+=v*v;return na&&nb?d/Math.sqrt(na*nb):0};
function normalize_dict_floats(d,lo=0,hi=1){const vs=Object.values(d);if(!vs.length)return d;const mn=Math.min(...vs),mx=Math.max(...vs);for(const k in d)d[k]=mx===mn?(hi-lo)/2:(d[k]-mn)/(mx-mn)*(hi-lo)+lo;return d}
function top_highest_x_values(d,x){return Object.fromEntries(Object.entries(d).sort((a,b)=>b[1]-a[1]).slice(0,x))}
function new_retrieve(persona,focal_points,n_count=30){
  const retrieved={};
  for(const focal of focal_points){
    const nodes=[...persona.a_mem.seq_event.slice(0,500),...persona.a_mem.seq_thought.slice(0,300)].filter(n=>!n.embedding_key.includes("idle")).sort((a,b)=>a.last_accessed-b.last_accessed);
    if(!nodes.length){retrieved[focal]={nodes:[],scores:{}};continue}
    // recencia: el último accedido es el más reciente (el paper usa decay^rank sobre la lista ordenada por last_accessed)
    const rec={},imp={},rel={},fe=LLM_embedding(focal);
    nodes.forEach((n,i)=>{rec[n.node_id]=Math.pow(persona.scratch.recency_decay,nodes.length-i);imp[n.node_id]=n.poignancy;rel[n.node_id]=cosine(fe,persona.a_mem.embeddings[n.embedding_key]||new Map())});
    normalize_dict_floats(rec);normalize_dict_floats(imp);normalize_dict_floats(rel);
    const gw=[0.5,3,2],master={};
    for(const n of nodes)master[n.node_id]=persona.scratch.recency_w*rec[n.node_id]*gw[0]+persona.scratch.relevance_w*rel[n.node_id]*gw[1]+persona.scratch.importance_w*imp[n.node_id]*gw[2];
    const top=top_highest_x_values(master,n_count);
    const out=Object.keys(top).map(id=>persona.a_mem.id_to_node[id]);
    out.forEach(n=>n.last_accessed=simT);
    retrieved[focal]={nodes:out,scores:top};
  }
  return retrieved;
}

/* ---------- perceive.py ---------- */
function perceive(persona){
  const s=persona.scratch,here=placeOf(persona.x,persona.z);
  // s_mem: memoria espacial (mundo → sector → arena → objetos)
  persona.s_mem.add(here);
  // eventos cercanos dentro de vision_r y en la misma "arena" (lugar), ordenados por distancia
  const cand=[];
  for(const o of agents){if(o===persona||!o.onFloor)continue;const d=Math.hypot(o.x-persona.x,o.z-persona.z);if(d<=s.vision_r&&(placeOf(o.x,o.z)===here||d<1.5)&&o.scratch.act_event)cand.push({d,ev:o.scratch.act_event})}
  cand.sort((a,b)=>a.d-b.d);
  const seen=new Set(),latest=persona.a_mem.get_summarized_latest_events(s.retention),ret=[];
  for(const {ev} of cand.slice(0,s.att_bandwidth)){
    const [sub,pred,obj,desc]=ev,key=[sub,pred,obj].join("|");
    if(seen.has(key)||latest.has(key))continue;seen.add(key);
    const keywords=[sub,obj].filter(Boolean);
    const poig=LLM_poignancy_event(desc),emb=[desc,LLM_embedding(desc)];
    const node=persona.a_mem.add_event(simT,null,sub,pred,obj,desc,keywords,poig,emb,[]);
    s.importance_trigger_curr-=poig;s.importance_ele_n+=1;ret.push(node);
  }
  if(ret.length)dirtyMem=true;
  return ret;
}
// un acontecimiento propio importante también entra en el flujo
function own_event(persona,pred,obj,desc){
  const s=persona.scratch,poig=LLM_poignancy_event(desc);
  const node=persona.a_mem.add_event(simT,null,who(persona),pred,obj,desc,[who(persona),obj],poig,[desc,LLM_embedding(desc)],[]);
  s.importance_trigger_curr-=poig;s.importance_ele_n+=1;dirtyMem=true;return node;
}

/* ---------- reflect.py ---------- */
function reflection_trigger(persona){const s=persona.scratch;return s.importance_trigger_curr<=0&&(persona.a_mem.seq_event.length+persona.a_mem.seq_thought.length)>0}
function reset_reflection_counter(persona){persona.scratch.importance_trigger_curr=persona.scratch.importance_trigger_max;persona.scratch.importance_ele_n=0}
function generate_focal_points(persona,n=3){
  const nodes=[...persona.a_mem.seq_event,...persona.a_mem.seq_thought].filter(x=>!x.embedding_key.includes("idle")).sort((a,b)=>a.last_accessed-b.last_accessed);
  const statements=nodes.slice(-persona.scratch.importance_ele_n);
  return LLM_focal_points(persona,statements,n);
}
function generate_insights_and_evidence(persona,nodes,n=5,focal=""){
  // el prompt numera las afirmaciones y pide "insight (because of 1, 5, 3)"; aquí devolvemos {insight: [node_ids]}
  const numbered=nodes.map((nd,i)=>({i:i+1,nd}));
  return LLM_insights(persona,numbered,n,focal);
}
function run_reflect(persona){
  const focal_pts=generate_focal_points(persona,3),record={clk:clock(),qs:[]};
  const retrieved=new_retrieve(persona,focal_pts,30);
  for(const focal of focal_pts){
    const nodes=retrieved[focal].nodes,thoughts=generate_insights_and_evidence(persona,nodes,5,focal),q={q:focal,insights:[]};
    for(const [thought,evidence] of thoughts){
      const [s,p,o]=LLM_triple(persona,thought),poig=LLM_poignancy_thought(thought),emb=[thought,LLM_embedding(thought)];
      const node=persona.a_mem.add_thought(simT,simT+30*24*60,s,p,o,thought,[s,o],poig,emb,evidence);
      q.insights.push({text:thought,ev:evidence,id:node.node_id});
    }
    record.qs.push(q);
  }
  persona.reflections.unshift(record);if(persona.reflections.length>12)persona.reflections.pop();
  reset_reflection_counter(persona);dirtyMem=true;
}
function reflect(persona){if(reflection_trigger(persona))run_reflect(persona)}
// al terminar una conversación: pensamiento de planificación + memo (reflect.py, bloque chatting_end_time)
function reflect_on_convo(persona,other,chatNode,outcome){
  const [plan,memo]=LLM_thoughts_on_convo(persona,other,chatNode,outcome);
  persona.lastStored={clk:clock(),items:[chatNode.description,plan,memo].filter(Boolean)};
  for(const t of [plan,memo]){if(!t)continue;const [s,p,o]=LLM_triple(persona,t);persona.a_mem.add_thought(simT,simT+30*24*60,s,p,o,t,[s,o],LLM_poignancy_thought(t),[t,LLM_embedding(t)],[chatNode.node_id])}
  dirtyMem=true;
}

/* ---------- converse.py :: agent_chat_v2 ---------- */
function generate_summarize_agent_relationship(persona,other){
  const r=new_retrieve(persona,[who(other)],50)[who(other)].nodes;
  const chats=r.filter(n=>n.type==="chat").length;
  return chats?`${cap(who(other))} y yo ya hemos hablado ${chats===1?"una vez":chats+" veces"} de nuestros proyectos.`:`A ${who(other)} apenas la conozco.`;
}
function agent_chat_v2(init_persona,target_persona){
  const curr_chat=[],ctx={props:{},adopt:[],agree:false,born:[]};
  let a=init_persona,b=target_persona;
  for(let round=0;round<8;round++){
    for(const [spk,oth] of [[a,b],[b,a]]){
      const rel=generate_summarize_agent_relationship(spk,oth);
      const last_chat=curr_chat.slice(-4).map(([w,t])=>`${w}: ${t}`).join("\n");
      const focal=[rel,oth.scratch.act_description];if(last_chat)focal.push(last_chat);
      const retrieved=new_retrieve(spk,focal,15);
      spk.lastRetrieval={clk:clock(),focal:focal.slice(0,2),nodes:Object.values(retrieved).flatMap(r=>r.nodes.map(n=>[n,r.scores[n.node_id]])).sort((x,y)=>y[1]-x[1]).filter((x,i,arr)=>arr.findIndex(y=>y[0]===x[0])===i).slice(0,5)};
      const res=LLM_utterance(spk,oth,retrieved,curr_chat,ctx);
      spk.lastUtt={clk:clock(),t:res.utt,ev:res.evidence||[]};
      curr_chat.push([who(spk),res.utt,spk,res.evidence,res]);
      if(res.end)return {chat:curr_chat,ctx};
    }
  }
  return {chat:curr_chat,ctx};
}

