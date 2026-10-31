"use strict";
(() => {
  if(window.top===window || location.pathname!=="/maps/api/js/ReviewsService.LoadWriteWidget") return;
  const visible=node=>Boolean(node && node.getClientRects().length && getComputedStyle(node).visibility!=="hidden");
  const all=(selector,root=document)=>Array.from(root.querySelectorAll(selector)).filter(visible);
  const one=nodes=>{
    if(nodes.length!==1) throw new Error("Google's review iframe is ambiguous or changed. Nothing was submitted.");
    return nodes[0];
  };
  const normalize=value=>value.normalize("NFKC").trim().replace(/\s+/g," ").toLowerCase();
  const selected=node=>node.getAttribute("aria-checked")==="true";
  let preparedId=null,submitted=false;
  async function waitFor(find,message,timeout=15000) {
    const deadline=Date.now()+timeout;
    while(Date.now()<deadline) {
      const result=find();if(result)return result;
      await new Promise(resolve=>setTimeout(resolve,150));
    }
    throw new Error(message);
  }
  function group() {
    // The real Google form also has Food/Service/Atmosphere stars.
    // Only the explicitly labelled overall rating is ever changed.
    return one(all('[role="radiogroup"][aria-label="Rating stars"]'));
  }
  function rating(stars) {
    const words=["","One","Two","Three","Four","Five"];
    const pattern=new RegExp("^(?:Rate\\s+)?(?:"+stars+"|"+words[stars]+")\\s+stars?$","i");
    return one(all('[role="radio"]',group()).filter(node=>
      node.getAttribute("data-rating")===String(stars) || pattern.test(node.getAttribute("aria-label") || "")));
  }
  function verify(review) {
    if(submitted) throw new Error("Submission already started. Check Google Maps before trying again.");
    one(all('h1,h2,[role="heading"]').filter(node=>normalize(node.textContent)===normalize(review.expected_name)));
    const text=one(all("textarea"));
    if(text.value!==review.text) throw new Error("The review text changed after preview. Nothing was submitted.");
    if(!selected(rating(review.stars)) || all('[role="radio"]',group()).filter(selected).length!==1)
      throw new Error("The selected rating could not be verified. Nothing was submitted.");
    return {ok:true,text:text.value,stars:review.stars};
  }
  async function prepare(review) {
    if(preparedId && preparedId!==review.id) throw new Error("This review iframe belongs to another draft.");
    await waitFor(()=>all("textarea").length && all('[role="radiogroup"][aria-label="Rating stars"]').length,
      "Google's review controls did not finish loading. Nothing was submitted.");
    one(all('h1,h2,[role="heading"]').filter(node=>normalize(node.textContent)===normalize(review.expected_name)));
    rating(review.stars).click();
    const text=one(all("textarea"));
    if(text.disabled || text.readOnly) throw new Error("Google's review editor is not ready.");
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set.call(text,review.text);
    text.dispatchEvent(new Event("input",{bubbles:true}));
    text.dispatchEvent(new Event("change",{bubbles:true}));
    await waitFor(()=>selected(rating(review.stars)),"Google's overall rating could not be verified.",3000);
    const result=verify(review);preparedId=review.id;
    return result;
  }
  function submit(review) {
    const result=verify(review);
    const post=one(all('button,[role="button"]').filter(node=>/^Post$/i.test((node.getAttribute("aria-label") || node.textContent).trim())));
    if(post.disabled || post.getAttribute("aria-disabled")==="true") throw new Error("Google's Post button is disabled.");
    submitted=true;
    post.click();
    // Acknowledge the click only. The parent Maps page verifies Google's
    // explicit submission result; neither a click nor a closed frame is success.
    return {...result,clicked:true};
  }
  chrome.runtime.onMessage.addListener((message,sender,reply)=>{
    if(message?.type!=="TASMEE_WIDGET" || sender.id!==chrome.runtime.id) return;
    Promise.resolve().then(async()=>{
      const review=message.review;
      if(message.url!==location.href || !review || !/^[a-f0-9]{24}$/.test(review.id) ||
         !Number.isInteger(review.stars) || review.stars<1 || review.stars>5 ||
         typeof review.text!=="string" || !review.text.trim() || review.text.length>4000 ||
         typeof review.expected_name!=="string" || !review.expected_name.trim()) throw new Error("Invalid review iframe request.");
      if(message.action==="prepare") return prepare(review);
      if(preparedId!==review.id) throw new Error("Prepare this review iframe before continuing.");
      if(message.action==="verify") return verify(review);
      if(message.action==="submit") return submit(review);
      throw new Error("Unsupported review iframe action.");
    }).then(reply,error=>reply({ok:false,message:error.message}));
    return true;
  });
  chrome.runtime.sendMessage({type:"TASMEE_WIDGET_READY"}).catch(()=>{});
})();
