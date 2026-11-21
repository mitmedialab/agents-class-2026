/* =====================================================================
   OFFLINE CONVERSATIONS: fixed rules instead of a model, for when Gemini is not available (no serve.py,
   no key, the single-file build, or a failed call). localConverse takes the same context the page sends
   to serve.py (prompts/converse.md) and returns the same shape: lines, insight, outcome, idea. So the
   cards, insights, ideas, episodic memory across runs and the newsletter all work without AI.
   The rules: each agent says what it brought (first sentence of its weekly build or interest), the two
   pieces meet on their longest shared word, the listener offers one of its skills, and the insight says
   so. Whether an idea is born or an earlier one moves on depends on that overlap and on a hash of the
   inputs, so the same inputs always give the same conversation.
   ===================================================================== */
const OFF_STOP=new Set(("the and for with that this from into over what when where which while about their there these those have has had "+
  "been being were will would could should them they then than more most also only each such some other using used uses through between "+
  "what your yours ours mine week built build building agent agents user users people person based like just very much many make made "+
  "whether without within after before every across around because both into onto upon still even again once first last next same "+
  "here thing things way ways part parts kind lot lots able real data "+
  "una para con los las del que por como sus más entre sobre esta este").split(" "));
const offWords=s=>(String(s||"").toLowerCase().match(/[a-záéíóúñü][a-z0-9áéíóúñü-]{3,}/g)||[]).filter(w=>!OFF_STOP.has(w));
const offHash=s=>{let h=2166136261;for(const ch of String(s)){h^=ch.charCodeAt(0);h=Math.imul(h,16777619)}return (h>>>0)/4294967296};
const offFirst=(t,n=150)=>{const s=String(t||"").split(/(?<=[.!?])\s+/)[0].trim();return s.length<=n?s:s.slice(0,n).replace(/\s+\S*$/,"")+"…"};
const offTitle=t=>String(t||"").replace(/^W\d+\s*·\s*/,"").trim();
// a short name for repeated mentions: the part before a colon ("Liminal", "City Agents"), else the first words
const offRef=(t,n=5)=>{const s=offTitle(t),c=s.indexOf(":");if(c>1)return s.slice(0,c).trim();const w=s.split(/\s+/);return w.length>n?w.slice(0,n).join(" ").replace(/[,.;:]$/,""):s};
const offCap=s=>s.charAt(0).toUpperCase()+s.slice(1);

