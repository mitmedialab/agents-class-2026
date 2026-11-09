// plan: WALLS, CORR y PLANTEX vienen de src/data/plan.js

const S=.1,W=(x,y)=>({x:(x-400)*S,z:(y-170)*S}),PX=(x,z)=>[x/S+400,z/S+170];
const rnd=(a,b)=>a+Math.random()*(b-a),pick=a=>a[Math.floor(Math.random()*a.length)];
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ZONES={
  humdyn:{r:[208,105,258,156],door:[243,170],b:"E15",n:"Human Dynamics"},
  city:{r:[262,105,328,165],door:[295,170],b:"E15",n:"City Science"},
  sculpt:{r:[330,105,375,165],door:[352,170],b:"E15",n:"Sculpting Evolution"},
  biotech:{r:[303,172,330,190],door:[340,180],b:"E15",n:"Community Biotech"},
  socalg:{r:[245,86,300,104],door:[270,108],b:"E15",n:"Social Algorithms"},
  multisens:{r:[192,180,207,205],door:[212,192],b:"E15",n:"Multisensory Intelligence"},
  facilities:{r:[195,230,232,262],door:[234,246],b:"E15",n:"Facilities"},
  nagashima:{r:[305,195,338,236],door:[340,216],b:"E15",n:"la sala 341"},
  cafe:{r:[428,148,468,178],door:[452,146],b:"E14",n:"la cafetería"},
  atrium:{r:[472,140,524,205],door:[470,150],b:"E14",n:"el atrio"},
  biomech:{r:[474,78,514,122],door:[494,131],b:"E14",n:"Biomechatronics"},
  swatch:{r:[527,50,603,124],door:[548,134],b:"E14",n:"Swatch Lab"},
  bt:{r:[476,216,598,282],door:[520,210],b:"E14",n:"BT Lab"},
  foodcam:{r:[431,133,447,147],door:[439,146],b:"E14",n:"el foodcam"}
};
const LABS=["humdyn","city","sculpt","biotech","socalg","multisens","facilities","nagashima","biomech","swatch","bt"];
// grupos del tercer piso hoy: Swatch Lab = Opera of the Future + Future Sketches; BT Lab = Tangible Media + Affective Computing + Viral Communications; 374 = Biomechatronics. tamaños estimados, no censados
const PLACES=[
  {n:"la cafetería",r:[428,148,468,178]},
  {n:"el pasaje principal",r:[375,128,470,162]},
  {n:"el atrio",r:[470,128,526,210]},
  {n:"el pasillo del Swatch Lab",r:[470,40,605,128]},
  {n:"el pasillo del BT Lab",r:[470,200,605,300]},
  {n:"el núcleo norte de E14",r:[408,40,470,128]},
  {n:"el núcleo sur de E14",r:[408,178,470,300]},
  {n:"el anillo norte de E15",r:[190,156,375,182]},
  {n:"el pasillo oeste",r:[190,182,238,300]},
  {n:"el pasillo sur",r:[238,250,408,300]},
  {n:"el pasillo este de E15",r:[334,182,408,250]},
  {n:"el ala norte de E15",r:[190,83,408,156]}
];
const placeOf=(x,z)=>{const[px,py]=PX(x,z);const p=PLACES.find(p=>px>=p.r[0]&&px<=p.r[2]&&py>=p.r[1]&&py<=p.r[3]);return p?p.n:"un laboratorio"};
const HUB={E15:[388,146],E14:[448,146]};
const LINE_T=1.8;


