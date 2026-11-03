"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const {webcrypto}=require("node:crypto");
const root=path.resolve(__dirname,"..");
const context={URL,URLSearchParams,setTimeout,clearTimeout,Date,Promise,Map,Set,performance,
  crypto:webcrypto,AbortController,TextDecoder,Uint8Array,fixtureResponse:response};
// Firefox's native Window.fetch checks its receiver; arrow-only fixtures hide
// the illegal invocation caused by storing it as a method on the guard object.
vm.runInNewContext(`globalThis.fetch=function(url){
  if(this!==globalThis) throw new TypeError("fetch called without its Window receiver");
  return Promise.resolve(fixtureResponse(url));
};`,context);
vm.runInNewContext(fs.readFileSync(path.join(root,"chrome_extension/network_guard.js"),"utf8"),context);
const {UKNetworkGuard,parseTrace}=context.TasmeeNetworkGuard;
function response(url,text="ip=8.8.8.8\nloc=GB\n",options={}) {
  const result=new Response(text,{status:options.status || 200,headers:{"content-type":"text/plain",...options.headers}});
  Object.defineProperty(result,"url",{value:options.url || url});
  Object.defineProperty(result,"redirected",{value:Boolean(options.redirected)});
  return result;
}
async function main() {
  const nativeReceiver=new UKNetworkGuard();
  assert.equal((await nativeReceiver.check()).allowed,true,"Default fetch must retain the browser global receiver");
  assert.equal(parseTrace("ip=8.8.8.8\nloc=GB").family,4);
  assert.equal(parseTrace("ip=2606:4700:4700::1111\nloc=GB").family,6);
  for(const address of ["192.168.1.1","10.0.0.1","127.0.0.1","100.64.0.1","169.254.1.1","172.16.0.1",
    "192.0.2.1","198.18.0.1","198.51.100.1","203.0.113.1","224.1.1.1","255.255.255.255","01.2.3.4",
    "1.2.3.999","::","::1","::ffff:8.8.8.8","fe80::1","fc00::1","ff02::1","2001:db8::1","2002::1",
    "3fff::1","2606:4700::1%eth0","2606:::1","2606:1:2:3:4:5:6:7:8"]) {
    assert.throws(()=>parseTrace(`ip=${address}\nloc=GB`),undefined,address);
  }
  for(const text of ["loc=GB","ip=8.8.8.8\nloc=gb","ip=8.8.8.8\nloc=GB\nloc=US","ip=8.8.8.8\nip=1.1.1.1\nloc=GB","x".repeat(4097)])
    assert.throws(()=>parseTrace(text));
  let now=100,calls=[];
  const guard=new UKNetworkGuard({clock:()=>now,wallClock:()=>1700000000000,
    fetcher:async(url,options)=>{calls.push({url,options});return response(url);}});
  assert.equal(guard.snapshot().status,"unknown");
  const verified=await guard.check();
  assert.equal(verified.enabled,true);assert.equal(verified.allowed,true);assert.equal(verified.country,"GB");
  assert.equal(verified.policy,"uk-browser-egress-v1");assert.equal(calls.length,2);
  assert.ok(!JSON.stringify(verified).includes("8.8.8.8"));
  for(const {url,options} of calls) {
    assert.ok(url.startsWith("https://www.cloudflare.com/cdn-cgi/trace?") || url.startsWith("https://1.1.1.1/cdn-cgi/trace?"));
    assert.equal(options.credentials,"omit");assert.equal(options.redirect,"error");assert.equal(options.cache,"no-store");
    assert.equal(options.referrerPolicy,"no-referrer");
  }
  await guard.check();assert.equal(calls.length,4);
  now+=30001;assert.equal(guard.snapshot().allowed,false);assert.equal(guard.snapshot().status,"unknown");
  assert.throws(()=>guard.requireFresh());
  assert.equal(new UKNetworkGuard({enabled:false}).snapshot().enabled,true);
  assert.equal(new UKNetworkGuard().snapshot().allowed,false);
  let index=0;
  const mixed=new UKNetworkGuard({fetcher:async url=>response(url,`ip=8.8.8.8\nloc=${index++ ? "US" : "GB"}`)});
  await assert.rejects(mixed.check(),/connect Avast/);
  assert.equal(mixed.snapshot().code,"not_uk");assert.equal(mixed.snapshot().country,"US");assert.equal(mixed.snapshot().allowed,false);
  const invalidResponses=[
    url=>response(url,"ip=8.8.8.8\nloc=GB",{status:503}),
    url=>response(url,"ip=8.8.8.8\nloc=GB",{redirected:true}),
    url=>response(url,"ip=8.8.8.8\nloc=GB",{url:"https://evil.example/"}),
    url=>response(url,"ip=8.8.8.8\nloc=GB",{headers:{"content-type":"text/html"}}),
    url=>response(url,"ip=8.8.8.8\nloc=GB",{headers:{"content-length":"5000"}}),
    url=>response(url,"x".repeat(4097)),
    url=>response(url,new Uint8Array([0xff])),
    ()=>{throw new Error("raw IP 8.8.8.8, private@example.com, cookie=SECRET");},
  ];
  for(const fetcher of invalidResponses) {
    const blocked=new UKNetworkGuard({fetcher});
    await assert.rejects(blocked.check(),error=>!error.message.includes("SECRET") && !error.message.includes("8.8.8.8"));
    assert.equal(blocked.snapshot().allowed,false);assert.equal(blocked.snapshot().status,"blocked");
    assert.ok(!JSON.stringify(blocked.snapshot()).includes("private@example.com"));
  }
  let aborted=false;
  const timed=new UKNetworkGuard({timeoutMs:10,fetcher:async(url,options)=>{
    options.signal.addEventListener("abort",()=>{aborted=true;});return new Promise(()=>{});
  }});
  await assert.rejects(timed.check());assert.equal(aborted,true);assert.equal(timed.snapshot().allowed,false);
  console.log("extension network guard: strict UK probes, private/global IP rejection, redaction, freshness and timeout passed");
}
main().catch(error=>{console.error(error);process.exitCode=1;});
