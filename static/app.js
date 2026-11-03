"use strict";
if(location.hash.startsWith("#unlock=")) history.replaceState(null,"",location.pathname+location.search);
const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const selectedBrowser=document.querySelector('meta[name="review-browser"]')?.content || "firefox";
const browserLabel=document.querySelector('meta[name="browser-label"]')?.content || (selectedBrowser==="firefox" ? "Firefox" : "Chrome");
const reloadHint=selectedBrowser==="firefox" ? "Update the signed Tasmee add-on in about:addons" : "Reload Tasmee in chrome://extensions/";
const activeStates = new Set(["queued","preparing","ready","publishing","submitting"]);
const labels = {queued:"Queued",preparing:"Preparing",ready:"Ready to post",publishing:"Checking",submitting:"Submitting",posted:"Success",unconfirmed:"Check Google Maps",failed:"Needs attention",cancelled:"Cancelled",interrupted:"Interrupted",resolved:"Business found"};
let browser = {status:"disconnected",email:"",busy:false}, reviews = [], selectedId = null, requesting = false, polling = false;
let lastHistory = "", lastPreview = "", resolvedBusiness = null, resolving = false;
let draftReviewId=null, historyTotal=0, accounts=[], businesses=[], accountSignature="", statsSignature="", historyExpanded=false;
let extensionCapabilities=[], monitoring=false, lastConnectedEmail="";
const monitorKey="tasmee.saved-monitor.v1", cadenceKey="tasmee.saved-monitor.next.v1";
let nextCheckAt=Date.now()+60000;
try {nextCheckAt=Math.max(nextCheckAt, Number(localStorage.getItem(cadenceKey)) || 0);} catch {}
const storageKey = "tasmee.personal-review.draft.v1";
let extensionInstalled=false, extensionChecked=false;
let policyRequest=0;
let changingCity=false, statusLoaded=false;
let policyReviewId=null;
let networkFlight=null;
const protectedApi = new Set(["/api/browser/login","/api/browser/check","/api/browser/select","/api/browser/verified","/api/business/resolve","/api/reviews"]);
function requiresNetwork(path) {
  return protectedApi.has(path) || /^\/api\/reviews\/[a-f0-9]{24}\/(publish|submitting|check-start|reconcile)$/.test(path);
}
function compatibleExtension(result) {
  const parts=typeof result.version==="string" && /^(\d{1,4})\.(\d{1,4})\.(\d{1,4})$/.exec(result.version);
  const version=parts && parts.slice(1).map(Number);
  return version && (version[0]>1 || version[0]===1 && (version[1]>0 || version[1]===0 && version[2]>=7)) &&
    Array.isArray(result.capabilities) && result.capabilities.includes("uk_network_guard");
}
async function checkNetwork() {
  if(networkFlight) return networkFlight;
  networkFlight=(async()=>{
    if($("networkStatus")) $("networkStatus").textContent="Checking this browser's UK IP…";
    try {
      const challenge=await api("/api/browser/network",{});
      if(!challenge.requires_extension) return challenge.network;
      const extension=await extensionRequest("ping",{},2000);
      extensionInstalled=true;
      const result=await extensionRequest("network_check",{challenge:challenge.challenge},20000);
      if(result.challenge!==challenge.challenge) throw new Error("UK-IP check did not match this request. Check again.");
      const report=await api("/api/browser/network-result",{challenge:challenge.challenge,extension,network:result.network});
      browser.network=report.network;
      if(!report.network.allowed) throw new Error(report.network.message);
      return report.network;
    } catch(error) {
      if(browser.transport==="extension") {
        try {const report=await api("/api/browser/network-failure",{});browser.network=report.network;} catch {}
      }
      throw error;
    }
  })();
  try {return await networkFlight;} finally {networkFlight=null;controls();}
}

function clearPolicyWarnings() {
  policyRequest++;
  $("policyWarnings").hidden=true;
  $("policyWarningList").replaceChildren();
}
async function checkReviewPolicy() {
  const text=$("text").value, requestId=++policyRequest;
  if(!text.trim()) {clearPolicyWarnings();return;}
  const result=await api("/api/reviews/preflight",{text});
  if(requestId!==policyRequest || $("text").value!==text) return;
  $("policyWarningList").replaceChildren(...result.warnings.map(warning=>element("li","",warning.message)));
  $("policyWarnings").hidden=!result.warnings.length;
}

