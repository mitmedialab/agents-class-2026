/* =====================================================================
   CAMERA AVATAR. Privacy by construction: the video element is never added to the page, each frame is
   drawn straight into a 40 × 30 canvas that is never shown, and from those 1,200 pixels only the
   avatar is kept: skin, hair and shirt snapped to the avatar palettes, a 7 × 5 face grid in four tones
   (skin, shade, dark, hair) and a one-pixel head tilt. The preview shows that avatar, nothing else.
   No frame is stored or sent anywhere; closing the panel stops the camera.
   ===================================================================== */
const CAM={stream:null,video:null,timer:0,cv:null,base:null,onKeep:null,av:null,dx:0,col:null,hist:[]};
const CW=40,CH=30,FPS=10;
const rgbOf=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
const nearest=(pal,c)=>{let best=0,bd=1e9;pal.forEach((h,i)=>{const p=rgbOf(h),d=(p[0]-c[0])**2+(p[1]-c[1])**2+(p[2]-c[2])**2;if(d<bd){bd=d;best=i}});return best};
const lum=c=>.299*c[0]+.587*c[1]+.114*c[2];
function isSkin(r,g,b){const y=.299*r+.587*g+.114*b,cb=128-.168736*r-.331264*g+.5*b,cr=128+.5*r-.418688*g-.081312*b;return y>45&&cr>=135&&cr<=180&&cb>=80&&cb<=135}

