"use strict";
(() => {
  const endpoints=["https://www.cloudflare.com/cdn-cgi/trace","https://1.1.1.1/cdn-cgi/trace"];
  const maximumBytes=4096, maximumAgeMs=30000;
  function publicFamily(address) {
    if(typeof address!=="string" || address.length>45 || /[\s%\[\]]/.test(address)) throw new Error("Invalid public address.");
    if(address.includes(".")) {
      if(!/^(?:0|[1-9]\d{0,2})(?:\.(?:0|[1-9]\d{0,2})){3}$/.test(address)) throw new Error("Invalid public address.");
      const [a,b,c,d]=address.split(".").map(Number);
      if([a,b,c,d].some(value=>value>255) || a===0 || a===10 || a===127 || a>=224 ||
        (a===100 && b>=64 && b<=127) || (a===169 && b===254) || (a===172 && b>=16 && b<=31) ||
        (a===192 && (b===168 || (b===0 && [0,2].includes(c)) || (b===88 && c===99))) ||
        (a===198 && (b===18 || b===19 || (b===51 && c===100))) || (a===203 && b===0 && c===113))
        throw new Error("Address is not public unicast.");
      return 4;
    }
    const parts=address.split("::");
    if(parts.length>2) throw new Error("Invalid public address.");
    const left=parts[0] ? parts[0].split(":") : [],right=parts.length===2 && parts[1] ? parts[1].split(":") : [];
    const groups=[...left,...right];
    if(groups.some(part=>! /^[a-f0-9]{1,4}$/i.test(part)) ||
      (parts.length===1 && left.length!==8) || (parts.length===2 && groups.length>=8)) throw new Error("Invalid public address.");
    const words=[...left,...Array(parts.length===2 ? 8-groups.length : 0).fill("0"),...right].map(part=>parseInt(part,16));
    if(words.length!==8 || words[0]<0x2000 || words[0]>0x3fff ||
      (words[0]===0x2001 && (words[1]<0x200 || words[1]===0xdb8)) || words[0]===0x2002 ||
      (words[0]===0x3fff && words[1]<0x1000)) throw new Error("Address is not public unicast.");
    return 6;
  }
  function parseTrace(text) {
    if(typeof text!=="string" || text.length>maximumBytes) throw new Error("Invalid trace response.");
    const fields={};
    for(const line of text.split(/\r?\n/)) {
      const separator=line.indexOf("="),key=line.slice(0,separator);
      if(separator<0 || !["ip","loc"].includes(key)) continue;
      if(Object.hasOwn(fields,key)) throw new Error("Ambiguous trace response.");
      fields[key]=line.slice(separator+1).trim();
    }
    if(!/^[A-Z]{2}$/.test(fields.loc || "")) throw new Error("Invalid country response.");
    return {country:fields.loc,family:publicFamily(fields.ip)};
  }
  class UKNetworkGuard {
    // Firefox's Window.fetch rejects being called with this guard as its receiver.
    constructor({fetcher=globalThis.fetch.bind(globalThis),clock=()=>performance.now(),wallClock=()=>Date.now(),timeoutMs=8000}={}) {
      this.fetcher=fetcher;this.clock=clock;this.wallClock=wallClock;this.timeoutMs=timeoutMs;
      this.verifiedAt=null;this.queue=Promise.resolve();
      this.state={status:"unknown",country:"",code:"not_checked",checked_at:"",expires_at:"",address_families:[]};
    }
    snapshot() {
      const fresh=this.verifiedAt!==null && this.clock()-this.verifiedAt>=0 && this.clock()-this.verifiedAt<maximumAgeMs;
      const result={...this.state,address_families:[...this.state.address_families],enabled:true,
        allowed:this.state.status==="verified" && fresh,policy:"uk-browser-egress-v1",max_age_seconds:30};
      if(result.status==="verified" && !fresh) {result.status="unknown";result.code="check_expired";}
      return result;
    }
    requireFresh() {
      if(!this.snapshot().allowed) throw new Error("UK-IP check expired. Check the connection again before continuing.");
    }
    check() {
      const task=this.queue.catch(()=>{}).then(()=>this.runCheck());
      this.queue=task.catch(()=>{});
      return task;
    }
    async readEndpoint(endpoint) {
      const controller=new AbortController();let reader=null,timer;
      const url=endpoint+"?tasmee_check="+crypto.randomUUID();
      const timeout=new Promise((resolve,reject)=>{timer=setTimeout(()=>{
        controller.abort();reject(new Error("Network check timed out."));
      },this.timeoutMs);});
      const download=(async()=>{
        const response=await this.fetcher(url,{method:"GET",credentials:"omit",cache:"no-store",redirect:"error",
          referrerPolicy:"no-referrer",signal:controller.signal});
        if(response.status!==200 || response.redirected || response.url!==url ||
          !/^text\/plain(?:\s*;|$)/i.test(response.headers.get("content-type") || "")) throw new Error("Invalid trace response.");
        const length=response.headers.get("content-length");
        if(length && (!/^\d+$/.test(length) || Number(length)>maximumBytes)) throw new Error("Trace response too large.");
        if(!response.body?.getReader) throw new Error("Trace stream unavailable.");
        reader=response.body.getReader();const chunks=[];let size=0;
        while(true) {
          const {done,value}=await reader.read();if(done) break;
          size+=value.byteLength;if(size>maximumBytes || chunks.length>=maximumBytes) throw new Error("Trace response too large.");
          chunks.push(value);
        }
        const bytes=new Uint8Array(size);let offset=0;
        for(const chunk of chunks) {bytes.set(chunk,offset);offset+=chunk.byteLength;}
        return parseTrace(new TextDecoder("utf-8",{fatal:true}).decode(bytes));
      })();
      try {return await Promise.race([download,timeout]);}
      finally {clearTimeout(timer);controller.abort();if(reader) reader.cancel().catch(()=>{});}
    }
    async runCheck() {
      let country="",code="check_unavailable";const families=new Set();
      try {
        for(const endpoint of endpoints) {
          const result=await this.readEndpoint(endpoint);country=result.country;families.add(result.family);
          if(country!=="GB") {code="not_uk";throw new Error("Non-UK country.");}
        }
        this.verifiedAt=this.clock();const checked=this.wallClock();
        this.state={status:"verified",country:"GB",code:"uk_verified",checked_at:new Date(checked).toISOString(),
          expires_at:new Date(checked+maximumAgeMs).toISOString(),address_families:[...families].sort()};
        return this.snapshot();
      } catch {
        this.verifiedAt=null;
        this.state={status:"blocked",country,code,checked_at:new Date(this.wallClock()).toISOString(),expires_at:"",
          address_families:[...families].sort()};
        throw new Error(code==="not_uk" ? "UK-IP protection blocked this action: connect Avast to a UK server and check again." :
          "UK IP could not be confirmed. Check Avast/internet and retry; there is no unverified fallback.");
      }
    }
  }
  globalThis.TasmeeNetworkGuard=Object.freeze({UKNetworkGuard,parseTrace});
})();
