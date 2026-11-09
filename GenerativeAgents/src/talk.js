/* =====================================================================
   CONVERSATIONS WITH A MODEL + EPISODIC MEMORY ACROSS RUNS
   When serve.py runs with a Gemini key, each conversation between two active agents is written by the
   model: each agent brings one weekly build or one interest from its people/ file, picked at random,
   plus what it remembers (retrieved from its associative memory) and the ideas in play. The page sends
   that context to serve.py, which owns the prompt (prompts/converse.md) and checks the answer's shape.
   Every finished conversation becomes an episode: a memory chunk saved in data/episodes.jsonl and loaded
   into the agents' memory at the start of later runs, so they pick up earlier threads.
   Without the server, or if a call fails, the template conversation in agents.js runs instead.
   ===================================================================== */
const LLM={server:false,on:false,model:null,pending:0,token:0,fails:0};
let EPISODES=[],runNo=1;
const api=(path,opt)=>fetch(path,opt).then(r=>r.ok?r.json():r.json().catch(()=>({})).then(j=>Promise.reject(new Error(j.error||r.status))));
const postJSON=(path,body)=>api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});

async function llmInit(){
  if(location.protocol==="file:")return;   // the single-file build has no server
  try{const s=await api("/api/status");LLM.server=true;LLM.on=!!s.llm;LLM.model=s.model||null;runNo=(s.runs||0)+1;
    const e=await api("/api/episodes");EPISODES=Array.isArray(e.episodes)?e.episodes:[]}
  catch(e){LLM.server=false;LLM.on=false}
}

/* ---------- what each agent brings: one weekly build or one interest, at random ---------- */
function topicsOf(pf){
  const out=[],noted=new Set();
  for(const b of pf.builds||[])out.push({kind:"weekly build",label:`${b.week} · ${b.title}`,text:b.summary||b.title});
  for(const n of pf.notes||[]){noted.add(n.term);out.push({kind:"research interest",label:n.term,text:n.description})}
  for(const i of pf.interests||[])if(!noted.has(i))out.push({kind:"research interest",label:i,text:i});
  if(!out.length)out.push({kind:"project",label:pf.project,text:pf.project});
  return out;
}
/* memories: the episodes this agent retrieves for the topic and the other person (Generative Agents retrieval) */
function episodeMemories(p,o,topic){
  const R=new_retrieve(p,[topic.text.slice(0,400),who(o)],20),seen=new Set(),out=[];
  for(const f in R)for(const n of R[f].nodes)if(n.episode&&!seen.has(n.node_id)){seen.add(n.node_id);out.push(n)}
  return out.slice(0,3).map(n=>n.episode.text);
}
const epText=ep=>`run ${ep.run}, day ${ep.day} at ${ep.place}: one brought "${ep.topics.a}", the other "${ep.topics.b}". insight: ${ep.insight}${ep.idea?` idea: "${ep.idea.title}".`:""}`;
const pairEpisodes=(a,b)=>EPISODES.filter(e=>(e.a===a.pf.code&&e.b===b.pf.code)||(e.a===b.pf.code&&e.b===a.pf.code)).slice(-3);
const placeEN=id=>SP_EN[id]||SP[id].n;