/* ---------- escena ---------- */
const vp=$("vp");
const renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(2,window.devicePixelRatio||1));vp.prepend(renderer.domElement);
const scene=new THREE.Scene();scene.background=new THREE.Color(0xD9D9D4);scene.fog=new THREE.Fog(0xD9D9D4,45,120);
scene.add(new THREE.HemisphereLight(0xFFFFFF,0x8A8A88,1.05));
const sun=new THREE.DirectionalLight(0xFFFFFF,.55);sun.position.set(12,24,8);scene.add(sun);
const camera=new THREE.PerspectiveCamera(42,1,.1,400);
const controls=new THREE.OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;controls.dampingFactor=.08;controls.maxPolarAngle=Math.PI*.49;controls.minDistance=2.5;controls.maxDistance=90;
const VIEWS={v3d:[[-4,24,24],[2,0,0]],vtop:[[3,44,.01],[3,0,0]],vcafe:[[2.4,6.2,6.6],[4.8,.3,-.7]]};
function setView(k){const [p,t]=VIEWS[k];camera.position.set(...p);controls.target.set(...t);controls.update();Object.keys(VIEWS).forEach(id=>$(id).setAttribute("aria-pressed",id===k))}
Object.keys(VIEWS).forEach(id=>$(id).addEventListener("click",()=>setView(id)));
function resize(){const w=vp.clientWidth,h=vp.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}
new ResizeObserver(resize).observe(vp);
const dotTex=(()=>{const c=document.createElement("canvas");c.width=c.height=64;const g=c.getContext("2d");
  const gr=g.createRadialGradient(32,32,0,32,32,32);gr.addColorStop(0,"rgba(255,255,255,1)");gr.addColorStop(.5,"rgba(255,255,255,.9)");gr.addColorStop(1,"rgba(255,255,255,0)");
  g.fillStyle=gr;g.fillRect(0,0,64,64);return new THREE.CanvasTexture(c)})();
const geoFrom=(pos,col)=>{const g=new THREE.BufferGeometry();g.setAttribute("position",new THREE.Float32BufferAttribute(pos,3));if(col)g.setAttribute("color",new THREE.Float32BufferAttribute(col,3));return g};
const dec=b=>{const s=atob(b),u=new Uint8Array(s.length);for(let i=0;i<s.length;i++)u[i]=s.charCodeAt(i);return new Uint16Array(u.buffer)};
const P2=(x,y)=>W(185+x/2,40+y/2);

/* plano: suelo = plano real teñido; muros = vóxeles */
const CORRPTS=[],CORRRAW=[];
(function buildPlan(){
  const tex=new THREE.TextureLoader().load(PLANTEX);tex.anisotropy=renderer.capabilities.getMaxAnisotropy();
  const fl=new THREE.Mesh(new THREE.PlaneGeometry(42.5,26.5),new THREE.MeshBasicMaterial({map:tex}));
  fl.rotation.x=-Math.PI/2;fl.position.set(-.25,-.01,.25);scene.add(fl);
  const wl=dec(WALLS),box=new THREE.BoxGeometry(.11,.85,.11),mat=new THREE.MeshLambertMaterial({color:0xE2E2DF});
  // dentro de la cafetería no se levantan los iconos del plano
  const keep=[];for(let i=0;i<wl.length;i+=2){const px=185+wl[i]/2,py=40+wl[i+1]/2;if(px>430&&px<466&&py>150&&py<176)continue;if((px>=338&&px<=398&&py>=209&&py<=223)||(px>=387&&px<=397&&py>=150&&py<=223))continue;keep.push(i)}
  const inst=new THREE.InstancedMesh(box,mat,keep.length),m4=new THREE.Matrix4();
  keep.forEach((i,k)=>{const w=P2(wl[i],wl[i+1]);m4.makeTranslation(w.x,.425,w.z);inst.setMatrixAt(k,m4)});
  inst.instanceMatrix.needsUpdate=true;scene.add(inst);
  const cr=dec(CORR);for(let i=0;i<cr.length;i+=24)CORRRAW.push([185+cr[i]/2,40+cr[i+1]/2]);
  // zócalo del edificio
  const base=new THREE.Mesh(new THREE.BoxGeometry(43,.5,27),new THREE.MeshLambertMaterial({color:0xB9B9B6}));base.position.set(-.25,-.27,.25);scene.add(base);
})();
const inBuilding=(px,py)=>(px>=190&&px<=408&&py>=85&&py<=304)||(px>=408&&px<=605&&py>=46&&py<=304);