/* the shared word: longest term (or interest phrase) found in both pieces of work */
function offCommon(A,B){
  const text=s=>`${s.topic.title} ${s.topic.text} ${s.project}`.toLowerCase();
  const ta=text(A),tb=text(B);
  const phrases=[...A.interests,...B.interests].map(x=>x.toLowerCase()).filter(p=>p.length>3&&!OFF_STOP.has(p)&&ta.includes(p)&&tb.includes(p));
  if(phrases.length)return phrases.sort((x,y)=>y.length-x.length)[0];
  const wb=new Set(offWords(tb));
  return offWords(ta).filter(w=>wb.has(w)).sort((x,y)=>y.length-x.length||x.localeCompare(y))[0]||null;
}
const OFF_T={
  en:{open:(k,t,s)=>k==="weekly build"?`This week I built ${t}.${s?" "+s:""}`:k==="research interest"?`I keep coming back to ${t}.${s?" "+s:""}`:`I'm working on ${t}.`,
      again:(ins,t,s)=>`Last time we landed on this: ${ins} Since then I've been on ${t}.${s?" "+s:""}`,
      reply:(k,t,s)=>k==="weekly build"?`On my side: ${t}.${s?" "+s:""}`:k==="research interest"?`For me it's ${t}.${s?" "+s:""}`:`Mine is ${t}.`,
      meet:w=>w?`Both of those come down to ${w}.`:null,wonder:(t,p)=>`I wonder what ${t} would look like inside ${p}.`,
      offer:(w,sk)=>w?`Then ${w} is our common ground. I could bring ${sk} to it.`:`I could bring ${sk} to that.`,
      closeNew:t=>`Let's sketch it: ${t}.`,closeOn:t=>`That fits «${t}». Let's fold it in.`,closeNone:"I'll think about it and tell you next time.",
      insight:(w,a,b,sk)=>w?`${w.charAt(0).toUpperCase()+w.slice(1)} links ${a} and ${b}: ${sk} from one could be tried on the other.`:`${a} and ${b} could meet through ${sk}.`,
      pitch:(sk,a,b)=>`Apply ${sk} to ${a}, using what ${b} already shows. First step: try it on one session of real data.`,
      pitchOn:(b,sk)=>`This version brings in ${b}: ${sk} joins the idea. First step: a small test with both setups.`,skill:"what I know"},
  es:{open:(k,t,s)=>k==="weekly build"?`Esta semana he hecho ${t}.${s?" "+s:""}`:k==="research interest"?`Le sigo dando vueltas a ${t}.${s?" "+s:""}`:`Estoy con ${t}.`,
      again:(ins,t,s)=>`La otra vez llegamos a esto: ${ins} Desde entonces estoy con ${t}.${s?" "+s:""}`,
      reply:(k,t,s)=>k==="weekly build"?`Por mi lado: ${t}.${s?" "+s:""}`:k==="research interest"?`Lo mío es ${t}.${s?" "+s:""}`:`Lo mío es ${t}.`,
      meet:w=>w?`Las dos cosas van de ${w}.`:null,wonder:(t,p)=>`Me pregunto cómo encajaría ${t} en ${p}.`,
      offer:(w,sk)=>w?`Entonces ${w} es el terreno común. Yo podría aportar ${sk}.`:`Yo podría aportar ${sk}.`,
      closeNew:t=>`Hagamos un boceto: ${t}.`,closeOn:t=>`Eso encaja con «${t}»: sumémoslo.`,closeNone:"Lo pienso y te cuento la próxima vez.",
      insight:(w,a,b,sk)=>w?`${w.charAt(0).toUpperCase()+w.slice(1)} une ${a} y ${b}: ${sk} se podría probar en el otro lado.`:`${a} y ${b} podrían cruzarse a través de ${sk}.`,
      pitch:(sk,a,b)=>`Aplicar ${sk} a ${a}, con lo que ya muestra ${b}. Primer paso: probarlo con una sesión de datos reales.`,
      pitchOn:(b,sk)=>`Esta versión incorpora ${b}: ${sk} entra en la idea. Primer paso: una prueba pequeña con los dos montajes.`,skill:"lo que sé"}
};
/* ctx: the context sent to serve.py; last: the pair's most recent earlier episode, if any */
function localConverse(ctx,last){
  const T=OFF_T[ctx.lang]||OFF_T.en,A=ctx.A,B=ctx.B;
  const ta=offTitle(A.topic.title),tb=offTitle(B.topic.title),ra=offRef(ta),rb=offRef(tb);
  const said=s=>s.topic.text&&offTitle(s.topic.text)!==offTitle(s.topic.title)?offFirst(s.topic.text,140):"",sa=said(A),sb=said(B);
  const common=offCommon(A,B),skill=B.skills&&B.skills[0]||T.skill,h=offHash(`${A.topic.title}|${B.topic.title}|${(ctx.shared_history||[]).length}`);
  // an idea in play that this conversation touches: the pair's last idea, or one whose title shares a word with the topics
  const words=new Set([...offWords(ta),...offWords(tb),...(common?offWords(common):[])]);
  const near=(ctx.ideas||[]).find(i=>last&&last.idea&&(i.id===last.idea.id||i.title===last.idea.title))||(ctx.ideas||[]).find(i=>offWords(i.title).some(w=>words.has(w)));
  let outcome="none",title="",pitch="",builds_on="";
  if(near&&h<.5){outcome="build_on";builds_on=near.id;title=near.title;pitch=T.pitchOn(rb,skill)}
  else if(common?h<.5:h<.25){outcome="new_idea";title=`${ra} × ${rb}`;pitch=T.pitch(skill,ra,rb)}
  const lines=[{speaker:"A",text:last&&last.insight?T.again(offFirst(last.insight,140),ta,sa):T.open(A.topic.kind,ta,sa)},
    {speaker:"B",text:T.reply(B.topic.kind,tb,sb)},
    {speaker:"A",text:T.meet(common)||T.wonder(ra,offRef(B.project,6))},
    {speaker:"B",text:T.offer(common,skill)},
    {speaker:"A",text:outcome==="new_idea"?T.closeNew(title):outcome==="build_on"?T.closeOn(title):T.closeNone}];
  return {lines,insight:offCap(T.insight(common,ra,rb,skill)),outcome,idea_title:title,idea_pitch:pitch,builds_on};
}
