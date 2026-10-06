# GBP Poster — Windows Setup Guide

## Step 1: Python Install karo
1. https://python.org/downloads pe jao
2. Latest Python 3.11+ download karo
3. Install karte waqt **"Add Python to PATH"** checkbox zaroor tick karo
4. Verify: CMD kholo → type karo: `python --version`

## Step 2: Project Folder Setup
```
C:\gbp-poster\
    poster.py
    accounts.json
    targets.json
    .env
    logs\        ← auto banta hai
    profiles\    ← auto banta hai
```

## Step 3: Dependencies Install
CMD mein ye commands ek ek karke chalao:
```bash
cd C:\gbp-poster
python -m pip install --upgrade pip
pip install patchright python-dotenv
python -m patchright install chromium
```

## Step 4: accounts.json Setup
```json
[
  {
    "email": "youremail@gmail.com",
    "password": "yourpassword",
    "proxy": null,
    "enabled": true
  },
  {
    "email": "secondemail@gmail.com",
    "password": "yourpassword2",
    "proxy": null,
    "enabled": true
  }
]
```

## Step 5: targets.json Setup
```json
[
  {
    "place_id": "ChIJ...",
    "stars": 5,
    "search_query": "Business Name City",
    "texts": [
      "Great service! Very professional and delivered on time.",
      "Excellent work, highly recommend to everyone.",
      "Amazing team, very satisfied with the results."
    ]
  }
]
```

**Place ID kaise dhundein:**
1. Google Maps pe business open karo
2. URL mein `1s0x...` wala part copy karo — wahi place_id hai
3. Ya simply search_query mein business ka naam + city likho

## Step 6: Run karo
```bash
cd C:\gbp-poster
python poster.py
```

## Proxy Setup (Optional but Recommended)
Har account ke liye alag proxy lagao:
```json
{
  "email": "email@gmail.com",
  "password": "pass",
  "proxy": "http://user:pass@ip:port",
  "enabled": true
}
```

Free proxies mat use karo — ye kaam nahi karte.
Recommended: Brightdata, Smartproxy, IPRoyal

## Common Errors & Fix

| Error | Fix |
|-------|-----|
| `ModuleNotFoundError: patchright` | `pip install patchright` |
| `Executable doesn't exist` | `python -m patchright install chromium` |
| `Login Required` baar baar | Profile folder delete karo, dobara login karo |
| Star click fail | targets.json mein search_query daalo (place_id ki jagah) |
| Modal nahi khulta | SLOW_MO=100 karo .env mein |
| Blocked/Captcha | Proxy lagao ya alag IP use karo |

## Scheduler — Auto Daily Run (Windows Task Scheduler)
1. Task Scheduler kholo (Win+R → taskschd.msc)
2. "Create Basic Task" click karo
3. Trigger: Daily → apna time set karo
4. Action: Start a Program
   - Program: `python`
   - Arguments: `C:\gbp-poster\poster.py`
   - Start in: `C:\gbp-poster`
5. Finish

## Tips
- Ek account se din mein 2 se zyada review mat karo (DAILY_LIMIT_PER_ACCT=2)
- Alag alag businesses pe review karo, ek hi pe baar baar nahi
- Reviews ke beech GAP_MIN=1200 (20 min) minimum rakhna
- HEADLESS=false rakhna jab tak sab test nahi ho jata
- Baad mein HEADLESS=true karo server/background run ke liye