/* ---------- rejilla de navegación: 1 celda = 1 px del plano; los muros no se cruzan ---------- */
const GW=425,GH=265,NAV=new Uint8Array(GW*GH);
(function buildNav(){
  for(let py=0;py<GH;py++)for(let px=0;px<GW;px++)NAV[py*GW+px]=inBuilding(185+px,40+py)?1:0;
  const wl=dec(WALLS);
  for(let i=0;i<wl.length;i+=2){const x=wl[i]>>1,y=wl[i+1]>>1;for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){const X=x+dx,Y=y+dy;if(X>=0&&X<GW&&Y>=0&&Y<GH)NAV[Y*GW+X]=0}}
  const clear=(px,py,r)=>{for(let dy=-r;dy<=r;dy++)for(let dx=-r;dx<=r;dx++){const X=px-185+dx,Y=py-40+dy;if(X>=0&&X<GW&&Y>=0&&Y<GH&&inBuilding(px+dx,py+dy))NAV[Y*GW+X]=1}};
  const line=(x1,y1,x2,y2,r)=>{const n=Math.ceil(Math.hypot(x2-x1,y2-y1));for(let k=0;k<=n;k++)clear(Math.round(x1+(x2-x1)*k/n),Math.round(y1+(y2-y1)*k/n),r)};
  // puertas: abrir desde el punto de puerta hasta el interior de la sala
  for(const z of Object.values(ZONES)){const [x1,y1,x2,y2]=z.r,[dx,dy]=z.door,ix=Math.min(Math.max(dx,x1+3),x2-3),iy=Math.min(Math.max(dy,y1+3),y2-3);line(dx,dy,ix,iy,2)}
  // cafetería diáfana, ascensores accesibles
  for(let py=150;py<=176;py++)for(let px=430;px<=466;px++)NAV[(py-40)*GW+(px-185)]=1;
  clear(362,170,3);clear(456,196,3);
})();
const walkable=(px,py)=>{px=Math.round(px);py=Math.round(py);const X=px-185,Y=py-40;return X>=0&&X<GW&&Y>=0&&Y<GH&&NAV[Y*GW+X]===1};
for(const [px,py] of CORRRAW)if(walkable(px,py))CORRPTS.push(W(px,py));
(function(){const wl=dec(WALLS);for(let i=0;i<wl.length;i+=2){const x=wl[i]>>1,y=wl[i+1]>>1;for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++){const X=x+dx,Y=y+dy;if(X>=0&&X<GW&&Y>=0&&Y<GH)NAV[Y*GW+X]=0}}
  for(let py=150;py<=176;py++)for(let px=430;px<=466;px++)NAV[(py-40)*GW+(px-185)]=1;})();