async function camOpen(base,onKeep){
  camClose();CAM.base={...base};CAM.onKeep=onKeep;CAM.hist=[];CAM.col=null;CAM.av={...base};CAM.dx=0;
  const box=$("cam");box.hidden=false;$("cam-msg").textContent=L2("camHint");
  [["t-camnote","camNote"],["t-camkeep","camKeep"],["t-camcancel","camCancel"],["t-camlive","camLive"]].forEach(([id,k])=>$(id).textContent=L2(k));
  drawCam();
  try{
    CAM.stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:320},height:{ideal:240},facingMode:"user"},audio:false});
    const v=document.createElement("video");v.muted=true;v.playsInline=true;v.srcObject=CAM.stream;await v.play();CAM.video=v;   // never added to the DOM
    CAM.cv=document.createElement("canvas");CAM.cv.width=CW;CAM.cv.height=CH;
    CAM.timer=setInterval(camFrame,1000/FPS);
  }catch(e){$("cam-msg").textContent=L2("camFail")+(e&&e.message||e);camStop()}
}
function camStop(){clearInterval(CAM.timer);CAM.timer=0;if(CAM.stream)CAM.stream.getTracks().forEach(t=>t.stop());CAM.stream=null;if(CAM.video){CAM.video.srcObject=null;CAM.video=null}CAM.cv=null}
function camClose(){camStop();const box=$("cam");if(box)box.hidden=true}
function camFrame(){
  const v=CAM.video;if(!v||!v.videoWidth)return;
  const g=CAM.cv.getContext("2d",{willReadFrequently:true}),vw=v.videoWidth,vh=v.videoHeight,sw=Math.min(vw,vh*CW/CH),sh=sw*CH/CW;
  g.save();g.scale(-1,1);g.drawImage(v,(vw-sw)/2,(vh-sh)/2,sw,sh,-CW,0,CW,CH);g.restore();   // mirrored, like a mirror
  const d=g.getImageData(0,0,CW,CH).data,px=(x,y)=>{const i=(y*CW+x)*4;return [d[i],d[i+1],d[i+2]]};
  // where the face is: the skin-colored pixels in the middle of the frame
  let n=0,sx=0,sy=0,sxx=0,syy=0;const skin=[0,0,0];
  for(let y=0;y<CH;y++)for(let x=Math.floor(CW*.12);x<Math.ceil(CW*.88);x++){const c=px(x,y);if(isSkin(...c)){n++;sx+=x;sy+=y;sxx+=x*x;syy+=y*y;skin[0]+=c[0];skin[1]+=c[1];skin[2]+=c[2]}}
  let cx=CW/2,cy=CH*.42,w=CW*.36;
  if(n>=15){cx=sx/n;cy=sy/n;w=Math.max(CW*.2,Math.min(CW*.6,3.4*Math.sqrt(Math.max(1,sxx/n-cx*cx))))}
  const h=w*1.3,x0=cx-w/2,y0=cy-h*.48,avg=(xa,xb,ya,yb,keep)=>{const s=[0,0,0];let k=0;
    for(let y=Math.max(0,Math.floor(ya));y<Math.min(CH,Math.ceil(yb));y++)for(let x=Math.max(0,Math.floor(xa));x<Math.min(CW,Math.ceil(xb));x++){const c=px(x,y);if(!keep||keep(c)){s[0]+=c[0];s[1]+=c[1];s[2]+=c[2];k++}}
    return k?s.map(v=>v/k):null};
  const sk=n>=15?skin.map(v=>v/n):avg(x0+w*.3,x0+w*.7,y0+h*.45,y0+h*.7),
    hair=avg(x0+w*.15,x0+w*.85,y0-h*.12,y0+h*.12,c=>!isSkin(...c))||(CAM.col&&CAM.col.hair),
    shirt=avg(cx-w*.6,cx+w*.6,y0+h*1.12,CH)||(CAM.col&&CAM.col.shirt);
  const ema=(o,c)=>!o?c:c?o.map((v,i)=>v*.7+c[i]*.3):o;
  CAM.col={skin:ema(CAM.col&&CAM.col.skin,sk),hair:ema(CAM.col&&CAM.col.hair,hair),shirt:ema(CAM.col&&CAM.col.shirt,shirt)};
  // the face grid: 7 × 5 cells over the face box, each one skin, shade, dark or hair by its brightness against the skin
  const ys=Math.max(30,lum(CAM.col.skin||[180,140,120])),bands=[.06,.24,.40,.56,.72,.94];let face="";
  for(let r=0;r<FACE_H;r++)for(let k=0;k<FACE_W;k++){
    const c=avg(x0+w*k/FACE_W,x0+w*(k+1)/FACE_W,y0+h*bands[r],y0+h*bands[r+1]);
    if(!c){face+="s";continue}const ratio=lum(c)/ys;
    face+=r===0&&!isSkin(...c)&&ratio<.8?"h":ratio<.6?"e":ratio<.84?"d":"s"}
  CAM.hist.push(face);if(CAM.hist.length>4)CAM.hist.shift();
  let f="";for(let i=0;i<face.length;i++){const cnt={};for(const s of CAM.hist)cnt[s[i]]=(cnt[s[i]]||0)+1;f+=Object.entries(cnt).sort((a,b)=>b[1]-a[1])[0][0]}
  if(!/e/.test(f.slice(14,21)))f=f.slice(0,15)+"e"+f.slice(16,19)+"e"+f.slice(20);   // keep two eyes even in flat light
  CAM.dx=cx<CW*.4?-1:cx>CW*.6?1:0;
  CAM.av={...CAM.base,s:CAM.col.skin?nearest(SKIN,CAM.col.skin):CAM.base.s,h:CAM.col.hair?nearest(HAIR,CAM.col.hair):CAM.base.h,t:CAM.col.shirt?nearest(SHIRT,CAM.col.shirt):CAM.base.t,face:f};
  $("cam-msg").textContent=n>=15?"":L2("camHint");
  drawCam();
}
function drawCam(){const c=$("cam-view");if(c&&CAM.av)paintRows(c,avatarRows(CAM.av,0,CAM.dx),avatarPal(CAM.av),8)}
$("cam-keep").addEventListener("click",()=>{const av={...CAM.av};camClose();if(CAM.onKeep)CAM.onKeep(av)});
$("cam-cancel").addEventListener("click",camClose);
document.addEventListener("visibilitychange",()=>{if(document.hidden)camClose()});
