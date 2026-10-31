"use strict";
// Node-only API mocks. No browser, credentials, network traffic or real review.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function exercise(folder, kind) {
  const manifest=JSON.parse(fs.readFileSync(path.join(folder,"manifest.json"),"utf8"));
  let listener;
  const opened=[],removed=[],calls=[],stored={},tabs=new Map();let failSaved=false;
  const api={runtime:{id:"fixture",getManifest:()=>manifest,onMessage:{addListener:fn=>listener=fn}},
    storage:{session:{get:async key=>({[key]:stored[key]}),set:async values=>Object.assign(stored,values),remove:async key=>delete stored[key]}},
    tabs:{create:async values=>{opened.push(values);const tab={id:opened.length+10,...values,status:'complete'};tabs.set(tab.id,tab);return tab;},
      get:async id=>tabs.get(id),update:async()=>{},remove:async id=>{removed.push(id);tabs.delete(id);},
      sendMessage:async(id,message)=>{calls.push(message.action);
        if(message.action==='account') return {ok:true,email:'owner@example.com',account_index:'1'};
        if(message.action==='reconcile' && failSaved) return {ok:false,message:'No matching saved review'};
        return {ok:true,assertion:{email:'owner@example.com',saved_review_id:'fixture-saved'}};}}};
  const context={URL,URLSearchParams,setTimeout,Date,Promise,console,Map};
  context[kind==="firefox" ? "browser" : "chrome"]=api;
  vm.runInNewContext(fs.readFileSync(path.join(folder,"background.js"),"utf8"),context);
  const sender={id:"fixture",frameId:0,tab:{id:1},url:"http://127.0.0.1:5000/"};
  function command(action,data,source=sender) {
    return new Promise(resolve=>{
      const result=listener({type:"TASMEE_COMMAND",action,data},source,resolve);
      if(result!==true) resolve(null);
    });
  }
  const ping=await command("ping");
  assert.equal(ping.ok,true);
  assert.equal(ping.version,"1.0.6");
  assert.ok(ping.capabilities.includes('saved_checks'));
  assert.equal(ping.browser_kind,kind);
  assert.equal((await command("login",{email:"owner@example.com"})).ok,true);
  assert.equal(opened.length,1);
  const url=new URL(opened[0].url);
  assert.equal(url.origin,"https://accounts.google.com");
  assert.equal(url.searchParams.get("Email"),"owner@example.com");
  assert.equal(url.searchParams.get("continue"),"https://www.google.com/maps?hl=en");
  assert.equal((await command("login",{email:"bad"})).ok,false);
  assert.equal(await command("login",{email:"owner@example.com"},{...sender,url:"https://evil.example/"}),null);
  assert.equal(await command("login",{email:"owner@example.com"},{...sender,frameId:1}),null);
  assert.equal(opened.length,1);
  assert.equal((await command('check',{email:'owner@example.com'})).ok,true);
  assert.equal(new URL(opened.at(-1).url).searchParams.get('authuser'),'owner@example.com');
  const review={id:'a'.repeat(24),stars:4,text:'Real visit.',expected_name:'My Market',account_email:'owner@example.com',
    navigation_url:'https://www.google.com/maps/place/My+Market/data=!1sfixture',
    business_url:'https://www.google.com/maps/place/My+Market/data=!1sfixture',business_key:'place:fixture',status:'posted'};
  const before=calls.length;
  assert.equal((await command('check_saved',{review})).ok,true);
  assert.equal(opened.at(-1).active,false);
  assert.equal(new URL(opened.at(-1).url).searchParams.get('authuser'),'1');
  assert.deepEqual(calls.slice(before),['reconcile']);
  assert.ok(removed.includes(opened.length+10));
  failSaved=true;
  assert.equal((await command('check_saved',{review})).ok,false);
  assert.ok(removed.includes(opened.length+10));
  const count=opened.length;
  assert.equal((await command('check_saved',{review:{...review,status:'ready'}})).ok,false);
  assert.equal((await command('check_saved',{review:{...review,business_url:'https://evil.example/maps'}})).ok,false);
  assert.equal(opened.length,count);
  assert.ok(!calls.includes('prepare') && !calls.includes('submit'));
  console.log(kind+": ping, sign-in URL validation and sender isolation passed");
}

(async()=>{
  const root=path.resolve(__dirname,"..");
  await exercise(path.join(root,"chrome_extension"),"chrome");
  await exercise(path.join(root,"firefox_extension"),"firefox");
})().catch(error=>{console.error(error);process.exitCode=1;});