/* ---------- clase 341: solo espacios comunes (341, cafetería, atrio, foodcam, pasillos); el resto no se puede pisar ---------- */
const OPEN_ZONES=["nagashima","cafe","atrium","foodcam"];
const ALLOW=new Uint8Array(GW*GH);
(function buildAllow(){
  const cr=dec(CORR),dens=new Uint8Array(GW*GH);
  for(let i=0;i<cr.length;i+=2){const x=cr[i]>>1,y=cr[i+1]>>1;if(x>=0&&x<GW&&y>=0&&y<GH)dens[y*GW+x]=1}
  const cnt=new Uint8Array(GW*GH);
  for(let y=0;y<GH;y++)for(let x=0;x<GW;x++){let n=0;for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++){const X=x+dx,Y=y+dy;if(X>=0&&X<GW&&Y>=0&&Y<GH&&dens[Y*GW+X])n++}cnt[y*GW+x]=n}
  for(let i=0;i<GW*GH;i++)ALLOW[i]=cnt[i]>=9?1:0;
  // dilatar un poco para que los pasillos sean continuos
  const d=new Uint8Array(ALLOW);for(let y=1;y<GH-1;y++)for(let x=1;x<GW-1;x++){if(ALLOW[y*GW+x])continue;for(let dy=-1;dy<=1&&!d[y*GW+x];dy++)for(let dx=-1;dx<=1;dx++)if(ALLOW[(y+dy)*GW+x+dx]){d[y*GW+x]=1;break}}
  d.forEach((v,i)=>ALLOW[i]=v);
  for(const id of OPEN_ZONES){const [x1,y1,x2,y2]=ZONES[id].r,[dx,dy]=ZONES[id].door;for(let y=y1;y<=y2;y++)for(let x=x1;x<=x2;x++)ALLOW[(y-40)*GW+(x-185)]=1;
    const ix=Math.min(Math.max(dx,x1+3),x2-3),iy=Math.min(Math.max(dy,y1+3),y2-3),n=Math.ceil(Math.hypot(ix-dx,iy-dy));for(let k=0;k<=n;k++){const px=Math.round(dx+(ix-dx)*k/n),py=Math.round(dy+(iy-dy)*k/n);for(let yy=-2;yy<=2;yy++)for(let xx=-2;xx<=2;xx++){const X=px-185+xx,Y=py-40+yy;if(X>=0&&X<GW&&Y>=0&&Y<GH)ALLOW[Y*GW+X]=1}}}
  // escaleras, núcleos y salas que el plano pinta claras pero no son espacio común
  const FORBID=[[365,176,398,206],[386,206,398,256],[396,166,452,207],[185,166,218,202],[405,40,447,126],[495,56,565,124],[560,96,606,132],[405,248,452,302],[405,214,448,252],[600,130,606,190]];
  for(const [x1,y1,x2,y2] of FORBID)for(let y=y1;y<=y2;y++)for(let x=x1;x<=x2;x++){const X=x-185,Y=y-40;if(X>=0&&X<GW&&Y>=0&&Y<GH)ALLOW[Y*GW+X]=0}
  for(const id of OPEN_ZONES){const [x1,y1,x2,y2]=ZONES[id].r;for(let y=y1;y<=y2;y++)for(let x=x1;x<=x2;x++)ALLOW[(y-40)*GW+(x-185)]=1}
  // puerta de la 341: pasillo corto hasta el anillo norte
  for(const [x1,y1,x2,y2] of [[338,209,398,223],[387,150,397,223]])for(let y=y1;y<=y2;y++)for(let x=x1;x<=x2;x++){const i=(y-40)*GW+(x-185);ALLOW[i]=1;NAV[i]=1}
  const ALLOW0=new Uint8Array(ALLOW);window.ALLOW0=ALLOW0;
  // solo lo conectado con la cafetería (sin islas)
  {const ok=new Uint8Array(GW*GH),q=[];const [sx,sy]=[448-185,163-40];q.push(sy*GW+sx);ok[sy*GW+sx]=1;
    while(q.length){const c=q.pop(),cx=c%GW,cy=(c-cx)/GW;for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){const X=cx+dx,Y=cy+dy;if(X<0||X>=GW||Y<0||Y>=GH)continue;const n=Y*GW+X;if(ok[n]||!ALLOW[n]||NAV[n]!==1)continue;ok[n]=1;q.push(n)}}
    for(let i=0;i<GW*GH;i++)if(!ok[i]){ALLOW[i]=0}}
  for(let i=0;i<GW*GH;i++)if(!ALLOW[i])NAV[i]=0;
  CORRPTS.length=0;for(const [px,py] of CORRRAW)if(walkable(px,py))CORRPTS.push(W(px,py));
})();
// máscara: negro donde no se puede entrar (para el 3D y para los planos 2D)
const MASK=(()=>{const c=document.createElement("canvas");c.width=GW;c.height=GH;const g=c.getContext("2d"),im=g.createImageData(GW,GH),d=im.data;
  for(let y=0;y<GH;y++)for(let x=0;x<GW;x++){let open=false;for(let dy=-1;dy<=1&&!open;dy++)for(let dx=-1;dx<=1;dx++){const X=x+dx,Y=y+dy;if(X>=0&&X<GW&&Y>=0&&Y<GH&&ALLOW[Y*GW+X]){open=true;break}}
    const i=(y*GW+x)*4;d[i]=22;d[i+1]=22;d[i+2]=24;d[i+3]=open?0:255}
  g.putImageData(im,0,0);return c})();
