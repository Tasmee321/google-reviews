"use strict";
(() => {
  const form=document.getElementById("unlockForm"), input=document.getElementById("unlockCode");
  const button=document.getElementById("unlockButton"), error=document.getElementById("unlockError");
  const status=document.getElementById("unlockStatus");
  let pending=false;
  // Remove the fragment before any unlock request. Never put the capability in
  // localStorage, a query string, diagnostics, a DOM attribute or an error message.
  const fragment=new URLSearchParams(location.hash.slice(1));
  let initialToken=fragment.get("unlock") || "";
  if(location.hash) history.replaceState(null,"",location.pathname);

  async function unlock(token) {
    if(pending) return;
    pending=true;button.disabled=true;input.disabled=true;
    error.hidden=true;error.textContent="";status.textContent="Unlocking private dashboard…";
    input.value="";
    try {
      const response=await fetch("/api/unlock",{method:"POST",credentials:"same-origin",cache:"no-store",
        headers:{"Content-Type":"application/json"},body:JSON.stringify({token})});
      token="";
      if(!response.ok) throw new Error("Private code accept nahi hua. Current app terminal ka private link dobara kholein.");
      const result=await response.json();
      if(result.ok!==true) throw new Error("Dashboard unlock nahi hua. Current private link use karein.");
      location.replace("/");
    } catch(failure) {
      error.textContent=failure instanceof TypeError ? "App se connection nahi hua. Server chala kar dobara try karein." : failure.message;
      error.hidden=false;status.textContent="Dashboard remains locked.";
    } finally {token="";pending=false;button.disabled=false;input.disabled=false;}
  }
  form.addEventListener("submit",event=>{event.preventDefault();unlock(input.value.trim());});
  if(initialToken) {const token=initialToken;initialToken="";unlock(token);}
})();
