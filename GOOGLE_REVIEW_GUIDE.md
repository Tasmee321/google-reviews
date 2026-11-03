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
  aur current/former employment, contractual/consultory, business/personal conflict-of-interest wala review submit na karein.
- Ek hi review repeat ya multiple accounts se rating influence na karein.
  Google policy fake engagement ke liye sensor data manipulation bhi prohibit karti hai.
- Reviews ka unusual volume/pattern aur account activity bhi Google evaluate kar
  sakta hai. App koi 'safe daily count', account rotation ya moderation-evasion recipe nahi deta.
- Sirf positive reviews mangwana, premises par pressure dalna ya prescribed text
  likhwana theek nahi. Har review independent asli reviewer ke apne alfaaz hon.

Sources: [Google content policy](https://support.google.com/contributionpolicy/answer/7400114?hl=en)
aur [high-quality review tips](https://support.google.com/maps/answer/10357321?hl=en).

## App mein istemal

1. `run.bat` se dedicated ordinary Firefox kholein. Signed 1.0.7 extension ke saath
   UK-IP check karein, phir apna Google account manually login/verify karein.
2. UK city select karke business search, ya exact Maps link, apni rating aur apna text enter karein.
3. Text field se bahar click karne par local reminders dikh sakte hain. Start
   par bhi ye check hota hai. Link/email, possible phone/long identifier aur
   local submitted/uncertain history mein repeated wording check hoti hai.
4. Warnings manually review karein. App text/rating change nahi karta, koi
   Google approval request nahi bhejta, aur draft kisi external checker ko upload nahi karta.
5. Sahi branch, account aur exact text/rating dekh kar policy confirmation tick
   karein, phir khud Post karein. Checkbox har naye review par reset hota hai.
6. Clear website/email inclusion final submission ko rokta hai; Cancel karke
   khud edit aur dobara prepare karein. Possible phone, repeated wording aur
   doosre local account ki same-business submission manual-review warnings hain.

Yeh limited advisory checks hain, exhaustive policy classifier nahi. Possible
phone number asal mein koi aur identifier bhi ho sakta hai. No warnings ka
matlab approved, authentic, safe-to-publish ya guaranteed live nahi. Deleted
history ka text preflight matching ke liye retain nahi hota; account names ya
matched review text warnings mein disclose nahi hote.

## Jo software verify nahi kar sakta

App real visit/service experience, sachai, hidden payment/incentive, relationship,
ownership/employment/competitor conflict ya asal account operator independently
verify nahi karti. Har language mein hate/harassment, defamation, private medical
ya financial information, off-topic text, restricted-goods promotion aur legal
eligibility ka exhaustive classifier bhi nahi. In points ko khud check karna hai.

UK IP Google review policy ki requirement nahi—yeh connection preference hai.
Recommended defaults mein city spoofing OFF hai aur city picker sirf search ke
liye hai. VPN ya coordinates authenticity/publication ka proof nahi bante.

## Review live na dikhe to

- Moderation mein kuch din lag sakte hain; foran duplicate/repost na karein.
- Apne Google Maps profile mein review status aur Google ki notifications dekhein.
- App ka Success/saved verification public visibility ka proof nahi. Google
  ke mutabiq removed content bhi profile mein Private/Not posted ki tarah reh sakta hai.
- Business/category par posting restrictions ya doosre non-policy reasons bhi
  ho sakte hain. App exact removal reason diagnose nahi karta.
- Removal ghalat lage aur appeal available ho to official appeal flow use karein.
  Eligible removal par aam tor par ek appeal, removal ke ek saal ke andar, available
  ho sakti hai; current Google notice/eligibility follow karein.
  Appeal submit karne ke baad Google review edit/delete karne se appeal cancel
  ho sakti hai. App koi appeal, edit, deletion ya repost khud nahi bhejta.

Sources: [missing/delayed reviews](https://support.google.com/business/answer/10313341?hl=en),
[removed/rejected content](https://support.google.com/contributionpolicy/answer/13780397?hl=en),
[appeal eligibility and process](https://support.google.com/contributionpolicy/answer/12648169?hl=en).

## Reliability aur permanent browser

Default ordinary Firefox apna existing `personal_data/firefox-profile/` aur signed
add-on preserve karta hai. Optional poster ka Chrome profile alag rehta hai. Permanent
profile ka matlab Google review ka permanent publication nahi. VPN/public IP
aur device location alag cheezein hain; inhein change karna publication ka proof nahi.

Extension mode mein browser preparation/verification/submission-response phase ka local deadline
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
$env:REVIEW_MODE = 'extension'
$env:REVIEW_BROWSER = 'firefox'
$env:REVIEW_OPEN_BROWSER = '0'
.\.venv\Scripts\python.exe app.py
```

Yeh commands project directory mein chalayein. Is update ke liye existing Mozilla
add-on ID `tasmee-personal-reviews@local.invalid` ke andar version 1.0.7 sign karwana
aur us signed XPI ko existing Firefox profile mein install karna zaroori hai.
Purana signed 1.0.6 UK-IP guard ke saath compatible nahi. Build unsigned files
banata hai; Mozilla upload/signing ya permanent installation khud nahi karta.