(function(){const tex=new THREE.CanvasTexture(MASK);tex.magFilter=THREE.NearestFilter;const m=new THREE.Mesh(new THREE.PlaneGeometry(42.5,26.5),new THREE.MeshBasicMaterial({map:tex,transparent:true,depthWrite:false}));m.rotation.x=-Math.PI/2;m.position.set(-.25,.004,.25);scene.add(m)})();
const inAllowed=(px,py)=>{px=Math.round(px);py=Math.round(py);const X=px-185,Y=py-40;return X>=0&&X<GW&&Y>=0&&Y<GH&&ALLOW[Y*GW+X]===1};

function nearestWalkable(px,py){px=Math.round(px);py=Math.round(py);if(walkable(px,py))return [px,py];for(let r=1;r<40;r++)for(let dy=-r;dy<=r;dy++)for(let dx=-r;dx<=r;dx++){if(Math.max(Math.abs(dx),Math.abs(dy))!==r)continue;if(walkable(px+dx,py+dy))return [px+dx,py+dy]}return [px,py]}
const losOK=(x1,y1,x2,y2)=>{const n=Math.ceil(Math.hypot(x2-x1,y2-y1)*2);for(let k=0;k<=n;k++)if(!walkable(x1+(x2-x1)*k/n,y1+(y2-y1)*k/n))return false;return true};
const NAVq=new Int32Array(GW*GH),NAVp=new Int32Array(GW*GH);
function findPath(ax,az,bx,bz){
  let [sx,sy]=nearestWalkable(...PX(ax,az)),[tx,ty]=nearestWalkable(...PX(bx,bz));
  const s=(sy-40)*GW+(sx-185),t=(ty-40)*GW+(tx-185);
  if(s===t)return [{x:bx,z:bz}];
  NAVp.fill(-1);let h=0,q=0;NAVq[q++]=s;NAVp[s]=s;
  const D=[1,-1,GW,-GW,GW+1,GW-1,-GW+1,-GW-1];
  let found=false;
  while(h<q){const c=NAVq[h++];if(c===t){found=true;break}const cx=c%GW;
    for(let k=0;k<8;k++){const n=c+D[k];if(n<0||n>=GW*GH||NAVp[n]!==-1||NAV[n]!==1)continue;const nx=n%GW;if(Math.abs(nx-cx)>1)continue;
      if(k>=4){const a=c+D[k>=6?(k===6?1:-1):(k===4?1:-1)],b=c+D[k>=6?-GW+0:GW]/1;/* evitar atravesar esquinas */if(NAV[c+(nx-cx)]!==1||NAV[c+(n-c-(nx-cx))]!==1)continue}
      NAVp[n]=c;NAVq[q++]=n}}
  if(!found)return null;
  const cells=[];for(let c=t;c!==s;c=NAVp[c])cells.push(c);cells.push(s);cells.reverse();
  // simplificar por línea de visión
  const pts=[];let i=0;while(i<cells.length-1){let j=cells.length-1;const [x1,y1]=[cells[i]%GW+185,Math.floor(cells[i]/GW)+40];
    while(j>i+1){const [x2,y2]=[cells[j]%GW+185,Math.floor(cells[j]/GW)+40];if(losOK(x1,y1,x2,y2))break;j--}
    const [x2,y2]=[cells[j]%GW+185,Math.floor(cells[j]/GW)+40];pts.push(W(x2,y2));i=j}
  if(!pts.length)pts.push(W(tx,ty));
  pts[pts.length-1]=W(tx,ty);
  return pts;
}
const inZone=(id,x,z)=>{const[x1,y1,x2,y2]=ZONES[id].r,a=W(x1,y1),b=W(x2,y2);return x>=a.x&&x<=b.x&&z>=a.z&&z<=b.z};
const inLab=(x,z)=>LABS.some(l=>inZone(l,x,z));
(function(){const[x1,y1,x2,y2]=ZONES.cafe.r,a=W(x1,y1),b=W(x2,y2);const m=new THREE.Mesh(new THREE.PlaneGeometry(b.x-a.x,b.z-a.z),new THREE.MeshBasicMaterial({color:0xE6E6E2}));m.rotation.x=-Math.PI/2;m.position.set((a.x+b.x)/2,.005,(a.z+b.z)/2);scene.add(m)})();

