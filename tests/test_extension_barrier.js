"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const {webcrypto}=require("node:crypto");
const root=path.resolve(__dirname,".."),source=name=>fs.readFileSync(path.join(root,"chrome_extension",name),"utf8");
function harness({widget=false}={}) {
  const store={},tabs=new Map();let listener,nextTab=10,clicks=0,probes=0,country="GB",flipAtBarrier=false;
  const review={id:"a".repeat(24),text:"My real visit.",stars:4,expected_name:"My Market",account_email:"owner@example.com",
    navigation_url:"https://www.google.com/maps/place/My+Market/data=!1sfixture",business_key:"place:fixture"};
  const sender={id:"fixture",frameId:0,tab:{id:1},url:"http://127.0.0.1:5000/"};
  const widgetUrl="https://www.google.com/maps/api/js/ReviewsService.LoadWriteWidget?placeid=fixture&authuser=0";
  const googleSender=tabId=>({id:"fixture",frameId:0,tab:tabs.get(tabId),url:tabs.get(tabId).url});
  const frameSender=tabId=>({...googleSender(tabId),frameId:2,url:widgetUrl});
  function send(message,source=sender) {
    return new Promise(resolve=>{if(listener(message,source,resolve)!==true) resolve(null);});
  }
  const api={runtime:{id:"fixture",getManifest:()=>({version:"1.0.7"}),onMessage:{addListener:fn=>{listener=fn;}}},
    storage:{session:{get:async key=>({[key]:store[key]}),set:async entries=>Object.assign(store,entries),remove:async key=>{delete store[key];}}},
    tabs:{create:async values=>{const tab={id:++nextTab,...values,status:"complete"};tabs.set(tab.id,tab);return tab;},
      get:async id=>tabs.get(id),update:async()=>{},remove:async id=>{tabs.delete(id);},
      sendMessage:async(tabId,message)=>{
        if(message.type==="TASMEE_WIDGET") {
          if(message.action!=="submit") return {ok:true,text:review.text,stars:review.stars};
          if(flipAtBarrier) country="PK";
          const barrier=await send({type:"TASMEE_SUBMIT_BARRIER",review},frameSender(tabId));
          if(!barrier.ok) return barrier;
          clicks++;return {ok:true,clicked:true,text:review.text,stars:review.stars};
        }
        if(message.action==="prepare") {
          if(widget) await send({type:"TASMEE_WIDGET_READY"},frameSender(tabId));
          return {ok:true,assertion:{text:review.text,stars:review.stars}};
        }
        if(message.action==="verify" && widget)
          return send({type:"TASMEE_WIDGET_REQUEST",action:"verify",review,url:widgetUrl},googleSender(tabId));
        if(message.action!=="submit") return {ok:true};
        if(widget) {
          const result=await send({type:"TASMEE_WIDGET_REQUEST",action:"submit",review,url:widgetUrl},googleSender(tabId));
          return result.ok ? {ok:true,confirmed:true} : result;
        }
        if(flipAtBarrier) country="PK";
        const barrier=await send({type:"TASMEE_SUBMIT_BARRIER",review},googleSender(tabId));
        if(!barrier.ok) return barrier;
        clicks++;return {ok:true,confirmed:true};
      }}};
  function restart() {
    const context={chrome:api,URL,URLSearchParams,setTimeout,clearTimeout,Date,Promise,Map,Set,performance,
      crypto:webcrypto,AbortController,TextDecoder,Uint8Array,fetch:async url=>{
        probes++;const response=new Response(`ip=8.8.8.8\nloc=${country}\n`,{headers:{"content-type":"text/plain"}});
        Object.defineProperty(response,"url",{value:url});return response;
      }};
    vm.runInNewContext(source("network_guard.js"),context);vm.runInNewContext(source("background.js"),context);
  }
  restart();
  return {review,store,tabs,sender,send,restart,googleSender,frameSender,
    command:(action,data={review})=>send({type:"TASMEE_COMMAND",action,data}),
    get clicks(){return clicks;},get probes(){return probes;},set flipAtBarrier(value){flipAtBarrier=value;}};
}
async function main() {
  for(const widget of [false,true]) {
    const fixture=harness({widget});
    assert.equal((await fixture.command("prepare")).ok,true);
    assert.equal((await fixture.command("verify")).ok,true);
    assert.equal((await fixture.command("submit")).ok,true);
    assert.equal(fixture.clicks,1);
    const stored=fixture.store["review:"+fixture.review.id];
    assert.equal(stored.phase,"submitting");assert.equal(stored.barrierUsed,true);
    assert.equal((await fixture.command("submit")).ok,false);assert.equal(fixture.clicks,1);
    const source=widget ? fixture.frameSender(stored.tabId) : fixture.googleSender(stored.tabId);
    assert.equal((await fixture.send({type:"TASMEE_SUBMIT_BARRIER",review:fixture.review},source)).ok,false);
    assert.equal(fixture.clicks,1);
    const blocked=harness({widget});
    await blocked.command("prepare");blocked.flipAtBarrier=true;
    const result=await blocked.command("submit");
    assert.equal(result.ok,false);assert.equal(result.network.allowed,false);assert.equal(result.network.code,"not_uk");
    assert.equal(blocked.clicks,0);assert.equal((await blocked.command("submit")).ok,false);
  }
  const restarted=harness();await restarted.command("prepare");restarted.restart();
  assert.equal((await restarted.command("ping")).network.status,"unknown");
  const rejected=await restarted.command("submit");assert.equal(rejected.ok,false);assert.match(rejected.message,/restarted/);
  assert.equal(restarted.clicks,0);
  const unauthorized=harness();await unauthorized.command("prepare");
  const before=unauthorized.probes,stored=unauthorized.store["review:"+unauthorized.review.id];
  for(const sender of [unauthorized.sender,{...unauthorized.googleSender(stored.tabId),id:"other-extension"},
    {...unauthorized.googleSender(stored.tabId),frameId:55,url:"https://www.google.com/maps/api/js/ReviewsService.LoadWriteWidget?placeid=fixture&authuser=0"}])
    assert.equal((await unauthorized.send({type:"TASMEE_SUBMIT_BARRIER",review:unauthorized.review},sender)).ok,false);
  assert.equal(unauthorized.probes,before);assert.equal(unauthorized.clicks,0);
  console.log("extension final barrier: inline/iframe one-shot submission, late network loss, restart and sender isolation passed");
}
main().catch(error=>{console.error(error);process.exitCode=1;});