/* ---------- a conversation: start (pending) → model answer → ideas, memory, episode ---------- */
function startModelTalk(a,b,place){
  const ta=pick(topicsOf(a.pf)),tb=pick(topicsOf(b.pf)),shared=pairEpisodes(a,b);
  const inPlay=IDEAS.filter(i=>i.members.has(a)||i.members.has(b)).map(i=>({id:i.id,title:ideaTitle(i),pitch:(i.llm&&i.llm.pitch)||i.versions[i.versions.length-1].text}));
  const earlier=[];for(const e of [...shared,...EPISODES.filter(e=>e.idea&&(e.a===a.pf.code||e.b===a.pf.code||e.a===b.pf.code||e.b===b.pf.code)).slice(-4)])
    if(e.idea&&e.run<runNo&&!earlier.some(x=>x.id===e.idea.id))earlier.push({id:e.idea.id,title:e.idea.title,pitch:`from an earlier run (run ${e.run}): ${e.insight}`});
  const side=(p,o,t)=>({project:p.pf.project,skills:p.pf.skills,interests:p.pf.interests,topic:{kind:t.kind,title:t.label,text:t.text},memories:episodeMemories(p,o,t)});
  const ctx={lang,place:placeEN(place),time:clock(),A:side(a,b,ta),B:side(b,a,tb),shared_history:shared.map(epText),ideas:[...inPlay,...earlier.slice(0,4)]};
  const c={clk:clock(),day,place,a,b,lines:[],start:simT,shown:0,born:[],adopt:[],evo:[],agree:false,pending:true,topics:{a:ta.label,b:tb.label},followup:shared.length>0};  // the same two talked before, in this run or an earlier one
  convs.unshift(c);if(convs.length>80)convs.pop();dirtyConv=true;
  const token=LLM.token;LLM.pending++;
  postJSON("/api/converse",ctx).then(res=>{if(token!==LLM.token)return;finishModelTalk(c,res,ctx)})
    .catch(err=>{if(token!==LLM.token)return;LLM.fails++;console.warn("model conversation failed, using a template:",err.message);
      const i=convs.indexOf(c);if(i>=0)convs.splice(i,1);
      const dur=templateTalk(a,b,place);[a,b].forEach(p=>{if(p.state==="talk"){p.timer=dur;p.scratch.chatting_end_time=simT+dur}})})
    .finally(()=>{if(token===LLM.token)LLM.pending=Math.max(0,LLM.pending-1);dirtyConv=true});
  return 1e9; // the pair stands talking until the answer arrives
}
function newIdeaLLM(a,b,title,pitch,place,lineage){
  const c=spc3(place);
  const idea={id:"i"+(++ideaN),title,parts:[{a,text:a.pf.project},{a:b,text:b.pf.project}],by:[a,b],members:new Set([a,b]),born:{t:simT,day,clk:clock(),place,x:c.x,z:c.z},mentions:0,
    tags:[...new Set([...a.pf.interests,...b.pf.interests])],llm:{title,pitch},lineage:lineage||null,
    versions:[{n:1,kind:"born",t:simT,clk:clock(),place,by:[a,b],text:pitch,evidence:[]}],wanted:new Map()};
  IDEAS.push(idea);return idea;
}
function finishModelTalk(c,res,ctx){
  const {a,b,place}=c,lines=res.lines.map(l=>({w:l.speaker==="A"?a:b,t:l.text,evidence:[],pitch:null,born:null,adopt:null,agree:false,evo:null,llm:true}));
  let idea=null,out="none";
  if(res.outcome==="build_on"){
    const cur=IDEAS.find(i=>i.id===res.builds_on);
    if(cur){idea=cur;out="evo";cur.llm=cur.llm||{title:ideaTitle(cur),pitch:""};if(res.idea_title)cur.llm.title=res.idea_title;cur.llm.pitch=res.idea_pitch;
      evolveIdea(cur,{kind:"llm",text:res.idea_pitch,evidence:[]},a,b);c.evo.push({idea:cur,evo:{kind:"llm"},by:a});
      for(const [p,o] of [[a,b],[b,a]])if(!cur.members.has(p)){joinIdea(p,cur,o);c.adopt.push({who:p,idea:cur,from:o})}}
    else{const prior=ctx.ideas.find(i=>i.id===res.builds_on);idea=newIdeaLLM(a,b,res.idea_title,res.idea_pitch,place,prior?{id:prior.id,title:prior.title}:null);out="born";c.born.push(idea)}
  }else if(res.outcome==="new_idea"){idea=newIdeaLLM(a,b,res.idea_title,res.idea_pitch,place,null);out="born";c.born.push(idea)}
  if(out==="born"){bornMemory(a,b,idea);bornMemory(b,a,idea);lines[lines.length-1].born=idea}
  Object.assign(c,{lines,insight:res.insight,pending:false,start:simT,shown:0});dirtyConv=true;
  CLOG.push({t:simT,day:c.day,clk:c.clk,place,out,mine:a.user||b.user,a,b,idea,insight:res.insight,topics:c.topics,followup:c.followup,llm:true,lines});
  // memory: the conversation (chat), its insight as an episode thought, and the usual plan + memo
  const ep={id:`r${runNo}-c${CLOG.length}`,run:runNo,day:c.day,clk:c.clk.replace(/^d\d+ /,""),place:placeEN(place),a:a.pf.code,b:b.pf.code,topics:c.topics,insight:res.insight,
    idea:idea?{id:`r${runNo}-${idea.id}`,title:ideaTitle(idea)}:null,outcome:res.outcome,lang};
  for(const [p,o] of [[a,b],[b,a]]){
    const mine=p===a?c.topics.a:c.topics.b,theirs=p===a?c.topics.b:c.topics.a;
    const d=`Hablé con ${who(o)} en ${SP[place].n}; «${mine}» × «${theirs}».`;
    const node=p.a_mem.add_chat(simT,null,who(p),"chat with",who(o),d,[who(p),who(o),...(idea?[qt(ideaTitle(idea))]:[])],out==="none"?5:8,[d,LLM_embedding(d)],lines.map(l=>[who(l.w),l.t]));
    p.scratch.importance_trigger_curr-=node.poignancy;p.scratch.importance_ele_n+=1;
    addEpisodeNode(p,o,ep,[node.node_id]);
    reflect_on_convo(p,o,node,{adopt:c.adopt,props:{},agree:false,born:c.born,evo:c.evo});
  }
  EPISODES.push(ep);if(LLM.server)postJSON("/api/episodes",{episodes:[ep]}).catch(()=>{});
  // each line stays up long enough to read: about 20 characters per simulated second, at least LINE_T
  let t=0;c.ends=lines.map(l=>t+=Math.max(LINE_T,l.t.length/20));const dur=t+1;
  for(const p of [a,b])if(p.state==="talk"&&p.conv===c){p.timer=dur;p.scratch.chatting_end_time=simT+dur}
  dirtyMem=true;
}
/* an episode as a thought in the agent's memory: retrievable by topic words and by the other person */
function addEpisodeNode(p,o,ep,filling){
  const t=`${cap(who(o))} · r${ep.run} ${ep.clk} · ${ep.insight}`;
  const node=p.a_mem.add_thought(simT,null,who(p),"recuerda",who(o),t,[who(o),"episodio",...(ep.idea?[qt(ep.idea.title)]:[])],7,[t+" "+ep.topics.a+" "+ep.topics.b,LLM_embedding(t+" "+ep.topics.a+" "+ep.topics.b)],filling||[]);
  node.episode={id:ep.id,text:epText(ep)};return node;
}
/* at the start of a run: every earlier episode between two agents on the floor becomes a memory for both */
function seedEpisodes(){
  const byCode=new Map(agents.filter(a=>a.active).map(a=>[a.pf.code,a]));
  for(const ep of EPISODES){if(ep.run>=runNo)continue;const A=byCode.get(ep.a),B=byCode.get(ep.b);if(!A||!B)continue;addEpisodeNode(A,B,ep);addEpisodeNode(B,A,ep)}
}
async function forgetEpisodes(){EPISODES=[];if(LLM.server)await api("/api/episodes",{method:"DELETE"}).catch(()=>{})}
const lineText=l=>l.llm?l.t:tr(l.t);