/* ---------- dos mapas de calor: presencia y propuestas ---------- */
const HW=850,HH=530;
function heatLayer(ramp,y){
  const acc=document.createElement("canvas");acc.width=HW;acc.height=HH;const actx=acc.getContext("2d");
  const hc=document.createElement("canvas");hc.width=HW;hc.height=HH;const hctx=hc.getContext("2d");
  const tex=new THREE.CanvasTexture(hc);
  const plane=new THREE.Mesh(new THREE.PlaneGeometry(42.5,26.5),new THREE.MeshBasicMaterial({map:tex,transparent:true,depthWrite:false}));
  plane.rotation.x=-Math.PI/2;plane.position.set(-.25,y,.25);plane.visible=false;scene.add(plane);
  return {on:false,plane,dirty:false,
    stamp(x,z,w,r=11){const[px,py]=PX(x,z),cx=(px-185)*2,cy=(py-40)*2,g=actx.createRadialGradient(cx,cy,0,cx,cy,r);g.addColorStop(0,`rgba(255,255,255,${w})`);g.addColorStop(1,"rgba(255,255,255,0)");actx.fillStyle=g;actx.fillRect(cx-r,cy-r,2*r,2*r);this.dirty=true},
    render(){const src=actx.getImageData(0,0,HW,HH).data,out=hctx.createImageData(HW,HH),d=out.data;
      for(let i=0;i<src.length;i+=4){const a=src[i+3];if(!a)continue;ramp(Math.min(1,a/190),d,i)}
      hctx.putImageData(out,0,0);tex.needsUpdate=true;this.dirty=false},
    clear(){actx.clearRect(0,0,HW,HH);hctx.clearRect(0,0,HW,HH);tex.needsUpdate=true}};
}
const presenceHeat=heatLayer((t,d,i)=>{d[i]=255;d[i+1]=t<.5?170-100*t:120-120*(t-.5);d[i+2]=t<.5?90-80*t:50-40*(t-.5);d[i+3]=40+200*t},.02);
const proposals=heatLayer((t,d,i)=>{d[i]=40+20*t;d[i+1]=160+40*t;d[i+2]=80;d[i+3]=40+200*t},.025);
function bindToggle(id,layer){$(id).addEventListener("click",()=>{layer.on=!layer.on;layer.plane.visible=layer.on;$(id).setAttribute("aria-pressed",layer.on);if(layer.on)layer.render()})}
bindToggle("heat",presenceHeat);bindToggle("prop",proposals);

/* huellas, pulsos, arcos */
const MAXH=6000,stampPos=new Float32Array(MAXH*3),stampGeo=new THREE.BufferGeometry();stampGeo.setAttribute("position",new THREE.BufferAttribute(stampPos,3));stampGeo.setDrawRange(0,0);
scene.add(new THREE.Points(stampGeo,new THREE.PointsMaterial({size:.14,color:0xFF4F12,map:dotTex,transparent:true,depthWrite:false,opacity:.45})));
let stampN=0;
function stamp(x,z){for(let k=0;k<26;k++){const i=(stampN%MAXH)*3,a=Math.random()*6.28,r=Math.abs((Math.random()+Math.random()-1))*.9;stampPos[i]=x+Math.cos(a)*r;stampPos[i+1]=.05+Math.random()*.04;stampPos[i+2]=z+Math.sin(a)*r;stampN++}
  stampGeo.setDrawRange(0,Math.min(stampN,MAXH));stampGeo.attributes.position.needsUpdate=true}