function extensionRequest(action,data={},timeout=150000) {
  return new Promise((resolve,reject)=>{
    const id=crypto.randomUUID();
    const timer=setTimeout(()=>{window.removeEventListener("message",receive);reject(new Error("Load the Tasmee extension in "+browserLabel+" and refresh this dashboard. If it is already loaded, check the Google Maps tab."));},timeout);
    function receive(event) {
      if(event.source!==window || event.origin!==location.origin || event.data?.type!=="TASMEE_RESPONSE" || event.data.id!==id) return;
      clearTimeout(timer);window.removeEventListener("message",receive);
      const result=event.data.response;
      if(!result?.ok) {
        const error=new Error(result?.message || "Browser extension did not complete the action.");
        if(result?.network && !result.network.allowed && browser.transport==="extension") {
          api("/api/browser/network-failure",{}).then(report=>{browser.network=report.network;controls();}).finally(()=>reject(error)).catch(()=>{});
        } else reject(error);
      }
      else if(action==="ping" && selectedBrowser==="firefox" && result.browser_kind!=="firefox")
        reject(new Error("Use the dedicated Firefox dashboard, not personal Chrome."));
      else if(action==="ping" && !compatibleExtension(result)) {
        extensionInstalled=false;
        reject(new Error(reloadHint+" to version 1.0.7 or later for UK-IP protection, then refresh this dashboard."));
      }
      else {
        if(action==="ping" && typeof result.version==="string")
          $("extensionState").title="Extension version: "+result.version;
        if(action==="ping") extensionCapabilities=result.capabilities || [];
        resolve(result);
      }
    }
    window.addEventListener("message",receive);
    window.postMessage({type:"TASMEE_REQUEST",id,action,data},location.origin);
  });
}
async function reportExtensionFailure(review,error) {
  try {await api("/api/reviews/"+review.id+"/failure",{confirmation_token:review.confirmation_token,message:error.message});} catch {}
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function notice(message, error=false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
  $("notice").hidden = !message;
}
async function api(path, data) {
  if(data!==undefined && browser.transport==="extension" && requiresNetwork(path)) await checkNetwork();
  const response = await fetch(path, data === undefined ? {cache:"no-store"} : {
    method:"POST", headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
    body:JSON.stringify(data)
  });
  let result;
  try { result = await response.json(); } catch { throw new Error("The app could not be reached. Restart run.bat and refresh."); }
  if (!response.ok) {
    const error = new Error(result.message || "Request failed.");
    error.fields = result.fields || {};
    throw error;
  }
  return result;
}
function errors(fields={}) {
  for (const key of ["target","expected_name","text","stars","email","policy_confirmed"]) {
    const errorNode = $(key + "Error");
    if (errorNode) { errorNode.hidden = !fields[key]; errorNode.textContent = fields[key] || ""; }
    if ($(key)) $(key).setAttribute("aria-invalid", fields[key] ? "true" : "false");
  }
  const summary = $("formErrors");
  summary.replaceChildren(); summary.hidden = !Object.keys(fields).length;
  if (!summary.hidden) {
    summary.append(element("strong", "", "Please check these fields:"));
    const list = element("ul");
    Object.entries(fields).forEach(([key,message]) => {
      const item=element("li"), link=element("a","",message);
      link.href = "#" + key;
      item.append(link); list.append(item);
    });
    summary.append(list); summary.focus();
  }
}
function formData() {
  let target=$("target").value.trim();
  const city=$("searchCity")?.value || "";
  if(target && !/^(?:[a-z][a-z0-9+.-]*:|\/\/|www\.|maps\.|google\.)/i.test(target))
    target += ", " + (city || "United Kingdom");
  return {
    target, expected_name:$("expected_name").value.trim(),
    text:$("text").value.trim(), stars:Number(document.querySelector('input[name="stars"]:checked')?.value || 0),
    account_email:browser.email
  };
}
function saveDraft() {
  $("characterCount").textContent = $("text").value.length.toLocaleString() + " / 4,000";
  const selected = Number(document.querySelector('input[name="stars"]:checked')?.value || 0);
  $("ratingDescription").textContent = selected ? ["","1 star · Poor","2 stars · Below expectations","3 stars · Average","4 stars · Good","5 stars · Excellent"][selected] : "Select a rating that reflects your visit.";
}
function clearComposer() {
  const city=$("searchCity")?.value || "";
  $("reviewForm").reset();
  if($("searchCity")) $("searchCity").value=city;
  for(const key of ["target","expected_name","text"]) $(key).value="";
  document.querySelectorAll('input[name="stars"]').forEach(node=>node.checked=false);
  try { localStorage.removeItem(storageKey); } catch {}
  resolvedBusiness=null;draftReviewId=null;
  clearPolicyWarnings();
  errors();saveDraft();
}
function clearDraft() {
  clearComposer();
  selectedId=null;resolvedBusiness=null;lastPreview="";
  $("previewDetails").open=false;
  errors();notice("");
  saveDraft();
}
function badge(node, status, title) {
  node.textContent = title || labels[status] || status;
  node.className = "badge" + (["connected","posted"].includes(status) ? " good" : ["ready","preparing","queued","publishing","submitting","unconfirmed"].includes(status) ? " warn" : ["failed","error","interrupted"].includes(status) ? " bad" : "");
}
function controls() {
  const active=reviews.find(review=>activeStates.has(review.status));
  const locked=requesting || monitoring || Boolean(active);
  $("draftFields").disabled=locked;
  if($("searchCity")) $("searchCity").disabled=!statusLoaded || locked || browser.busy;
  $("prepareButton").disabled=locked || browser.status!=="connected" || browser.busy;
  $("prepareButton").textContent=resolving ? "Fetching business…" : active && ["queued","preparing"].includes(active.status) ? "Preparing review…" : "Start →";
  $("connectButton").disabled=requesting || browser.busy || Boolean(active);
  $("checkButton").disabled=requesting || browser.busy || Boolean(active);
  $("email").disabled=requesting || browser.busy || Boolean(active);
  $("publishButton").disabled=requesting || browser.busy;
  $("policy_confirmed").disabled=browser.busy;
  if($("networkCheckButton")) $("networkCheckButton").disabled=requesting || browser.busy || Boolean(active);
  $("reconcileButton").disabled=requesting || browser.busy || Boolean(active);
  $("checkSavedButton").disabled=locked || browser.busy;
  $("accountSelect").disabled=locked || browser.busy;
  $("switchAccountButton").disabled=locked || browser.busy || !$("accountSelect").value;
  $("forgetAccountButton").disabled=locked || browser.busy || !$("accountSelect").value;
  $("clearHistoryButton").disabled=locked || browser.busy || !historyTotal;
  document.querySelectorAll('.history-delete').forEach(node=>node.disabled=locked || browser.busy || node.dataset.active==="true");
  $("cancelButton").disabled=requesting || (active?.status==="ready" && browser.busy);
  const capable=extensionCapabilities.includes("saved_checks");
  badge($("monitorStatus"), monitoring ? "preparing" : "idle", !capable ? (browser.transport==="poster" ? "Unavailable" : "Needs signed 1.0.7") : !$("autoCheck").checked ? "Paused" : browser.status!=="connected" ? "Connect Google" : locked || browser.busy ? "Waiting for idle" : "Monitoring saved status");
  renderCityLocation();
  if($("networkStatus")) {
    const network=browser.network;
    $("networkStatus").textContent=networkFlight ? "Checking this browser's UK IP…" : network ? network.message+(network.checked_at ? " Last check: "+new Date(network.checked_at).toLocaleTimeString() : "") : "Check UK IP before signing in.";
  }
}
function renderCityLocation(syncSelection=false) {
  const node=$("cityLocation");if(!node) return;
  const supported=browser.transport==="poster" && extensionCapabilities.includes("city_geolocation");
  node.hidden=!supported;if(!supported) return;
  const location=browser.location;
  node.textContent=changingCity ? "Applying city location…" : location?.enabled ?
    "Browser location ON: "+(location.selection || "coordinates from config")+". IP unchanged." :
    "City location OFF. Choose a city to turn it on; IP stays controlled by Avast.";
  if(syncSelection && !changingCity && $("searchCity").value!==(location?.selection || "")) {
    $("searchCity").value=location?.selection || "";
    invalidateBusiness();
  }
}
function renderPreview() {
  const review=reviews.find(item=>item.id===selectedId) || resolvedBusiness;
  const signature=JSON.stringify(review);
  if(signature===lastPreview) { controls(); return; }
  lastPreview=signature;
  $("previewEmpty").hidden=Boolean(review); $("previewContent").hidden=!review;
  const ready=review?.status==="ready";
  $("policyConfirmation").hidden=!ready;
  if(!ready || policyReviewId!==review?.id) {
    $("policy_confirmed").checked=false;
    $("policy_confirmedError").hidden=true;
    policyReviewId=ready ? review.id : null;
    $("preparedPolicyWarnings").replaceChildren();
    if(ready) {
      $("previewDetails").open=true;
      const reviewId=review.id;
      api("/api/reviews/preflight",{text:review.text,review_id:reviewId}).then(result=>{
        if(policyReviewId===reviewId) $("preparedPolicyWarnings").replaceChildren(...result.warnings.map(warning=>element("li","",warning.message)));
      }).catch(error=>notice(error.message,true));
    }
  }
  badge($("reviewStatus"),review?.status || "idle",review ? undefined : "No review yet");
  if (!review) return;
  $("previewBusiness").textContent=review.business_name || review.expected_name;
  $("previewLink").hidden=!review.business_url;
  if(review.business_url) $("previewLink").href=review.business_url;
  $("previewAddress").textContent=review.business_address ||
    (["queued","preparing"].includes(review.status) ? "Google Maps se business location check ho rahi hai…" :
     "Address available nahi hai. Google Maps link khol kar branch check karein.");
  const hasCoordinates=Number.isFinite(review.business_latitude) && Number.isFinite(review.business_longitude);
  $("previewCoordinates").hidden=!hasCoordinates;
  $("previewCoordinates").textContent=hasCoordinates ?
    "Place coordinates: " + review.business_latitude.toFixed(6) + ", " + review.business_longitude.toFixed(6) : "";
  $("visibilityNotice").hidden=review.status!=="posted";
  $("previewEmail").textContent="Posting as " + review.account_email;
  $("previewRating").textContent="★".repeat(review.stars)+"☆".repeat(5-review.stars)+" · "+review.stars+"/5";
  $("previewText").textContent=review.text;
  $("previewDates").textContent=review.created_at ? "Created: "+new Date(review.created_at).toLocaleString()+" · Updated: "+new Date(review.updated_at).toLocaleString() : "";
  badge($("savedStatus"),review.saved_status==="verified" ? "posted" : review.saved_status==="unverified" ? "unconfirmed" : "idle",
    review.saved_status==="verified" ? "Saved · verified" : review.saved_status==="unverified" ? "Saved · not verified" : "Saved · not checked");
  $("checkMessage").textContent=(review.check_message || "Read-only saved-review verification has not run.")+
    (review.checked_at ? " Last check: "+new Date(review.checked_at).toLocaleString() : "");
  $("reviewMessage").textContent=review.message;
  $("publishButton").hidden=review.status!=="ready";
  $("reconcileButton").hidden=review.status!=="unconfirmed" || browser.transport!=="extension";
  $("checkSavedButton").hidden=!["posted","unconfirmed"].includes(review.status) || !["extension","poster"].includes(browser.transport) || !extensionCapabilities.includes("saved_checks");
  $("cancelButton").hidden=!["queued","preparing","ready"].includes(review.status);
  $("activityList").replaceChildren(...review.events.map(event=>element("li","",new Date(event.at).toLocaleString()+" · "+event.message)));
  controls();
}
function renderHistory() {
  const query=$("historySearch").value.trim().toLowerCase(), filter=$("historyFilter").value;
  const visibleReviews=reviews.filter(review=>(!filter || review.status===filter) &&
    (!query || [review.business_name,review.expected_name,review.business_address,review.account_email].join(" ").toLowerCase().includes(query)));
  const signature=JSON.stringify([reviews.map(r=>[r.id,r.status,r.updated_at]),query,filter,historyTotal,selectedId]);
  if(signature===lastHistory) return;
  lastHistory=signature;
  $("historyCount").textContent=visibleReviews.length+" shown / "+historyTotal+" total";
  $("historyEmpty").hidden=Boolean(visibleReviews.length);
  $("historyEmpty").textContent=historyTotal ? "No matching entries in loaded history." : "No local review history yet.";
  $("loadHistoryButton").hidden=reviews.length>=historyTotal;
  $("historyList").replaceChildren(...visibleReviews.map(review=>{
    const item=element("div","history-item");
    const row=element("button","history-row");
    row.setAttribute("aria-pressed",String(selectedId===review.id));
    row.type="button"; row.setAttribute("aria-label","View "+review.expected_name+" review, "+(labels[review.status]||review.status));
    const info=element("span","history-info");
    info.append(element("span","history-name",review.business_name||review.expected_name),element("span","history-date",new Date(review.created_at).toLocaleString()));
    info.append(element("span","history-date",review.business_address || "Address not recorded"),element("span","history-date",review.account_email));
    const status=element("span"); badge(status,review.status);
    row.append(info,element("span","history-stars",review.stars+" / 5 stars"),status);
    row.addEventListener("click",()=>{selectedId=review.id;renderPreview();$("previewDetails").open=true;$("activityDetails").open=true;renderHistory();$("previewPanel").scrollIntoView({block:"nearest"});});
    const remove=element("button","button quiet danger history-delete","Delete");
    remove.type="button";remove.dataset.active=String(activeStates.has(review.status));
    remove.setAttribute("aria-label","Delete local history for "+(review.business_name||review.expected_name));
    remove.addEventListener("click",()=>deleteLocal(review));
    item.append(row,remove);return item;
  }));
  controls();
}
function renderAccounts() {
  const signature=JSON.stringify([accounts,browser.email]);
  if(signature===accountSignature) return;
  accountSignature=signature;
  const selected=$("accountSelect").value;
  const placeholder=element("option","",accounts.length ? "Choose a saved account" : "Connect an account first");placeholder.value="";
  $("accountSelect").replaceChildren(placeholder,...accounts.map(account=>{
    const option=element("option","",account.email+(browser.email===account.email ? " · connected" : " · shortcut"));
    option.value=account.email;return option;
  }));
  $("accountSelect").value=accounts.some(account=>account.email===selected) ? selected : accounts.some(account=>account.email===browser.email) ? browser.email : "";
}
function renderStatistics() {
  const signature=JSON.stringify(businesses);if(signature===statsSignature) return;statsSignature=signature;
  const total=businesses.reduce((sum,b)=>sum+b.posted+b.pending,0);
  $("submissionCount").textContent=total+" tracked submissions";
  $("businessStats").replaceChildren(...businesses.map(b=>{
    const row=element("div","business-stat"),info=element("div");
    info.append(element("h3","",b.name),element("p","hint",b.address || "Address not recorded"));
    row.append(info,element("span","badge",b.posted+" submitted · "+b.pending+" pending"));return row;
  }));
  if(!businesses.length) $("businessStats").append(element("p","hint","No submitted or pending review records yet."));
}
function confirmLocal(message) {
  return new Promise(resolve=>{
    const dialog=$("confirmDialog");$("confirmMessage").textContent=message;
    const done=()=>{dialog.removeEventListener("close",done);resolve(dialog.returnValue==="delete");};
    dialog.returnValue="cancel";dialog.addEventListener("close",done);dialog.showModal();
  });
}
$("confirmCancel").addEventListener("click",()=>$("confirmDialog").close("cancel"));
$("confirmDelete").addEventListener("click",()=>$("confirmDialog").close("delete"));
async function deleteLocal(review=null) {
  if(requesting || monitoring) return;
  if(!await confirmLocal((review ? "Delete local details for "+(review.business_name||review.expected_name)+"?" : "Delete ALL local review history?")+" Google reviews will NOT be deleted. Review text/account details are removed from history; minimal business counts and hashed duplicate-protection receipts remain.")) return;
  action(async()=>{
    const result=await api(review ? "/api/reviews/"+review.id+"/delete" : "/api/history/clear",{confirm_local_delete:true});
    reviews=review ? reviews.filter(r=>r.id!==review.id) : [];
    if(!review || selectedId===review.id) {selectedId=null;lastPreview="";}
    notice(result.message);$("historyTitle").focus();
  });
}
async function poll() {
  if(polling || document.hidden) return;
  polling=true;
  try {
    const locationAtRequest=browser.location;
    const result=await api("/api/status");
    // Preserve only changes made during this request; a restarted server resets revisions.
    if(browser.location && browser.location!==locationAtRequest && result.browser.location &&
       browser.location.revision>result.browser.location.revision) result.browser.location=browser.location;
    browser=result.browser;
    statusLoaded=true;
    if(browser.transport==="poster") extensionCapabilities=browser.capabilities || [];
    historyTotal=result.history_total || 0;accounts=result.accounts || [];businesses=result.businesses || [];
    // Retain explicitly loaded older pages, but refresh recent records from the server.
    const incoming=new Set(result.reviews.map(r=>r.id));
    reviews=[...result.reviews,...(historyExpanded ? reviews.filter(r=>!incoming.has(r.id)) : [])];
    renderCityLocation(true);
    const completed=reviews.find(r=>r.id===draftReviewId && r.status==="posted");
    if(completed) {clearComposer();notice("Success: submission confirmed. Form cleared; details are saved in history. Public visibility remains unknown.");}
    if(browser.transport==="extension" && !extensionChecked) {
      extensionChecked=true;
      try {await extensionRequest("ping",{},1500);extensionInstalled=true;} catch {}
    }
    $("extensionSetup").hidden=browser.transport!=="extension" || extensionInstalled;
    $("extensionState").textContent=browser.transport==="poster" ? "Poster · "+browserLabel+" · no extension required" : extensionInstalled ? browserLabel+" extension connected" : browserLabel+" extension setup";
    const current=reviews.find(r=>activeStates.has(r.status));
    if(current) selectedId=current.id;
    badge($("connectionBadge"),browser.status,browser.status==="connected" ? "Google connected" : browser.busy ? "Browser working…" : browser.status==="signing_in" ? "Finish Google sign-in" : "Not connected");
    $("accountMessage").textContent=browser.message;
    if(browser.status==="connected" && browser.email!==lastConnectedEmail) {$("email").value=browser.email;lastConnectedEmail=browser.email;}
    renderAccounts();renderStatistics();renderPreview();renderHistory();controls();
  } catch(error) {notice(error.message,true);} finally {polling=false;}
}
async function action(operation) {
  if(requesting || monitoring) return;
  requesting=true; controls();notice("");
  try {await operation();await poll();}
  catch(error) {notice(error.message,true);if(error.fields && Object.keys(error.fields).length) errors(error.fields);}
  finally {requesting=false;controls();}
}
$("accountForm").addEventListener("submit",event=>{
  event.preventDefault();
  const email=$("email").value.trim();
  if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    $("emailError").hidden=false; $("emailError").textContent="Enter a valid Google email.";
    $("email").setAttribute("aria-invalid","true");$("email").focus();return;
  }
  $("emailError").hidden=true;$("email").removeAttribute("aria-invalid");
  action(async()=>{
    if(selectedBrowser==="firefox") {await extensionRequest("ping",{},2000);extensionInstalled=true;}
    const response=await api("/api/browser/login",{email});
    if(response.requires_extension) await extensionRequest("login",{email});
    notice(response.message);
  });
});
$("checkButton").addEventListener("click",()=>action(async()=>{
  const response=await api("/api/browser/check",{});
  if(response.requires_extension) {
    const extension=await extensionRequest("ping",{},2000);extensionInstalled=true;
    const result=await extensionRequest("check",{email:$("email").value.trim()});
    await api("/api/browser/verified",{email:result.email,browser_kind:extension.browser_kind});
  }
}));
$("networkCheckButton")?.addEventListener("click",()=>action(async()=>{
  const network=await checkNetwork();
  notice(network.message);
}));
$("policy_confirmed").addEventListener("change",()=>{
  $("policy_confirmedError").hidden=true;
  $("policy_confirmed").removeAttribute("aria-invalid");
});
$("reviewForm").addEventListener("submit",event=>{
  event.preventDefault(); errors();
  action(async()=>{
    const data=formData();
    if(!data.target) {errors({target:"Enter a Google Maps link or business search."});return;}
    if(["extension","poster"].includes(browser.transport)) {
      if(browser.transport==="extension") {
        const extension=await extensionRequest("ping",{},2000);
        if(!compatibleExtension(extension)) throw new Error(reloadHint+" to version 1.0.7 or later, then refresh this dashboard.");
      }
      resolving=true;controls();
      let result;
      try {
        const response=await api("/api/business/resolve",{target:data.target});
        result=browser.transport==="extension" ? await extensionRequest("resolve",response) : response;
      } finally {resolving=false;controls();}
      const info=result.assertion;
      if(!info || typeof info.name!=="string" || !info.name.trim() || info.name.length>200 || info.email!==browser.email)
        throw new Error("The business and Google account could not be verified.");
      data.expected_name=info.name;$("expected_name").value=info.name;
      selectedId=null;
      resolvedBusiness={status:"resolved",business_name:info.name,business_url:info.url,business_address:info.address,
        business_latitude:info.latitude,business_longitude:info.longitude,
        account_email:info.email,stars:data.stars,text:data.text,events:[],message:"Business fetched. Select your rating and enter your review, then click Start."};
      renderPreview();
    }
    const invalid={};
    if(!data.expected_name) invalid.expected_name="Enter the exact business name.";
    if(!data.stars) invalid.stars="Select a rating from 1 to 5 stars.";
    if(!data.text) invalid.text="Write your review.";
    if(Object.keys(invalid).length) {errors(invalid);return;}
    await checkReviewPolicy();
    const result=await api("/api/reviews",data);
    selectedId=result.review.id;draftReviewId=result.review.id;lastPreview="";
    if(result.requires_extension) {
      try {
        const prepared=await extensionRequest("prepare",{review:result.review});
        await api("/api/reviews/"+result.review.id+"/prepared",{confirmation_token:result.review.confirmation_token,assertion:prepared.assertion});
      } catch(error) {await reportExtensionFailure(result.review,error);throw error;}
    }
  });
});
$("publishButton").addEventListener("click",()=>action(async()=>{
  const review=reviews.find(r=>r.id===selectedId);
  if(!review || review.status!=="ready") throw new Error("Prepare the review before posting.");
  if(!$("policy_confirmed").checked) {
    $("policy_confirmedError").hidden=false;
    $("policy_confirmedError").textContent="Check this exact review and confirm the policy points before posting.";
    $("policy_confirmed").setAttribute("aria-invalid","true");
    $("policy_confirmed").focus();return;
  }
  const result=await api("/api/reviews/"+review.id+"/publish",{confirmation_token:review.confirmation_token,policy_confirmed:true});
  if(result.requires_extension) {
    try {
      const checked=await extensionRequest("verify",{review:result.review});
      await api("/api/reviews/"+review.id+"/submitting",{confirmation_token:review.confirmation_token,assertion:checked.assertion});
      const submitted=await extensionRequest("submit",{review:result.review});
      await api("/api/reviews/"+review.id+"/result",{confirmation_token:review.confirmation_token,confirmed:submitted.confirmed});
    } catch(error) {await reportExtensionFailure(review,error);throw error;}
  }
}));
$("reconcileButton").addEventListener("click",()=>action(async()=>{
  const review=reviews.find(r=>r.id===selectedId);
  if(!review || review.status!=="unconfirmed") throw new Error("Select an uncertain review first.");
  const extension=await extensionRequest("ping",{},2000);
  if(!compatibleExtension(extension)) throw new Error(reloadHint+" to version 1.0.7 or later, then refresh this dashboard.");
  const result=await extensionRequest("reconcile",{review});
  await api("/api/reviews/"+review.id+"/reconcile",{confirmation_token:review.confirmation_token,assertion:result.assertion});
  notice("Success: your saved review was verified. Nothing was posted again.");
}));
$("cancelButton").addEventListener("click",()=>action(async()=>{
  const review=reviews.find(r=>r.id===selectedId);
  await api("/api/reviews/"+selectedId+"/cancel",{});
  if(browser.transport==="extension" && review) {
    try {await extensionRequest("discard",{review},3000);} catch {}
  }
}));
$('copyExtensionPath').addEventListener('click',async()=>{
  try {await navigator.clipboard.writeText($('extensionPath').textContent);notice('Extension folder path copied.');}
  catch {notice('Select and copy the folder path shown in the setup instructions.',true);}
});
$("reviewForm").addEventListener("input",saveDraft);
$("text").addEventListener("input",clearPolicyWarnings);
$("text").addEventListener("blur",()=>{checkReviewPolicy().catch(()=>{});});
$("reviewForm").addEventListener("input",()=>{if(draftReviewId && !reviews.some(r=>r.id===draftReviewId && activeStates.has(r.status))) draftReviewId=null;});
function invalidateBusiness() {
  $("expected_name").value="";
  resolvedBusiness=null;
  if(!reviews.some(r=>activeStates.has(r.status))) {selectedId=null;renderPreview();}
}
$("target").addEventListener("input",invalidateBusiness);
$("searchCity")?.addEventListener("change",async()=>{
  invalidateBusiness();
  if(browser.transport!=="poster" || !extensionCapabilities.includes("city_geolocation")) return;
  if(requesting || monitoring || browser.busy || reviews.some(r=>activeStates.has(r.status))) {
    renderCityLocation(true);return;
  }
  const city=$("searchCity").value;
  changingCity=true;
  try {
    await action(async()=>{
      const result=await api("/api/browser/location",{city});
      browser.location=result.location;
      notice(result.location.enabled ? "Browser location selected. It applies to the poster browser, not your IP or Avast server." : "City location override cleared. IP routing is unchanged.");
    });
  } finally {changingCity=false;renderCityLocation(true);controls();}
});
$("clearHistoryButton").addEventListener("click",()=>deleteLocal());
$("historySearch").addEventListener("input",renderHistory);
$("historyFilter").addEventListener("change",renderHistory);
$("loadHistoryButton").addEventListener("click",()=>action(async()=>{
  const result=await api("/api/history?offset="+reviews.length);
  historyExpanded=true;
  const ids=new Set(reviews.map(r=>r.id));reviews.push(...result.reviews.filter(r=>!ids.has(r.id)));historyTotal=result.total;
  renderHistory();
}));
$("accountSelect").addEventListener("change",controls);
$("switchAccountButton").addEventListener("click",()=>action(async()=>{
  const email=$("accountSelect").value;
  if(browser.transport==="poster") {
    $("email").value=email;
    await api("/api/browser/select",{email});
    notice("Selected account is being checked in the poster browser. Nothing was posted.");
    return;
  }
  await extensionRequest("ping",{},2000);
  if(!extensionCapabilities.includes("account_selection")) {
    $("email").value=email;
    await api("/api/browser/login",{email});await extensionRequest("login",{email});
    notice("Google Maps mein selected account choose karein, phir Check connection dabayein. Direct selector ke liye signed extension 1.0.7 chahiye.");return;
  }
  await api("/api/browser/select",{email});$("email").value=email;
  const result=await extensionRequest("check",{email});
  const ping=await extensionRequest("ping",{},2000);
  await api("/api/browser/verified",{email:result.email,browser_kind:ping.browser_kind});
  notice("Selected Google account verified. No review was posted.");
}));
$("forgetAccountButton").addEventListener("click",async()=>{
  const email=$("accountSelect").value;if(!email) return;
  if(!await confirmLocal("Remove shortcut for "+email+"? Google stays signed in and existing reviews are unchanged.")) return;
  action(async()=>{const result=await api("/api/account-shortcuts/forget",{email});notice(result.message);});
});
async function checkSaved(review, automatic=false) {
  const token={confirmation_token:review.confirmation_token};
  const reserved=await api("/api/reviews/"+review.id+"/check-start",{...token,automatic});
  if(reserved.completed) {
    reviews=reviews.map(r=>r.id===review.id ? reserved.review : r);
    return;
  }
  let result;
  try {result=await extensionRequest("check_saved",{review:reserved.review},90000);}
  catch(error) {
    await api("/api/reviews/"+review.id+"/check-result",{...token,verification_token:reserved.verification_token,matched:false});
    throw error;
  }
  const checked=await api("/api/reviews/"+review.id+"/check-result",{...token,verification_token:reserved.verification_token,matched:true,assertion:result.assertion});
  reviews=reviews.map(r=>r.id===review.id ? checked.review : r);
}
$("checkSavedButton").addEventListener("click",()=>action(async()=>{
  const review=reviews.find(r=>r.id===selectedId);if(!review) return;
  await checkSaved(review);notice("Saved status verified. This does not prove public visibility; nothing was reposted.");
}));
function scheduleCheck(delay) {
  nextCheckAt=Date.now()+delay;try {localStorage.setItem(cadenceKey,String(nextCheckAt));} catch {}
}
async function autoCheckSaved() {
  if(document.hidden || !$("autoCheck").checked || !extensionCapabilities.includes("saved_checks") ||
     requesting || monitoring || polling || browser.busy || browser.status!=="connected" ||
     reviews.some(r=>activeStates.has(r.status)) || Date.now()<nextCheckAt || $("confirmDialog").open) return;
  monitoring=true;scheduleCheck(10*60*1000);controls();
  try {const {review}=await api("/api/check-candidate");if(review) await checkSaved(review,true);}
  catch(error) {scheduleCheck(30*60*1000);notice("Saved-review check needs attention: "+error.message,true);}
  finally {monitoring=false;await poll();controls();}
}
try {$("autoCheck").checked=localStorage.getItem(monitorKey)!=="off";} catch {}
$("autoCheck").addEventListener("change",()=>{try {localStorage.setItem(monitorKey,$("autoCheck").checked ? "on" : "off");} catch {}controls();});
document.addEventListener("visibilitychange",()=>{if(!document.hidden) poll();});
async function checkIdleNetwork() {
  if(document.hidden || browser.transport!=="extension" || browser.status!=="connected" ||
     !extensionInstalled || requesting || monitoring || polling || browser.busy || networkFlight) return;
  monitoring=true;controls();
  try {await checkNetwork();} catch(error) {notice(error.message,true);}
  finally {monitoring=false;await poll();controls();}
}
clearDraft();poll();setInterval(poll,2000);setInterval(autoCheckSaved,30000);setInterval(checkIdleNetwork,30000);
