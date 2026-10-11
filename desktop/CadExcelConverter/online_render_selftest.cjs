const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const elements = {region:{value:'CMB_GN_HP'},status:{textContent:''}};
const buttons = ['FIBER','COAX','CONDUIT'].map(group=>({dataset:{group},classList:{toggle(){}}}));
const document = {getElementById:id=>elements[id]||(elements[id]={style:{}}),querySelectorAll:()=>buttons};
class LatLng { constructor(lat,lng){this.lat=lat;this.lng=lng;} getLat(){return this.lat;} getLng(){return this.lng;} }
class Polyline { constructor(options){this.options=options;} setMap(map){this.map=map;} setZIndex(){} }
const map = {level:3,getLevel(){return this.level;},getCenter(){return new LatLng(35,127);}};
const context = vm.createContext({document,console,kakao:{maps:{LatLng,Polyline,event:{addListener(){}}}},setTimeout,clearTimeout,setInterval,clearInterval});
vm.runInContext(fs.readFileSync(process.argv[2],'utf8')+`
globalThis.test={loadObjects,clearGroupOverlays,clearOverlays,bindUi,
 setMap:v=>map=v,setApi:v=>apiCall=v,setSnap:v=>snapCablePath=v,
 groups:groupEnabled,getOverlays:()=>overlays,status:()=>document.getElementById('status').textContent,
 reset:()=>{clearOverlays();lastQueryLat=null;lastQueryLng=null;lastDetailMode=null;},
 setDevice:v=>drawDevice=v};`,context);
const t=context.test; t.setMap(map); t.bindUi();
const feature=(group,type,coordinates)=>({properties:{group_id:group},geometry:{type,coordinates}});
const coords=[[127,35],[127.001,35.001]];
const features=[feature('FIBER','LineString',coords),feature('COAX','MultiLineString',[coords,coords]),feature('CONDUIT','LineString',coords)];
let requests=0;
t.setApi(async()=>{requests++;return {features};});
t.groups.COAX=t.groups.CONDUIT=true;
(async()=>{
 for(const level of [1,2,3]){
  map.level=level;t.reset();
  t.setSnap(()=>{throw Error('projection unavailable');});
  await t.loadObjects(true);
  assert.equal(t.getOverlays().length,4);
  assert.match(t.status(),/렌더선 4/);
  assert.match(t.status(),/F:1\/C:2\/D:1/);
  for(const line of t.getOverlays()) assert.equal(line.options.path[0].getLng(),127);
 }
 t.setSnap(()=>[new LatLng(NaN,127),new LatLng(35,NaN)]);
 await t.loadObjects(true);
 assert.equal(t.getOverlays()[0].options.path[0].getLat(),35);
 const old=t.getOverlays().slice(), count=requests;
 buttons[0].onclick();
 assert.equal(requests,count,'OFF must not fetch');
 assert.equal(old[0].map,null);
 assert.equal(t.getOverlays().length,3);
 assert.ok(t.getOverlays().every(x=>x.map===map));
 let resolve;
 t.setApi(()=>{requests++;return new Promise(r=>resolve=r);});
 const pending=t.loadObjects(true);
 buttons[1].onclick();
 resolve({features});await pending;
 assert.equal(t.getOverlays().length,1,'late request must not restore OFF group');
 map.level=4;await t.loadObjects(true);
 assert.equal(t.getOverlays().length,0);
 map.level=3;t.reset();
 const late=t.loadObjects(true);map.level=4;await t.loadObjects();
 resolve({features});await late;
 assert.equal(t.getOverlays().length,0,'late L3 response must not draw at L4');
 // Idle with no meaningful movement must preserve a forced in-flight reload.
 map.level=3;t.groups.FIBER=t.groups.COAX=true;t.reset();
 t.setApi(async()=>({features}));await t.loadObjects(true);
 t.setApi(()=>new Promise(r=>resolve=r));
 const forced=t.loadObjects(true);await t.loadObjects();
 resolve({features:[feature('FIBER','LineString',coords)]});await forced;
 assert.equal(t.getOverlays().length,1,'redundant idle cancelled reload');
 // A later ON must win even if the preceding request resolves last.
 t.reset();t.groups.COAX=false;const responses=[];
 t.setApi(()=>{requests++;return new Promise(r=>responses.push(r));});
 const older=t.loadObjects(true);const beforeOn=requests;
 buttons[1].onclick();assert.equal(requests,beforeOn+1);
 responses[1]({features});await new Promise(r=>setImmediate(r));
 responses[0]({features:[]});await older;
 assert.equal(t.getOverlays().length,4);
 console.log('ONLINE_RENDER_AND_STALE_REQUEST_BEHAVIOR_OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
