# Google reviews: behtar quality, clear status

Official Google pages 3 November 2026 ko check kiye gaye. Yeh guide publication
percentage, moderation approval ya permanent visibility ki guarantee nahi hai.

## Review likhte waqt

- Sirf apna firsthand, asli tajurba aur sahi business/branch review karein.
- Specific aur relevant details likhein: kis service/product ka tajurba hua,
  kya acha/bura tha, aur doosre visitors ko kya maloom hona chahiye. Facts invent na karein.
- Rating sachchi rakhein. Respectful negative review bhi allowed hai; artificial
  praise ya zabardasti positive/negative balance ki zarurat nahi.
- Spelling aur grammar check karein; excessive capitals/punctuation se parhez
  karein. Google ki guidance mein paragraph suggested hai, koi guaranteed word-count nahi.
- Reviews ke andar website/social links, phone numbers aur email addresses na
  daalein. Kisi ki private, medical, financial ya identification details expose na karein.
- Paid/incentivized review, payment/discount/free service ke badlay review,
  aur employment/business/personal conflict-of-interest wala review submit na karein.
- Ek hi review repeat ya multiple accounts se rating influence na karein.
  Google policy fake engagement ke liye sensor data manipulation bhi prohibit karti hai.

Sources: [Google content policy](https://support.google.com/contributionpolicy/answer/7400114?hl=en)
aur [high-quality review tips](https://support.google.com/maps/answer/10357321?hl=en).

## App mein istemal

1. `run.bat` se dashboard kholein. Default poster browser mein Google account verify karein.
2. UK city select karke business search, ya exact Maps link, apni rating aur apna text enter karein.
3. Text field se bahar click karne par local reminders dikh sakte hain. Start
   par bhi ye check hota hai. Link/email, possible phone/long identifier aur
   local submitted/uncertain history mein repeated wording check hoti hai.
4. Warnings manually review karein. App text/rating change nahi karta, koi
   Google approval request nahi bhejta, aur draft kisi external checker ko upload nahi karta.
5. Sahi branch, account aur exact text/rating dekh kar khud Post karein.

Yeh limited advisory checks hain, exhaustive policy classifier nahi. Possible
phone number asal mein koi aur identifier bhi ho sakta hai. No warnings ka
matlab approved, authentic, safe-to-publish ya guaranteed live nahi. Deleted
history ka text preflight matching ke liye retain nahi hota; account names ya
matched review text warnings mein disclose nahi hote.

## Review live na dikhe to

- Moderation mein kuch din lag sakte hain; foran duplicate/repost na karein.
- Apne Google Maps profile mein review status aur Google ki notifications dekhein.
- App ka Success/saved verification public visibility ka proof nahi. Google
  ke mutabiq removed content bhi profile mein Private/Not posted ki tarah reh sakta hai.
- Business/category par posting restrictions ya doosre non-policy reasons bhi
  ho sakte hain. App exact removal reason diagnose nahi karta.
- Removal ghalat lage aur appeal available ho to official appeal flow use karein.
  Appeal submit karne ke baad Google review edit/delete karne se appeal cancel
  ho sakti hai. App koi appeal, edit, deletion ya repost khud nahi bhejta.

Sources: [missing/delayed reviews](https://support.google.com/business/answer/10313341?hl=en),
[removed/rejected content](https://support.google.com/contributionpolicy/answer/13780397?hl=en),
[appeal eligibility and process](https://support.google.com/contributionpolicy/answer/12648169?hl=en).

## Reliability aur permanent browser

Poster apna persistent Chrome profile use karta hai. Optional extension mode ka
Firefox profile aur installed signed add-on bhi preserve hote hain. Permanent
profile ka matlab Google review ka permanent publication nahi. VPN/public IP
aur device location alag cheezein hain; inhein change karna publication ka proof nahi.

Optional extension mode mein browser preparation/verification/submission-response phase ka local deadline
180 seconds hai; yeh app reliability limit hai, Google posting cadence nahi.
Timeout aglay status/API check par recover hota hai. Submission authorize ho
chuki ho to status Unconfirmed rehta hai aur duplicate protection preserve hoti
hai. Submission se pehle timeout Interrupted hota hai. Old Maps tab close karke
status check karein; app automatically submit/retry nahi karta. Poster mode mein
navigation aur element timeouts `config.json` mein set hain. Ready preview
sirf waqt guzarne se expire nahi hota.

Update apply karne ke liye active action complete/cancel karein, server terminal
mein Ctrl+C karein, launcher dobara run karein aur existing dashboard
refresh karein. Sirf server start karna ho to:

```powershell
$env:REVIEW_MODE = 'poster'
$env:REVIEW_OPEN_BROWSER = '0'
.\.venv\Scripts\python.exe app.py
```

Yeh commands project directory mein chalayein. Is dashboard/backend update ke
liye existing signed 1.0.6 extension replace/re-sign karne ki zarurat nahi.