const pulses=[],ringGeo=(()=>{const p=[];for(let a=0;a<6.28;a+=.12)p.push(Math.cos(a),0,Math.sin(a));return geoFrom(p)})();
const arcs=[];
function arc(a,b,color){const pts=[];for(let i=0;i<=24;i++){const t=i/24;pts.push(a.x+(b.x-a.x)*t,1.2+Math.sin(Math.PI*t)*.9,a.z+(b.z-a.z)*t)}
  const m=new THREE.Points(geoFrom(pts),new THREE.PointsMaterial({size:.12,color,map:dotTex,transparent:true,depthWrite:false,opacity:1}));scene.add(m);arcs.push({m,t:0})}
const ghosts=[];
function ghost(x,z){const m=new THREE.Points(ringGeo,new THREE.PointsMaterial({size:.18,color:0x2B9A4C,map:dotTex,transparent:true,depthWrite:false,opacity:.95}));m.position.set(x,.08,z);m.scale.setScalar(.7);scene.add(m);ghosts.push({m,t:0})}

/* ---------- arte píxel ---------- */
function paintRows(c,rows,pal,k=1){c.width=rows[0].length*k;c.height=rows.length*k;const g=c.getContext("2d");g.clearRect(0,0,c.width,c.height);
  rows.forEach((row,y)=>[...row].forEach((ch,x)=>{if(ch!=="."){g.fillStyle=pal[ch];g.fillRect(x*k,y*k,k,k)}}));return c}
function pixTex(rows,pal){const c=paintRows(document.createElement("canvas"),rows,pal);
  const t=new THREE.CanvasTexture(c);t.magFilter=THREE.NearestFilter;t.minFilter=THREE.NearestFilter;t.url=c.toDataURL();return t}
const FR=[
["................",".....hhhhhh.....","....hhhhhhhh....","....hhssssshh...","....hsssssssh...","....hsesssesh...","....hsssssssh...",".....ssssss.....","......ssss......",".....tttttt.....","....tttttttt....","...sttttttttts..","...sttttttttts..","...s.tttttt.s...",".....tttttt.....",".....pppppp.....",".....pppppp.....",".....pp..pp.....",".....pp..pp.....",".....pp..pp.....",".....bb..bb.....","....bbb..bbb....","................","................"],
["................",".....hhhhhh.....","....hhhhhhhh....","....hhssssshh...","....hsssssssh...","....hsesssesh...","....hsssssssh...",".....ssssss.....","......ssss......",".....tttttt.....","....tttttttt....","..s.tttttttt.s..","...sttttttttts..","....tttttttt....",".....tttttt.....",".....pppppp.....","....ppp..ppp....","....pp....pp....","...pp......pp...","...pp......pp...","...bb......bb...","..bbb......bbb..","................","................"],
["................",".....hhhhhh.....","....hhhhhhhh....","....hhssssshh...","....hsssssssh...","....hsesssesh...","....hsssssssh...",".....ssssss.....","......ssss......",".....tttttt.....","....tttttttt....","...sttttttttts..","..s.tttttttt.s..","....tttttttt....",".....tttttt.....",".....pppppp.....",".....pppppp.....","....ppp..pp.....","....pp...pp.....","....pp...pp.....","....bb...bb.....","...bbb...bbb....","................","................"]];
const SKIN=["#F4C7A1","#E0A982","#C98B5E","#A66A3E","#7C4A2A","#5A3520"],HAIR=["#1E1A17","#4A2E1C","#8B5A2B","#C9A24C","#B14A2E","#2B2F6B","#6E6E78","#E7E1D0"],
  SHIRT=["#3D7FE0","#E0583D","#2FAF6A","#E8B33A","#9A4FD6","#F07AA8","#2BB5B5","#F2F0E6","#30343A","#D06A2C"],PANTS=["#263142","#3B3F48","#5A3A2A","#1F4A6E","#6B6F78","#2E5F3E"];
