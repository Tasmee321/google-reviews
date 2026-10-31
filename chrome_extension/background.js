"use strict";
const mapsHosts = new Set(["www.google.com","google.com","maps.google.com","www.google.co.uk","www.google.com.pk"]);
const allowedActions = new Set(["ping","login","check","resolve","prepare","verify","submit","discard","reconcile","check_saved"]);
const accountIndexes=new Map();
function accountUrl(url, email, selecting=false) {
  const parsed = new URL(safeTarget(url));
  if(mapsHosts.has(parsed.hostname)) {
    if(selecting) parsed.searchParams.set("authuser",email);
    else if(accountIndexes.has(email)) parsed.searchParams.set("authuser",accountIndexes.get(email));
  }
  return parsed.href;
}
function dashboardSender(sender) {
  try {
    const url = new URL(sender.url);
    return sender.id===chrome.runtime.id && sender.frameId === 0 && sender.tab?.id !== undefined && url.protocol === "http:" &&
      ["127.0.0.1","localhost"].includes(url.hostname) && url.pathname === "/";
  } catch {return false;}
}
function safeMaps(url) {
  const parsed = new URL(url);
  if(parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port ||
     !mapsHosts.has(parsed.hostname) || !parsed.pathname.startsWith("/maps")) throw new Error("Only a verified Google Maps page is supported.");
  return parsed.href;
}
function safeTarget(url) {
  const parsed = new URL(url);
  if(parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port) throw new Error("Invalid business link.");
  if(parsed.hostname === "maps.app.goo.gl" || (parsed.hostname === "goo.gl" && parsed.pathname.startsWith("/maps/"))) return parsed.href;
  return safeMaps(url);
}
function cleanReview(review) {
  if(!review || !/^[a-f0-9]{24}$/.test(review.id) || !Number.isInteger(review.stars) || review.stars<1 || review.stars>5 ||
     typeof review.text!=="string" || !review.text.trim() || review.text.length>4000 ||
     typeof review.expected_name!=="string" || !review.expected_name.trim() || review.expected_name.length>200 ||
     typeof review.account_email!=="string" || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(review.account_email)) throw new Error("Invalid review request.");
  return {id:review.id, text:review.text, stars:review.stars, expected_name:review.expected_name,
    account_email:review.account_email.toLowerCase(), business_key:review.business_key || "", navigation_url:accountUrl(review.navigation_url,review.account_email.toLowerCase())};
}
async function waitLoaded(tabId) {
  const deadline=Date.now()+45000;
  while(Date.now()<deadline) {
    const tab=await chrome.tabs.get(tabId);
    if(tab.status==="complete") {safeMaps(tab.url);return;}
    await new Promise(resolve=>setTimeout(resolve,200));
  }
  throw new Error("Google Maps took too long to load. Check the tab and your internet connection.");
}
async function google(tabId, action, review) {
  const tab=await chrome.tabs.get(tabId);safeMaps(tab.url);
  const result=await chrome.tabs.sendMessage(tabId,{type:"TASMEE_GOOGLE",action,review},{frameId:0});
  if(!result?.ok) throw new Error(result?.message || "The Google Maps page could not be verified.");
  return result;
}
const widgetPath="/maps/api/js/ReviewsService.LoadWriteWidget";
function safeWidget(url) {
  const parsed=new URL(safeMaps(url));
  if(parsed.pathname!==widgetPath || !parsed.searchParams.get("placeid") ||
     !/^\d+$/.test(parsed.searchParams.get("authuser") || "")) throw new Error("Unverified Google review iframe.");
  return parsed.href;
}
let registrations=Promise.resolve();
async function registerWidget(sender) {
  if(sender.id!==chrome.runtime.id || !Number.isInteger(sender.frameId) || sender.frameId<=0 || sender.tab?.id===undefined)
    throw new Error("Invalid review iframe sender.");
  safeMaps(sender.tab.url);
  const url=safeWidget(sender.url),key="widget:"+sender.tab.id;
  const current=(await chrome.storage.session.get(key))[key] || {};
  current[sender.frameId]={frameId:sender.frameId,url};
  await chrome.storage.session.set({[key]:current});
  return {ok:true};
}
async function widgetRequest(message,sender) {
  if(sender.id!==chrome.runtime.id || sender.frameId!==0 || sender.tab?.id===undefined)
    throw new Error("Only the verified Maps tab can request its review iframe.");
  const parent=new URL(safeMaps(sender.url));
  const review=cleanReview(message.review),key="review:"+review.id;
  const stored=(await chrome.storage.session.get(key))[key];
  const phases={prepare:["preparing"],verify:["ready","submitting"],submit:["submitting"]};
  if(!stored || stored.tabId!==sender.tab.id || !phases[message.action]?.includes(stored.phase) ||
     ["text","stars","expected_name","account_email"].some(field=>stored.review[field]!==review[field]))
    throw new Error("This iframe action is not authorized by the dashboard review.");
  const expected=safeWidget(message.url),url=new URL(expected);
  if(url.origin!==parent.origin || url.searchParams.get("authuser")!==(parent.searchParams.get("authuser") || "0"))
    throw new Error("The review iframe belongs to a different Google account or origin.");
  const deadline=Date.now()+15000;
  while(Date.now()<deadline) {
    const frames=(await chrome.storage.session.get("widget:"+stored.tabId))["widget:"+stored.tabId] || {};
    const matches=Object.values(frames).filter(frame=>frame.url===expected);
    if(matches.length>1) throw new Error("More than one matching review iframe is open. Prepare a new preview.");
    if(matches.length===1) {
      // Never retry submission: a dropped reply may already have reached Google.
      const response=await chrome.tabs.sendMessage(stored.tabId,
        {type:"TASMEE_WIDGET",action:message.action,review,url:expected},{frameId:matches[0].frameId});
      if(!response?.ok) throw new Error(response?.message || "The Google review iframe could not be verified.");
      return response;
    }
    await new Promise(resolve=>setTimeout(resolve,150));
  }
  throw new Error("Google's review iframe did not finish loading. Keep its Maps tab open and prepare again.");
}
async function command(action,data,sender) {
  if(action==="ping") {
    const manifest=chrome.runtime.getManifest();
    return {ok:true,version:manifest.version,capabilities:["saved_checks","account_selection"],browser_kind:manifest.browser_specific_settings?.gecko ? "firefox" : "chrome"};
  }
  if(action==="login") {
    if(typeof data?.email!=="string" || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email) || data.email.length>254)
      throw new Error("Enter a valid Google email.");
    const url=new URL("https://accounts.google.com/ServiceLogin");
    url.search=new URLSearchParams({continue:"https://www.google.com/maps?hl=en",hl:"en",Email:data.email}).toString();
    await chrome.tabs.create({url:url.href,active:true});
    return {ok:true};
  }
  if(action==="check") {
    if(data?.email && (typeof data.email!=="string" || data.email.length>254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email)))
      throw new Error("Invalid selected account email.");
    const url=data?.email ? accountUrl("https://www.google.com/maps?hl=en",data.email.toLowerCase(),true) : "https://www.google.com/maps?hl=en";
    const tab=await chrome.tabs.create({url,active:true});
    await waitLoaded(tab.id);
    const result=await google(tab.id,"account");
    if(data?.email && result.email!==data.email.toLowerCase()) throw new Error("Switch to the selected Google account in Maps, then check again.");
    if(/^\d+$/.test(String(result.account_index))) {
      accountIndexes.set(result.email,String(result.account_index));
      await chrome.storage.session.set({["account:"+result.email]:String(result.account_index)});
    }
    await chrome.tabs.update(sender.tab.id,{active:true});
    await chrome.tabs.remove(tab.id).catch(()=>{});
    return result;
  }
  const resolutionKey="resolved:"+sender.tab.id;
  const email=data?.account_email || data?.review?.account_email;
  if(typeof email==="string" && !accountIndexes.has(email.toLowerCase())) {
    const index=(await chrome.storage.session.get("account:"+email.toLowerCase()))["account:"+email.toLowerCase()];
    if(/^\d+$/.test(String(index))) accountIndexes.set(email.toLowerCase(),String(index));
  }
  if(action==="resolve") {
    const account_email=data?.account_email;
    if(typeof account_email!=="string" || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(account_email)) throw new Error("Check your Google connection first.");
    const navigation_url=accountUrl(data?.navigation_url,account_email.toLowerCase());
    const previous=(await chrome.storage.session.get(resolutionKey))[resolutionKey];
    await chrome.storage.session.remove(resolutionKey);
    if(previous) await chrome.tabs.remove(previous.tabId).catch(()=>{});
    const tab=await chrome.tabs.create({url:navigation_url,active:true});
    try {
      await waitLoaded(tab.id);
      const response=await google(tab.id,"resolve",{navigation_url,account_email:account_email.toLowerCase()});
      await chrome.storage.session.set({[resolutionKey]:{tabId:tab.id,navigation_url}});
      await chrome.tabs.update(sender.tab.id,{active:true});
      return response;
    } catch(error) {
      await chrome.tabs.update(sender.tab.id,{active:true}).catch(()=>{});
      throw error;
    }
  }
  const review=cleanReview(data?.review);
  const key="review:"+review.id;
  const stored=(await chrome.storage.session.get(key))[key];
  if(action==="check_saved") {
    if(!["posted","unconfirmed"].includes(data.review.status)) throw new Error("Only saved or uncertain submissions can be checked.");
    const tab=await chrome.tabs.create({url:accountUrl(safeMaps(data.review.business_url),review.account_email),active:false});
    try {
      await waitLoaded(tab.id);
      // Strictly read-only: this never opens a writer, fills fields or submits.
      return await google(tab.id,"reconcile",review);
    } finally {await chrome.tabs.remove(tab.id).catch(()=>{});}
  }
  if(action==="reconcile") {
    if(data.review.status!=="unconfirmed") throw new Error("Only an uncertain submission can be checked.");
    const tab=await chrome.tabs.create({url:accountUrl(safeMaps(data.review.business_url),review.account_email),active:true});
    try {
      await waitLoaded(tab.id);
      return await google(tab.id,"reconcile",review);
    } finally {await chrome.tabs.update(sender.tab.id,{active:true}).catch(()=>{});}
  }
  if(action==="prepare") {
    if(stored) throw new Error("This review was already prepared. Cancel it and create a new draft.");
    const resolved=(await chrome.storage.session.get(resolutionKey))[resolutionKey];
    await chrome.storage.session.remove(resolutionKey);
    let tab;
    if(resolved?.navigation_url===review.navigation_url) {
      tab=await chrome.tabs.get(resolved.tabId);
      safeMaps(tab.url);
    } else tab=await chrome.tabs.create({url:review.navigation_url,active:true});
    const state={tabId:tab.id,ownerTab:sender.tab.id,phase:"preparing",review};
    await chrome.storage.session.set({[key]:state});
    let response;
    try {
      await waitLoaded(tab.id);
      response=await google(tab.id,"prepare",review);
      await chrome.storage.session.set({[key]:{...state,phase:"ready"}});
    } catch(error) {
      await chrome.storage.session.remove(key);
      await chrome.tabs.update(sender.tab.id,{active:true}).catch(()=>{});
      throw error;
    }
    await chrome.tabs.update(sender.tab.id,{active:true});
    return response;
  }
  if(!stored || stored.ownerTab!==sender.tab.id) throw new Error("The prepared tab is no longer available in this dashboard. Prepare again.");
  if(action==="discard") {
    if(stored.phase==="submitting") throw new Error("Submission has already started. Check Google Maps.");
    await chrome.storage.session.remove(key);
    await chrome.tabs.remove(stored.tabId).catch(()=>{});
    return {ok:true};
  }
  if(stored.phase!=="ready") throw new Error("Submission already started. Do not post again.");
  if(action==="verify") return google(stored.tabId,"verify",review);
  if(action==="submit") {
    await chrome.storage.session.set({[key]:{...stored,phase:"submitting"}});
    const result=await google(stored.tabId,"submit",review);
    await chrome.tabs.update(sender.tab.id,{active:true});
    return result;
  }
  throw new Error("Unsupported action.");
}
// Serialize commands so double clicks cannot race the submission marker.
let commands=Promise.resolve();
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(message?.type==="TASMEE_WIDGET_READY") {
    const task=registrations.then(()=>registerWidget(sender));
    registrations=task.catch(()=>{});
    task.then(reply,error=>reply({ok:false,message:error.message}));
    return true;
  }
  if(message?.type==="TASMEE_WIDGET_REQUEST") {
    // Separate from the dashboard queue: the current prepare/verify/submit
    // command is awaiting this narrowly authorized nested iframe request.
    widgetRequest(message,sender).then(reply,error=>reply({ok:false,message:error.message}));
    return true;
  }
  if(message?.type!=="TASMEE_COMMAND" || !allowedActions.has(message.action) || !dashboardSender(sender)) return;
  const task=commands.then(()=>command(message.action,message.data,sender));
  commands=task.catch(()=>{});
  task.then(reply,error=>reply({ok:false,message:error.message}));
  return true;
});
