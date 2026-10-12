const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const elements = {region:{value:'CMB_GN_HP'},status:{textContent:''},detail:{style:{}}};
const buttons = ['FIBER','COAX','CONDUIT'].map(group=>({dataset:{group},classList:{toggle(){}}}));
const document = {getElementById:id=>elements[id]||(elements[id]={style:{}}),querySelectorAll:()=>buttons};
class LatLng { constructor(lat,lng){this.lat=lat;this.lng=lng;} getLat(){return this.lat;} getLng(){return this.lng;} }
class Polyline { constructor(options){this.options=options;} setMap(map){this.map=map;} setZIndex(){} }
const map = {level:3,getLevel(){return this.level;},getCenter(){return new LatLng(35,127);}};
const context = vm.createContext({document,console,kakao:{maps:{LatLng,Polyline,event:{addListener(){}}}},setTimeout,clearTimeout,setInterval,clearInterval});
vm.runInContext(fs.readFileSync(process.argv[2],'utf8')+`
globalThis.test={loadObjects,clearGroupOverlays,clearOverlays,clearNonFiberOverlays,hideGroupOverlays,showGroupOverlays,applyZoomVisibility,renderFiberFeatures,bindUi,
 setMap:v=>map=v,setApi:v=>apiCall=v,setSnap:v=>snapCablePath=v,
 groups:groupEnabled,getOverlays:()=>overlays,status:()=>document.getElementById('status').textContent,
 reset:()=>{clearOverlays();lastQueryLat=null;lastQueryLng=null;lastDetailMode=null;},
 setDevice:v=>drawDevice=v};`,context);
const t=context.test; t.setMap(map); t.bindUi();
const feature=(group,type,coordinates)=>({properties:{group_id:group},geometry:{type,coordinates}});
const coords=[[127,35],[127.001,35.001]];
const dynamicFeatures=[
  feature('COAX','MultiLineString',[coords,coords]),
  feature('CONDUIT','LineString',coords)
];
const fiberFeatures=[feature('FIBER','LineString',coords)];
let requests=0;
t.setApi(async()=>{requests++;return {features:dynamicFeatures};});
t.groups.COAX=t.groups.CONDUIT=true;
(async()=>{
  t.reset();
  const fiberCount=t.renderFiberFeatures(fiberFeatures);
  assert.equal(fiberCount,1);
  assert.equal(t.getOverlays().length,1);

  map.level=3;
  await t.loadObjects(true);
  assert.equal(t.getOverlays().length,4,'fiber + two coax + one conduit');
  assert.ok(t.getOverlays().some(x=>x.options.path[0].getLng()===127));

  map.level=4;
  await t.loadObjects(true);
  assert.equal(t.getOverlays().length,1,'zoom out must preserve cached fiber only');

  map.level=3;
  await t.loadObjects(true);
  assert.equal(t.getOverlays().length,4);

  const before=requests;
  buttons[1].onclick();
  assert.equal(requests,before,'COAX OFF must not fetch');
  assert.equal(t.getOverlays().length,4,'COAX OFF keeps cached overlay objects');
  const coaxHidden=t.getOverlays().filter(x=>x.map===null).length;
  assert.equal(coaxHidden,2,'two COAX lines hidden in-place');

  buttons[1].onclick();
  assert.equal(requests,before,'COAX reopen must restore cached overlays without fetch');
  assert.equal(t.getOverlays().filter(x=>x.map===map).length,4,'cached COAX lines restored immediately');

  buttons[0].onclick();
  assert.equal(t.getOverlays().length,4,'FIBER OFF keeps cached fiber object');
  assert.equal(t.getOverlays().filter(x=>x.map===null).length,1,'fiber hidden in-place');

  const zoomRequests=requests;
  map.level=4;
  t.applyZoomVisibility(4);
  assert.equal(requests,zoomRequests,'zoom visibility must not fetch');
  assert.equal(t.getOverlays().filter(x=>x.map===map).length,0,'L4 hides all currently cached non-fiber and disabled fiber');
  map.level=3;
  t.applyZoomVisibility(3);
  assert.equal(requests,zoomRequests,'zoom in visibility must not fetch');

  console.log('ONLINE_PERSISTENT_LAYER_CACHE_RENDER_OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