const avatarIdx=i=>({t:i%SHIRT.length,h:Math.floor(i/SHIRT.length)%HAIR.length,s:(i*5+2)%SKIN.length,p:(i*7+3)%PANTS.length,hs:0,g:0});
/* avatar = palette indexes {t shirt, h hair, s skin, p pants} + optional hs (hair style), g (glasses) and face:
   35 characters (7 columns × 5 rows over the face, s skin · d shade · e dark · h hair) written by the camera */
const HAIRSTYLES=4,FACE_X=5,FACE_Y=3,FACE_W=7,FACE_H=5;
const shade=(hex,k)=>"#"+[1,3,5].map(i=>Math.round(parseInt(hex.slice(i,i+2),16)*k).toString(16).padStart(2,"0")).join("");
function avatarPal(av){const s=SKIN[av.s%SKIN.length];return {h:HAIR[av.h%HAIR.length],s,d:shade(s,.8),e:"#17171B",t:SHIRT[av.t%SHIRT.length],p:PANTS[av.p%PANTS.length],b:"#15151A",g:"#17171B",l:"#CFE3EE"}}
function avatarRows(av,f=0,dx=0){
  const R=FR[f].map(r=>[...r]),put=(y,x,ch)=>{if(R[y]&&x>=0&&x<16)R[y][x]=ch};
  const hs=(av.hs||0)%HAIRSTYLES;
  if(hs===1)[[7,4],[8,4],[9,4],[7,11],[8,11],[9,11],[8,5],[8,10]].forEach(([y,x])=>put(y,x,"h"));       // long
  if(hs===2){for(let x=0;x<16;x++)if(R[1][x]==="h")R[1][x]=".";put(3,5,"s");put(3,11,"s")}                // buzz
  if(hs===3){put(0,7,"h");put(0,8,"h")}                                                                  // bun
  if(av.face&&av.face.length===FACE_W*FACE_H)for(let y=0;y<FACE_H;y++)for(let x=0;x<FACE_W;x++){const ch=av.face[y*FACE_W+x],cur=R[FACE_Y+y][FACE_X+x];if(cur==="s"||cur==="e")R[FACE_Y+y][FACE_X+x]=ch}
  if(av.g)[["g",5],["l",6],["g",7],["g",8],["g",9],["l",10],["g",11]].forEach(([ch,x])=>put(5,x,ch));
  if(dx)for(let y=0;y<=8;y++){const row=R[y];R[y]=dx>0?[".",...row.slice(0,15)]:[...row.slice(1),"."]}   // head tilt (camera preview)
  return R.map(r=>r.join(""));
}
function spriteFrom(av){const pal=avatarPal(av);return FR.map((_,f)=>pixTex(avatarRows(av,f),pal))}
function spriteSet(i){const pal={h:HAIR[Math.floor(i/SHIRT.length)%HAIR.length],s:SKIN[(i*5+2)%SKIN.length],e:"#17171B",t:SHIRT[i%SHIRT.length],p:PANTS[(i*7+3)%PANTS.length],b:"#15151A"};return FR.map(f=>pixTex(f,pal))}
const bubbleTex=(()=>{const c=document.createElement("canvas");c.width=18;c.height=14;const g=c.getContext("2d");
  g.fillStyle="#161616";g.fillRect(1,0,16,10);g.fillRect(0,1,18,8);g.fillRect(6,10,5,2);g.fillRect(6,12,2,1);
  g.fillStyle="#FFFFFF";g.fillRect(2,1,14,8);g.fillRect(1,2,16,6);g.fillRect(7,9,3,2);
  g.fillStyle="#161616";[4,8,12].forEach(x=>g.fillRect(x,4,2,2));const t=new THREE.CanvasTexture(c);t.magFilter=t.minFilter=THREE.NearestFilter;return t})();
const shadowGeo=new THREE.CircleGeometry(.32,16),shadowMat=new THREE.MeshBasicMaterial({color:0x000000,transparent:true,opacity:.22,depthWrite:false});
const selRing=new THREE.Points(ringGeo,new THREE.PointsMaterial({size:.2,color:0x161616,map:dotTex,transparent:true,depthWrite:false,opacity:.9}));selRing.visible=false;scene.add(selRing);

