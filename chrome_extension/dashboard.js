"use strict";
let publishGesture = 0;
document.addEventListener("click", event => {
  if (event.isTrusted && event.target.closest?.("#publishButton")) publishGesture = Date.now();
}, true);
window.addEventListener("message", async event => {
  if (event.source !== window || event.origin !== location.origin || event.data?.type !== "TASMEE_REQUEST") return;
  if (location.pathname !== "/" || !document.querySelector('meta[name="csrf-token"]')) return;
  const {id, action, data} = event.data;
  if (typeof id !== "string" || !["ping","login","check","resolve","prepare","verify","submit","discard","reconcile","check_saved"].includes(action)) return;
  let response;
  try {
    if (action === "submit") {
      if (Date.now() - publishGesture > 60000) throw new Error("Click Post this review to authorize submission.");
      publishGesture = 0;
    }
    response = await chrome.runtime.sendMessage({type:"TASMEE_COMMAND", action, data});
  } catch (error) { response = {ok:false, message:error.message}; }
  window.postMessage({type:"TASMEE_RESPONSE", id, response}, location.origin);
});
