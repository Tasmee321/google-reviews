"use strict";
(() => {
  if(window.top!==window) return;
  const visible=element=>Boolean(element && element.getClientRects().length && getComputedStyle(element).visibility!=="hidden");
  const all=(selector,root=document)=>Array.from(root.querySelectorAll(selector)).filter(visible);
  const one=elements=>{
    if(elements.length!==1) throw new Error("Google's page is ambiguous or has changed. Continue manually in Google Maps.");
    return elements[0];
  };
  const normalize=value=>value.normalize("NFKC").trim().replace(/\s+/g," ").toLowerCase();
  const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  async function waitFor(find,message,timeout=20000) {
    const deadline=Date.now()+timeout;
    while(Date.now()<deadline) {const value=find();if(value)return value;await delay(150);}
    throw new Error(message);
  }
  function accountEmails() {
    const labels=all('[aria-label*="Google Account"], [aria-label*="Google account"]');
    return [...new Set(labels.flatMap(element=>(element.getAttribute("aria-label") || "").match(/[\w.+%-]+@[\w.-]+\.[a-z]{2,}/gi)||[]).map(email=>email.toLowerCase()))];
  }
  function account() {
    const emails=accountEmails();
    if(emails.length>1) throw new Error("More than one Google account was detected. Check the Maps account before continuing.");
    if(emails.length!==1) throw new Error("Google account email is not readable on this Maps page. Nothing was submitted.");
    return emails[0];
  }
  async function waitAccount() {
    // Maps renders the business heading before the signed-in account header.
    // Wait for the email itself, not just an empty/loading account button.
    return waitFor(()=>{
      const emails=accountEmails();
      if(emails.length>1) throw new Error("More than one Google account was detected. Check the Maps account before continuing.");
      return emails.length===1 ? emails[0] : null;
    },"Google account email did not finish loading. Check sign-in on the Maps tab, then prepare again. Nothing was submitted.",15000);
  }
  function key(url,name) {
    const parsed=new URL(url);
    for(const field of ["query_place_id","place_id","cid","ftid"]) if(parsed.searchParams.has(field)) return field+":"+parsed.searchParams.get(field);
    const match=parsed.pathname.match(/!1s([^!/?]+)/);
    return match ? "place:"+match[1] : normalize(name)+"|"+parsed.pathname.replace(/\/$/,"");
  }
  function business(review) {
    const selectedHeadings=all('h1.DUwDvf');
    const headings=selectedHeadings.length ? selectedHeadings : all('h1,[role="heading"][aria-level="1"]').filter(h=>
      h.textContent.trim() && normalize(h.textContent)!=="results");
    const name=one(review.expected_name ? headings.filter(h=>normalize(h.textContent)===normalize(review.expected_name)) : headings).textContent.trim();
    if(!name || name.length>200) throw new Error("The selected business name is not readable. Open a specific business link.");
    const email=account();
    if(email!==review.account_email) throw new Error("Google is signed into a different account. Nothing was submitted.");
    if(review.business_key && key(location.href,name)!==review.business_key) throw new Error("The business changed after preview. Nothing was submitted.");
    // Only the selected business's explicit address, not the search/camera location.
    const addresses=all('[data-item-id="address"]');
    let address="";
    if(addresses.length===1) {
      const node=addresses[0],label=node.getAttribute("aria-label") || "";
      if(/^Address:\s*/i.test(label)) address=label.replace(/^Address:\s*/i,"").trim();
      else address=node.querySelector('.Io6YTe')?.textContent.trim() || "";
    }
    const coordinatePairs=[...new Set([...decodeURIComponent(location.pathname).matchAll(/!3d([+-]?(?:\d+(?:\.\d*)?|\.\d+))!4d([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?=!|\/|$)/g)]
      .map(match=>Number(match[1])+","+Number(match[2])))];
    let latitude=null,longitude=null;
    if(coordinatePairs.length===1) {
      const pair=coordinatePairs[0].split(',').map(Number);
      if(Math.abs(pair[0])<=90 && Math.abs(pair[1])<=180) [latitude,longitude]=pair;
    }
    return {name,email,url:location.href,address,latitude,longitude};
  }
  async function resolve(request) {
    await waitFor(()=>all('h1.DUwDvf').length || all('h1,[role="heading"][aria-level="1"]').some(h=>h.textContent.trim() && normalize(h.textContent)!=="results"),
      "Open a specific Google Maps business link, not just a map or an ambiguous search.");
    await waitAccount();
    const info=business({account_email:request.account_email,expected_name:""});
    const targetKey=key(request.navigation_url,info.name);
    const resolvedKey=key(info.url,info.name);
    if(/^(place:|query_place_id:|place_id:|cid:|ftid:)/.test(targetKey) && targetKey.split(':')[0]===resolvedKey.split(':')[0] && targetKey!==resolvedKey)
      throw new Error("Google opened a different business from the supplied link. Check the branch.");
    return {ok:true,assertion:info};
  }
  function savedReview(review) {
    const headings=all('h2,[role="heading"]').filter(node=>node.textContent.trim()==="Your review");
    if(headings.length!==1) return null;
    // Google's own-review heading is immediately followed by its review card.
    // Never match an arbitrary public review with the same words/rating.
    const card=headings[0].parentElement?.nextElementSibling;
    if(!visible(card) || !card.matches('[data-review-id]') || !card.getAttribute("data-review-id")) return null;
    const text=all('.wiI7pd',card),stars=all('[role="img"][aria-label]',card).filter(node=>/^[1-5] stars?$/.test(node.getAttribute("aria-label")));
    if(text.length!==1 || stars.length!==1 || text[0].textContent.replace(/\r\n/g,"\n")!==review.text.replace(/\r\n/g,"\n") ||
       Number(stars[0].getAttribute("aria-label").match(/^[1-5]/)[0])!==review.stars) return null;
    let sibling=card.nextElementSibling,editable=false;
    for(let i=0;sibling && i<3;i++,sibling=sibling.nextElementSibling) {
      if(all('h1,h2,[role="heading"],[data-review-id]',sibling).length) break;
      if(all('button,[role="button"]',sibling).some(node=>(node.getAttribute("aria-label")||node.textContent).trim()==="Edit your review")) editable=true;
    }
    if(!editable) return null;
    return {...business(review),text:text[0].textContent.replace(/\r\n/g,"\n"),stars:review.stars,saved_review_id:card.getAttribute("data-review-id")};
  }
  async function reconcile(review) {
    await waitAccount();
    business(review);
    const assertion=await waitFor(()=>savedReview(review),
      "A saved review matching this account, business, exact text and rating was not found. Nothing was posted again.",10000);
    return {ok:true,assertion};
  }
  function form() {
    return one(all('[role="dialog"]').filter(dialog=>all("textarea",dialog).length===1));
  }
  function widgetFrame() {
    const frames=all('iframe').filter(frame=>{
      try {
        const url=new URL(frame.src);
        return url.origin===location.origin && url.pathname==="/maps/api/js/ReviewsService.LoadWriteWidget";
      } catch {return false;}
    });
    return frames.length ? one(frames) : null;
  }
  async function widget(action,review) {
    const frame=widgetFrame();
    if(!frame) throw new Error("The Google review iframe closed. Prepare a new preview.");
    const response=await chrome.runtime.sendMessage({type:"TASMEE_WIDGET_REQUEST",action,review,url:frame.src});
    if(!response?.ok) throw new Error(response?.message || "The Google review iframe did not respond.");
    return response;
  }
  function rating(root,stars) {
    const pattern=new RegExp("^(?:Rate\\s+)?"+stars+"\\s+stars?$","i");
    return one(all('[role="radio"],[data-rating],[aria-label*="star"],[aria-label*="Star"]',root).filter(item=>
      pattern.test((item.getAttribute("aria-label")||"").trim()) || item.getAttribute("data-rating")===String(stars)));
  }
  const selected=item=>["aria-checked","aria-pressed","aria-selected"].some(attribute=>item.getAttribute(attribute)==="true");
  async function verify(review) {
    await waitAccount();
    const info=business(review);
    if(widgetFrame()) {
      const response=await widget("verify",review);
      return {...business(review),text:response.text,stars:response.stars};
    }
    const root=form(),textarea=one(all("textarea",root));
    if(textarea.value!==review.text) throw new Error("The review text changed after preview. Nothing was submitted.");
    if(!selected(rating(root,review.stars))) throw new Error("The selected rating could not be verified. Nothing was submitted.");
    return {...info,text:textarea.value,stars:review.stars};
  }
  function button(root,pattern) {
    return one(all('button,[role="button"]',root).filter(item=>pattern.test((item.getAttribute("aria-label")||item.textContent).trim())));
  }
  async function prepare(review) {
    await waitFor(()=>all('h1,[role="heading"][aria-level="1"]').length,"The business did not load. Check the Maps tab.");
    const headings=all('h1,[role="heading"][aria-level="1"]');
    if(!headings.some(h=>normalize(h.textContent)===normalize(review.expected_name))) throw new Error("The business name does not match. Check the exact name and location.");
    await waitAccount();
    business(review);
    button(document,/^(Write a review|Rate and review)$/i).click();
    const root=await waitFor(()=>widgetFrame() || all('[role="dialog"]').find(dialog=>all("textarea",dialog).length===1),"The review dialog was not found. Continue manually in Google Maps.");
    if(root.tagName==="IFRAME") {
      const response=await widget("prepare",review);
      return {ok:true,assertion:{...business(review),text:response.text,stars:response.stars}};
    }
    rating(root,review.stars).click();
    const textarea=one(all("textarea",root));
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set.call(textarea,review.text);
    textarea.dispatchEvent(new Event("input",{bubbles:true}));
    textarea.dispatchEvent(new Event("change",{bubbles:true}));
    await waitFor(()=>selected(rating(root,review.stars)),"Google's rating could not be verified. Nothing was submitted.",3000);
    return {ok:true,assertion:await verify(review)};
  }
  let submitted=false;
  async function submit(review) {
    if(submitted) throw new Error("This page already started a submission. Check Google Maps before posting again.");
    await verify(review);
    if(widgetFrame()) {
      submitted=true;
      try {await widget("submit",review);}
      catch(error) {
        if(!/message.*closed|message channel closed|receiving end does not exist/i.test(error.message)) throw error;
        // A removed iframe can close the reply channel after Post. Only an
        // explicit success in the parent page is accepted; never click again.
      }
    } else {
      const post=button(form(),/^Post$/);
      if(post.disabled || post.getAttribute("aria-disabled")==="true") throw new Error("Google's Post button is disabled.");
      submitted=true;
      post.click();
    }
    const pattern=/^(Your review (?:has been|was) posted[.!]?|Review posted[.!]?|Thanks for your review[.!]?|Thank you for sharing[.!]?)$/i;
    let confirmed=false;
    try {await waitFor(()=>{
      business(review);
      return all('[role="status"],[role="alert"],p,span,div').some(node=>pattern.test(node.textContent.trim())) || savedReview(review);
    },"No confirmation",15000);confirmed=true;} catch {}
    return {ok:true,confirmed};
  }
  chrome.runtime.onMessage.addListener((message,sender,reply)=>{
    if(message?.type!=="TASMEE_GOOGLE" || sender.id!==chrome.runtime.id) return;
    Promise.resolve().then(async()=>{
      if(message.action==="account") {
        const email=await waitAccount(),authuser=new URL(location.href).searchParams.get("authuser") || "0";
        return {ok:true,email,account_index:/^\d+$/.test(authuser) ? authuser : null};
      }
      if(message.action==="resolve") return resolve(message.review);
      if(message.action==="reconcile") return reconcile(message.review);
      if(message.action==="prepare") return prepare(message.review);
      if(message.action==="verify") return {ok:true,assertion:await verify(message.review)};
      if(message.action==="submit") return submit(message.review);
      throw new Error("Unsupported action.");
    }).then(reply,error=>reply({ok:false,message:error.message}));
    return true;
  });
})();
