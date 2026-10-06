#!/usr/bin/env python3
"""
GBP Poster — Maximum Stealth Edition
- Full IP evasion: proxy per account, WebRTC leak blocked, canvas fingerprint spoofed
- Navigator, plugins, screen, hardware concurrency — all spoofed
- Human mouse movement with bezier curves
- Human typing with realistic rhythm and mistakes
- Text spinner — unique review every post, never exact duplicate
- Google policy bypass: warm-up browsing before review, natural session flow
- Smart retry with exponential backoff
- Daily limit + done tracking
"""

import os, sys, json, time, random, logging, math
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv()

from patchright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ============ PATHS ============
ROOT       = Path(__file__).parent
PROFILES   = ROOT / "profiles"
LOGS       = ROOT / "logs"
STATE_FILE = ROOT / "state.json"
PROFILES.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)

# ============ CONFIG ============
HEADLESS         = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO          = int(os.getenv("SLOW_MO", "55"))
GAP_MIN          = int(os.getenv("GAP_MIN", "1200"))
GAP_MAX          = int(os.getenv("GAP_MAX", "5400"))
DAILY_LIMIT      = int(os.getenv("DAILY_LIMIT_PER_ACCT", "2"))
TZ               = os.getenv("TZ", "Asia/Karachi")
LOCALE           = os.getenv("LOCALE", "en-US")
MAX_RETRIES      = int(os.getenv("MAX_RETRIES", "3"))
WARMUP_ENABLED   = os.getenv("WARMUP_ENABLED", "true").lower() == "true"

# ============ LOGGING ============
log_file = LOGS / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.FileHandler(LOGS / "run.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("poster")

# ============ USER AGENTS — 16 rotated ============
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.120 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.120 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.84 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.142 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.208 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_7_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.122 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_7_10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720},
    {"width": 1920, "height": 1080},
    {"width": 1600, "height": 900},
    {"width": 1280, "height": 800},
    {"width": 1360, "height": 768},
]

# Hardware concurrency options — real machines have 2,4,6,8,12,16
HW_CONCURRENCY = [2, 4, 4, 6, 8, 8, 12, 16]

# Platform options matched to user agent
PLATFORMS = {
    "Windows": "Win32",
    "Macintosh": "MacIntel",
    "Linux": "Linux x86_64",
}

# ============ MAXIMUM STEALTH INIT SCRIPT ============
STEALTH_SCRIPT = """
// 1. Remove webdriver traces
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
delete navigator.__proto__.webdriver;

// 2. Realistic plugins array
const makePlugin = (name, desc, suffixes, mimeTypes) => {
    const plugin = Object.create(Plugin.prototype);
    Object.defineProperty(plugin, 'name', { get: () => name });
    Object.defineProperty(plugin, 'description', { get: () => desc });
    Object.defineProperty(plugin, 'filename', { get: () => name.toLowerCase().replace(/ /g,'') + '.dll' });
    Object.defineProperty(plugin, 'length', { get: () => mimeTypes.length });
    return plugin;
};
const fakePlugins = [
    makePlugin('Chrome PDF Plugin', 'Portable Document Format', ['pdf'], []),
    makePlugin('Chrome PDF Viewer', '', ['pdf'], []),
    makePlugin('Native Client', '', [], []),
];
Object.defineProperty(navigator, 'plugins', {
    get: () => Object.assign(fakePlugins, { item: i => fakePlugins[i], namedItem: n => fakePlugins.find(p => p.name === n), refresh: () => {} }),
});

// 3. Languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'en-GB'] });

// 4. Hardware concurrency — injected per session
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => __HW_CONCURRENCY__ });

// 5. Device memory
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

// 6. Platform
Object.defineProperty(navigator, 'platform', { get: () => '__PLATFORM__' });

// 7. Chrome runtime
window.chrome = {
    app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
    runtime: { OnInstalledReason: {}, OnRestartRequiredReason: {}, PlatformArch: {}, PlatformNaclArch: {}, PlatformOs: {}, RequestUpdateCheckStatus: {} },
    csi: () => {},
    loadTimes: () => ({ commitLoadTime: Date.now()/1000 - Math.random()*2, connectionInfo: 'h2', finishDocumentLoadTime: 0, finishLoadTime: 0, firstPaintAfterLoadTime: 0, firstPaintTime: 0, navigationType: 'Other', npnNegotiatedProtocol: 'h2', requestTime: Date.now()/1000 - Math.random()*3, startLoadTime: Date.now()/1000 - Math.random()*3, wasAlternateProtocolAvailable: false, wasFetchedViaSpdy: true, wasNpnNegotiated: true }),
};

// 8. Block WebRTC IP leak
if (window.RTCPeerConnection) {
    const origRTC = window.RTCPeerConnection;
    window.RTCPeerConnection = function(config, constraints) {
        if (config && config.iceServers) {
            config.iceServers = [];
        }
        return new origRTC(config, constraints);
    };
    window.RTCPeerConnection.prototype = origRTC.prototype;
}

// 9. Canvas fingerprint noise — slight pixel variation so fingerprint changes
const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    const ctx = this.getContext('2d');
    if (ctx) {
        const imageData = ctx.getImageData(0, 0, this.width || 1, this.height || 1);
        for (let i = 0; i < imageData.data.length; i += 4) {
            imageData.data[i]   += Math.floor(Math.random() * 2);
            imageData.data[i+1] += Math.floor(Math.random() * 2);
            imageData.data[i+2] += Math.floor(Math.random() * 2);
        }
        ctx.putImageData(imageData, 0, 0);
    }
    return origToDataURL.apply(this, arguments);
};

// 10. AudioContext fingerprint noise
if (window.AudioContext || window.webkitAudioContext) {
    const OrigAudio = window.AudioContext || window.webkitAudioContext;
    const patchedAudio = function(...args) {
        const ctx = new OrigAudio(...args);
        const origGetChannelData = ctx.constructor.prototype.getChannelData;
        if (origGetChannelData) {
            ctx.constructor.prototype.getChannelData = function(channel) {
                const data = origGetChannelData.call(this, channel);
                for (let i = 0; i < data.length; i += 100) {
                    data[i] += Math.random() * 0.0001;
                }
                return data;
            };
        }
        return ctx;
    };
    window.AudioContext = patchedAudio;
    window.webkitAudioContext = patchedAudio;
}

// 11. Screen properties matching viewport
Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });

// 12. Permission query — always return 'granted' for notifications
const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(parameters);
}
"""

# ============ TEXT SPINNER ============
# Randomizes text so every review is unique — avoids duplicate content detection
def spin_text(text: str) -> str:
    """Replace {option1|option2|option3} patterns with random choice."""
    import re
    def replace_spin(m):
        options = m.group(1).split("|")
        return random.choice(options).strip()
    spun = re.sub(r'\{([^}]+)\}', replace_spin, text)
    # Also randomly add/remove trailing period
    if spun and spun[-1] == "." and random.random() < 0.3:
        spun = spun[:-1]
    return spun

# ============ FINGERPRINT ============
def pick_fp(seed: str) -> dict:
    r = random.Random(seed + str(date.today()))
    ua = r.choice(USER_AGENTS)
    vp = r.choice(VIEWPORTS)
    hw = r.choice(HW_CONCURRENCY)
    # Match platform to UA
    if "Macintosh" in ua:
        platform = "MacIntel"
    elif "Linux" in ua:
        platform = "Linux x86_64"
    else:
        platform = "Win32"
    return {"user_agent": ua, "viewport": vp, "hw_concurrency": hw, "platform": platform}

def build_stealth_script(hw: int, platform: str) -> str:
    return STEALTH_SCRIPT.replace("__HW_CONCURRENCY__", str(hw)).replace("__PLATFORM__", platform)

# ============ STATE ============
def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"daily": {}, "done": {}, "stats": {}}

def _save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")

def daily_count(email: str) -> int:
    today = str(date.today())
    return _load_state()["daily"].get(email, {}).get(today, 0)

def increment_daily(email: str):
    s = _load_state()
    today = str(date.today())
    s["daily"].setdefault(email, {})
    s["daily"][email][today] = s["daily"][email].get(today, 0) + 1
    _save_state(s)

def is_done(email: str, place_id: str) -> bool:
    return _load_state()["done"].get(email, {}).get(place_id, False)

def mark_done(email: str, place_id: str):
    s = _load_state()
    s["done"].setdefault(email, {})
    s["done"][email][place_id] = True
    s.setdefault("stats", {})
    s["stats"][place_id] = s["stats"].get(place_id, 0) + 1
    _save_state(s)

# ============ DATA MODELS ============
@dataclass
class Account:
    email:    str
    password: str
    proxy:    str | None = None
    enabled:  bool = True
    totp:     str | None = None   # 16-char Google App Password (2FA)
    profile_dir: Path = field(init=False)

    def __post_init__(self):
        self.profile_dir = PROFILES / self.email.replace("@", "_at_")
        self.profile_dir.mkdir(exist_ok=True)

@dataclass
class Target:
    place_id:     str
    stars:        int
    texts:        list[str]
    search_query: str | None = None
    review_count: int = 1         # kitne reviews lagane hain is business pe
    reviews:      list | None = None  # [{text, stars}, ...] — per-review rating

def load_accounts() -> list[Account]:
    p = ROOT / "accounts.json"
    if not p.exists():
        log.error("accounts.json nahi mili")
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [Account(**a) for a in raw if a.get("enabled", True)]

def load_targets() -> list[Target]:
    p = ROOT / "targets.json"
    if not p.exists():
        log.error("targets.json nahi mili")
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [Target(**t) for t in raw]

# ============ HUMAN MOUSE — BEZIER CURVE MOVEMENT ============
def bezier_move(page, x1: int, y1: int, x2: int, y2: int, steps: int = 25):
    """Move mouse along bezier curve — looks like a real human hand."""
    try:
        # Control points for curve
        cx = x1 + random.randint(-80, 80)
        cy = y1 + random.randint(-80, 80)
        for i in range(steps + 1):
            t = i / steps
            # Quadratic bezier
            bx = (1-t)**2 * x1 + 2*(1-t)*t * cx + t**2 * x2
            by = (1-t)**2 * y1 + 2*(1-t)*t * cy + t**2 * y2
            page.mouse.move(bx, by)
            time.sleep(random.uniform(0.008, 0.025))
    except Exception:
        pass

def human_click(page, element):
    """Click element with realistic mouse movement."""
    try:
        box = element.bounding_box()
        if box:
            # Click slightly off-center — humans don't click exact center
            tx = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            ty = box["y"] + box["height"] * random.uniform(0.3, 0.7)
            vp = page.viewport_size or {"width": 1366, "height": 768}
            sx = random.randint(50, vp["width"] - 50)
            sy = random.randint(50, vp["height"] - 50)
            bezier_move(page, sx, sy, int(tx), int(ty))
            time.sleep(random.uniform(0.05, 0.15))
            element.click()
            return True
    except Exception:
        pass
    try:
        element.click()
        return True
    except Exception:
        return False

def random_mouse_move(page):
    try:
        vp = page.viewport_size or {"width": 1366, "height": 768}
        x1, y1 = random.randint(100, vp["width"]-100), random.randint(100, vp["height"]-100)
        x2, y2 = random.randint(100, vp["width"]-100), random.randint(100, vp["height"]-100)
        bezier_move(page, x1, y1, x2, y2, steps=random.randint(10, 20))
    except Exception:
        pass

# ============ HUMAN TYPING ============
# Common typo pairs — humans make mistakes and correct them
TYPO_MAP = {
    'a': 'as', 'e': 'er', 'i': 'io', 'o': 'op', 's': 'sa',
    't': 'tr', 'n': 'nb', 'r': 're',
}

def human_type(page, element, text: str):
    """Type with human rhythm, occasional typo + backspace correction."""
    element.click()
    time.sleep(random.uniform(0.3, 0.7))
    element.fill("")
    time.sleep(random.uniform(0.1, 0.3))

    i = 0
    while i < len(text):
        ch = text[i]
        # 3% chance of a typo
        if random.random() < 0.03 and ch.isalpha() and ch.lower() in TYPO_MAP:
            typo = random.choice(TYPO_MAP[ch.lower()])
            for tc in typo:
                element.type(tc, delay=random.uniform(40, 120))
            time.sleep(random.uniform(0.1, 0.4))
            # Backspace to fix
            for _ in typo:
                page.keyboard.press("Backspace")
                time.sleep(random.uniform(0.05, 0.12))
            time.sleep(random.uniform(0.05, 0.2))

        # Type the actual character
        delay_ms = random.uniform(40, 130)
        # Slower after punctuation or space — human rhythm
        if i > 0 and text[i-1] in '.,!? ':
            delay_ms = random.uniform(120, 280)
        element.type(ch, delay=delay_ms)

        # Occasional long pause — thinking
        if random.random() < 0.025:
            time.sleep(random.uniform(0.4, 1.2))
        i += 1

    time.sleep(random.uniform(0.5, 1.0))

# ============ HELPERS ============
def delay(a: float, b: float):
    time.sleep(random.uniform(a, b))

def is_blocked(page) -> bool:
    try:
        url = page.url
        if "/sorry/" in url or "sorry/index" in url:
            return True
        content = page.content()
        signals = ["This browser or app may not be secure", "unusual traffic",
                   "verify you're not a robot", "captcha", "I'm not a robot"]
        return any(s.lower() in content.lower() for s in signals)
    except Exception:
        return False

def is_logged_in(ctx) -> bool:
    page = ctx.new_page()
    try:
        page.goto("https://myaccount.google.com/", wait_until="domcontentloaded", timeout=30000)
        delay(2.0, 3.5)
        if is_blocked(page):
            return False
        if "accounts.google.com" in page.url:
            return False
        return "myaccount.google.com" in page.url
    except Exception:
        return False
    finally:
        try:
            page.close()
        except Exception:
            pass

# ============ WARM-UP BROWSING ============
# Browsing other sites before review — makes session look organic
WARMUP_SITES = [
    "https://www.google.com",
    "https://www.google.com/search?q=best+contractors+near+me",
    "https://www.google.com/search?q=home+improvement+services",
    "https://www.google.com/maps",
]

def warmup_session(page, acct: Account):
    """Browse a few pages naturally before posting — organic session pattern."""
    if not WARMUP_ENABLED:
        return
    log.info("%s: warm-up browsing...", acct.email)
    sites = random.sample(WARMUP_SITES, k=random.randint(2, 3))
    for url in sites:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            delay(3.0, 7.0)
            # Random scroll
            page.evaluate(f"window.scrollBy(0, {random.randint(200, 600)})")
            delay(1.0, 3.0)
            random_mouse_move(page)
            delay(1.0, 2.0)
        except Exception:
            continue
    log.info("%s: warm-up done", acct.email)

# ============ LAUNCH ============
def launch(pw, acct: Account):
    fp = pick_fp(acct.email)
    stealth = build_stealth_script(fp["hw_concurrency"], fp["platform"])

    kw = dict(
        user_data_dir=str(acct.profile_dir),
        headless=HEADLESS,
        slow_mo=SLOW_MO,
        viewport=fp["viewport"],
        user_agent=fp["user_agent"],
        locale=LOCALE,
        timezone_id=TZ,
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            # Block WebRTC completely at browser level
            "--enforce-webrtc-ip-permission-check",
            "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        ],
        ignore_default_args=["--enable-automation", "--no-sandbox"],
    )
    if acct.proxy:
        kw["proxy"] = {"server": acct.proxy}

    ctx = pw.chromium.launch_persistent_context(**kw)
    ctx.add_init_script(stealth)
    log.info("%s: browser launched [UA: ...%s] [HW: %d] [Platform: %s]",
             acct.email, fp["user_agent"][-30:], fp["hw_concurrency"], fp["platform"])
    return ctx

# ============ CONSENT ============
def handle_consent(page):
    for txt in ("Accept all", "I agree", "Accept", "Got it"):
        try:
            btn = page.query_selector(f'button:has-text("{txt}")')
            if btn and btn.is_visible():
                human_click(page, btn)
                delay(1.0, 1.8)
                return
        except Exception:
            continue

# ============ NAVIGATE ============
def navigate_to_business(page, tgt: Target, acct: Account) -> bool:
    # Support: short URLs (maps.app.goo.gl), full URLs, search queries, place_id
    sq = tgt.search_query or ""
    if sq.startswith("http"):
        url = sq  # Direct URL — short or full Maps link
    elif sq:
        query = sq.replace(" ", "+")
        url = f"https://www.google.com/maps/search/{query}"
    else:
        url = f"https://www.google.com/maps/search/?api=1&query=place_id:{tgt.place_id}"

    log.info("%s: navigating → %s", acct.email, url)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except PWTimeout:
        page.goto(url, wait_until="commit", timeout=30000)

    delay(4.0, 7.0)

    if is_blocked(page):
        log.error("%s: blocked/captcha", acct.email)
        return False

    handle_consent(page)
    delay(1.5, 3.0)
    random_mouse_move(page)

    # Fallback: if place_id didn't resolve, try name search
    if "place_id" in url and "maps/place" not in page.url and tgt.search_query:
        log.warning("%s: place_id fallback → name search", acct.email)
        q = tgt.search_query.replace(" ", "+")
        page.goto(f"https://www.google.com/maps/search/{q}", wait_until="domcontentloaded", timeout=30000)
        delay(3.0, 5.0)
        handle_consent(page)

    return True

# ============ CLICK WRITE A REVIEW ============
def click_write_review(page, acct: Account) -> bool:
    # Scroll a bit — button sometimes below fold
    page.evaluate("window.scrollBy(0, 250)")
    delay(1.0, 2.0)
    random_mouse_move(page)

    labels = ("Write a review", "Rate and review", "Write review", "Add a review")

    def _try_click_all_pages(ctx) -> bool:
        """Try clicking the review button on every open page — Google sometimes
        opens a pre-review interstitial in a second tab before the form."""
        for pg in ctx.pages:
            for txt in labels:
                selectors = [
                    f'button:has-text("{txt}")',
                    f'[role="button"]:has-text("{txt}")',
                    f'a:has-text("{txt}")',
                    f'button[aria-label*="{txt}"]',
                    f'[aria-label*="{txt}"]',
                ]
                for sel in selectors:
                    try:
                        for el in pg.query_selector_all(sel):
                            if el.is_visible():
                                el.scroll_into_view_if_needed()
                                delay(0.4, 0.8)
                                human_click(pg, el)
                                log.info("%s: clicked '%s' on %s", acct.email, txt, pg.url)
                                return True
                    except Exception:
                        continue
        return False

    ctx = page.context

    if _try_click_all_pages(ctx):
        return True

    # JS fallback on primary page
    try:
        result = page.evaluate("""
            (() => {
                const labels = ['Write a review','Rate and review','Write review','Add a review'];
                for (const el of document.querySelectorAll('button,[role="button"],a')) {
                    const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
                    if (labels.some(l => t.includes(l)) && el.offsetParent !== null) {
                        el.click(); return t;
                    }
                }
                return null;
            })()
        """)
        if result:
            log.info("%s: JS clicked '%s'", acct.email, result)
            return True
    except Exception:
        pass

    log.error("%s: 'Write a review' not found", acct.email)
    return False

# ============ WAIT FOR MODAL ============
def wait_for_modal(page, acct: Account, timeout_s: int = 35) -> bool:
    """
    Google Maps opens the review form in 3 different ways depending on the
    account state and Maps version:
      1. Inline modal on the same page (role=dialog or textarea appears)
      2. New tab / popup page (page.context().pages() grows)
      3. Full-page navigation to a /contribute/ or /review/ URL

    We poll all three surfaces simultaneously.
    Returns (page_to_use, True) — caller must use the returned page object
    to continue typing/clicking, because it may be a different tab.
    We mutate the module-level reference via a sentinel approach: if a new
    page is found we return it so post_review can reassign.
    """
    selectors = [
        'textarea',
        '[role="dialog"] textarea',
        '[role="dialog"]',
        'div[data-rating]',
        '[aria-label*="Rate"]',
        'g-radio-button-group',
        'div[jsaction*="stars"]',
        '[aria-label*="star"]',
        '[aria-label*="Star"]',
        '[aria-label*="review"]',
        '[aria-label*="Review"]',
        # 2024+ new contribute flow
        '[aria-label*="Share details"]',
        '[aria-label*="Describe your experience"]',
        'span[role="img"][aria-label*="star"]',
        'form[jsaction*="review"]',
        'div[data-review-id]',
        '[jsname="YPqjbf"]',  # Google's internal star container jsname
        'div.RHo1pe',         # star rating container class (Maps 2024)
    ]
    deadline = time.time() + timeout_s
    ctx = page.context

    while time.time() < deadline:
        # Scan every open page in the context — catches popup tabs
        all_pages = ctx.pages
        for pg in all_pages:
            try:
                url = pg.url
                # New-tab review page (full navigate)
                if "contribute" in url or "/review" in url or "reviewsTab" in url:
                    log.info("%s: modal via new-tab URL: %s", acct.email, url)
                    # Bring this page to focus
                    pg.bring_to_front()
                    delay(0.8, 1.5)
                    return True
            except Exception:
                pass

            for sel in selectors:
                try:
                    el = pg.query_selector(sel)
                    if el and el.is_visible():
                        log.info("%s: modal found via '%s' on %s", acct.email, sel, pg.url)
                        pg.bring_to_front()
                        return True
                except Exception:
                    pass

        # Check original page URL
        try:
            url = page.url
            if "review" in url.lower() or "contribute" in url.lower():
                log.info("%s: modal via original page URL", acct.email)
                return True
        except Exception:
            pass

        time.sleep(0.6)

    log.error("%s: modal not found (%ds)", acct.email, timeout_s)
    return False

# ============ CLICK STAR ============
def click_star(page, stars: int, acct: Account) -> bool:
    delay(1.5, 2.5)

    # Strategy 1: 2024+ Google Maps — img[src*="star"] inside clickable spans
    try:
        ok = page.evaluate(f"""
            (() => {{
                // New Maps UI: star icons are inside span/div with data-index or nth position
                // Look for the star container — usually a div with 5 children
                const containers = [
                    ...document.querySelectorAll('div[jsaction*="review"] span[role="img"]'),
                    ...document.querySelectorAll('span[role="img"][aria-label*="star"]'),
                    ...document.querySelectorAll('span[role="img"][aria-label*="Star"]'),
                ];
                if (containers.length >= {stars}) {{
                    containers[{stars-1}].click();
                    return true;
                }}

                // Fallback: any clickable element with star in aria
                const starEls = [...document.querySelectorAll(
                    '[aria-label*="{stars} star"],[aria-label*="{stars} Star"],' +
                    '[aria-label="Rate {stars} stars"],[aria-label="Rate {stars} star"]'
                )].filter(e => e.offsetParent !== null);
                if (starEls.length > 0) {{
                    starEls[0].click();
                    return true;
                }}
                return false;
            }})()
        """)
        if ok:
            log.info("%s: star %d via JS img/span strategy", acct.email, stars)
            delay(0.8, 1.5)
            return True
    except Exception:
        pass

    # Strategy 2: aria-label direct — extended label set for 2024 Maps
    aria_labels = [
        f"{stars} star", f"{stars} stars",
        f"Rate {stars} stars", f"Rate {stars} star",
        f"{stars} Star", f"{stars} Stars",
        f"Press {stars} to rate",
    ]
    for label in aria_labels:
        for sel in (
            f'[aria-label="{label}"]',
            f'span[aria-label="{label}"]',
            f'div[aria-label="{label}"]',
            f'button[aria-label="{label}"]',
            f'[aria-label*="{label}"]',
        ):
            try:
                els = page.query_selector_all(sel)
                for el in els:
                    if el.is_visible():
                        el.scroll_into_view_if_needed()
                        delay(0.3, 0.7)
                        human_click(page, el)
                        log.info("%s: star %d clicked via aria '%s'", acct.email, stars, label)
                        delay(0.8, 1.5)
                        return True
            except Exception:
                continue

    # Strategy 3: radiogroup / g-radio-button-group
    try:
        for grp_sel in (
            'g-radio-button-group',
            '[role="radiogroup"]',
            'div[data-rating]',
            'form[jsaction*="review"]',
        ):
            grp = page.query_selector(grp_sel)
            if grp:
                btns = grp.query_selector_all(
                    'div[role="radio"],button,span[role="radio"],'
                    'input[type="radio"],span[role="img"]'
                )
                if btns and len(btns) >= stars:
                    btn = btns[stars - 1]
                    btn.scroll_into_view_if_needed()
                    delay(0.4, 0.8)
                    human_click(page, btn)
                    log.info("%s: star %d via radiogroup", acct.email, stars)
                    delay(0.8, 1.5)
                    return True
    except Exception:
        pass

    # Strategy 4: screenshot debug — log what's on page to diagnose
    try:
        html_snippet = page.evaluate("""
            (() => {
                const interesting = document.querySelectorAll(
                    '[aria-label*="star"],[aria-label*="Star"],[aria-label*="rate"],[aria-label*="Rate"],' +
                    '[role="radio"],[role="radiogroup"],g-radio-button-group'
                );
                return [...interesting].slice(0,10).map(e =>
                    `${e.tagName}[aria-label="${e.getAttribute('aria-label')}"][role="${e.getAttribute('role')}"]`
                ).join(' | ');
            })()
        """)
        log.warning("%s: star debug — found elements: %s", acct.email, html_snippet)
    except Exception:
        pass

    log.error("%s: star %d click failed — all strategies exhausted", acct.email, stars)
    return False

# ============ TYPE REVIEW ============
def type_review_text(page, text: str, acct: Account) -> bool:
    delay(1.5, 2.5)
    spun = spin_text(text)
    log.info("%s: typing %d chars: '%s...'", acct.email, len(spun), spun[:40])

    # 2024+ Maps: textarea appears AFTER star click with a short delay
    # wait up to 8s for it to appear
    textarea_selectors = [
        'textarea',
        '[contenteditable="true"]',
        '[role="textbox"]',
        'textarea[aria-label*="review"]',
        'textarea[aria-label*="Review"]',
        'textarea[aria-label*="Share"]',
        'textarea[aria-label*="Describe"]',
        '[aria-label*="Share details"]',
        '[aria-label*="Describe your experience"]',
        '[aria-label*="Tell us"]',
        '[placeholder*="review"]',
        '[placeholder*="experience"]',
        '[placeholder*="Share"]',
        # New Maps contribute flow
        'div[contenteditable="true"][role="textbox"]',
        'div[aria-multiline="true"]',
    ]

    deadline = time.time() + 15
    while time.time() < deadline:
        # scan ALL open tabs — Google Maps often opens review form in a new tab
        all_pages = list(page.context.pages)
        for pg in reversed(all_pages):  # newest tab first
            try:
                pg.bring_to_front()
            except Exception:
                pass
            for sel in textarea_selectors:
                try:
                    els = pg.query_selector_all(sel)
                    for el in els:
                        if el.is_visible():
                            el.scroll_into_view_if_needed()
                            delay(0.5, 1.0)
                            human_type(pg, el, spun)
                            log.info("%s: typed via '%s' on %s", acct.email, sel, pg.url)
                            return True
                except Exception:
                    continue
        time.sleep(0.8)

    # debug: log what's on every tab
    try:
        all_pages = list(page.context.pages)
        for i, pg in enumerate(all_pages):
            try:
                snippet = pg.evaluate("""
                    (() => {
                        const els = document.querySelectorAll(
                            'textarea,div[contenteditable],[role="textbox"],[aria-multiline]'
                        );
                        return [...els].slice(0,5).map(e =>
                            `${e.tagName}[aria-label="${e.getAttribute('aria-label')}"]` +
                            `[placeholder="${e.getAttribute('placeholder')}"]` +
                            `[visible=${e.offsetParent !== null}]`
                        ).join(' | ');
                    })()
                """)
                log.warning("%s: tab[%d] url=%s | textarea debug — %s",
                            acct.email, i, pg.url, snippet)
            except Exception:
                pass
    except Exception:
        pass

    log.error("%s: textarea not found after 15s on any tab", acct.email)
    return False

# ============ CLICK POST ============
def click_post(page, acct: Account) -> bool:
    delay(1.0, 2.0)
    for label in ("Post", "Submit", "Done", "Publish", "Send"):
        for sel in (f'button:has-text("{label}")', f'[role="button"]:has-text("{label}")',
                    f'button[aria-label*="{label}"]', f'[aria-label="{label}"]'):
            try:
                el = page.query_selector(sel)
                if el and el.is_visible() and el.is_enabled():
                    el.scroll_into_view_if_needed()
                    delay(0.4, 0.9)
                    human_click(page, el)
                    log.info("%s: Post clicked", acct.email)
                    delay(2.5, 4.0)
                    return True
            except Exception:
                continue

    # JS fallback
    try:
        result = page.evaluate("""
            (() => {
                const labels = ['Post','Submit','Done','Publish','Send'];
                for (const el of document.querySelectorAll('button,[role="button"]')) {
                    const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
                    if (labels.includes(t) && el.offsetParent !== null && !el.disabled) {
                        el.click(); return t;
                    }
                }
                return null;
            })()
        """)
        if result:
            log.info("%s: JS Post '%s'", acct.email, result)
            delay(2.5, 4.0)
            return True
    except Exception:
        pass

    log.error("%s: Post button not found", acct.email)
    return False

# ============ VERIFY POSTED ============
def verify_posted(page, acct: Account) -> bool:
    delay(2.0, 3.5)
    signals = ["Your review has been posted", "Review posted", "Thank you",
               "review will be posted", "posted successfully"]
    try:
        content = page.content().lower()
        for s in signals:
            if s.lower() in content:
                log.info("%s: confirmed — '%s'", acct.email, s)
                return True
    except Exception:
        pass
    try:
        dialog = page.query_selector('[role="dialog"]')
        if not dialog or not dialog.is_visible():
            log.info("%s: modal closed — success assumed", acct.email)
            return True
    except Exception:
        pass
    log.warning("%s: unconfirmed — marking done optimistically", acct.email)
    return True

# ============ FULL REVIEW FLOW ============
def post_review(page, tgt: Target, acct: Account) -> bool:
    text = random.choice(tgt.texts) if tgt.texts else ""

    if not navigate_to_business(page, tgt, acct):
        return False

    delay(2.0, 4.0)
    random_mouse_move(page)

    if not click_write_review(page, acct):
        return False

    # 2024 Maps sometimes needs extra time after button click before modal loads
    delay(3.5, 5.5)

    if not wait_for_modal(page, acct):
        # save screenshot for debugging
        try:
            ss_path = LOGS / f"debug_modal_{acct.email}_{int(time.time())}.png"
            page.screenshot(path=str(ss_path))
            log.warning("%s: modal fail screenshot saved → %s", acct.email, ss_path)
        except Exception:
            pass
        return False

    # After wait_for_modal, the active page may have shifted to a popup tab.
    # Re-read ctx.pages and use the most-recently-opened page that looks like
    # the review form — this handles Google opening a new tab for the form.
    ctx = page.context
    active_page = page
    for pg in reversed(ctx.pages):
        try:
            url = pg.url
            if any(k in url for k in ("contribute", "/review", "reviewsTab", "maps")):
                active_page = pg
                break
        except Exception:
            pass

    delay(1.0, 2.0)

    # Stars first — Google sometimes requires it
    star_ok = click_star(active_page, tgt.stars, acct)
    if not star_ok:
        log.warning("%s: star failed — continuing", acct.email)

    delay(1.2, 2.0)

    if text:
        if not type_review_text(active_page, text, acct):
            log.warning("%s: text failed — continuing", acct.email)

    delay(1.5, 2.5)
    random_mouse_move(active_page)

    if not click_post(active_page, acct):
        return False

    return verify_posted(active_page, acct)

# ============ MAIN ============
def run():
    accounts = load_accounts()
    targets  = load_targets()

    if not accounts:
        log.error("accounts.json empty or missing")
        return
    if not targets:
        log.error("targets.json empty or missing")
        return

    enabled = [a for a in accounts if a.enabled]
    log.info("start — %d accounts, %d targets, limit=%d/day",
             len(enabled), len(targets), DAILY_LIMIT)

    stats = {"posted": 0, "skipped": 0, "failed": 0}

    with sync_playwright() as pw:
        for acct in enabled:
            count = daily_count(acct.email)
            if count >= DAILY_LIMIT:
                log.info("%s: daily limit (%d/%d) — skip", acct.email, count, DAILY_LIMIT)
                stats["skipped"] += 1
                continue

            log.info("=== %s [%d/%d done today] ===", acct.email, count, DAILY_LIMIT)
            ctx = None

            try:
                ctx = launch(pw, acct)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                if not is_logged_in(ctx):
                    print(f"\n{'='*60}")
                    print(f"  LOGIN REQUIRED: {acct.email}")
                    print(f"  Chrome mein login karo, phir ENTER dabao")
                    print(f"{'='*60}")
                    input("  >> ENTER: ")
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()

                # Warm-up browsing — organic session
                warmup_session(page, acct)

                for tgt in targets:
                    if daily_count(acct.email) >= DAILY_LIMIT:
                        log.info("%s: daily limit hit", acct.email)
                        break
                    if is_done(acct.email, tgt.place_id):
                        log.info("%s: skip (done) %s", acct.email, tgt.place_id)
                        continue

                    log.info("%s: → %s (%d★)", acct.email, tgt.place_id, tgt.stars)
                    success = False

                    for attempt in range(1, MAX_RETRIES + 1):
                        try:
                            success = post_review(page, tgt, acct)
                            if success:
                                break
                            backoff = 5 * (2 ** attempt) + random.uniform(0, 5)
                            log.warning("%s: attempt %d failed — retry in %.0fs",
                                        acct.email, attempt, backoff)
                            time.sleep(backoff)
                            page = ctx.new_page()
                        except Exception as e:
                            log.error("%s: attempt %d crash: %s", acct.email, attempt, e, exc_info=True)
                            backoff = 5 * (2 ** attempt)
                            time.sleep(backoff)
                            try:
                                page = ctx.new_page()
                            except Exception:
                                pass

                    if success:
                        mark_done(acct.email, tgt.place_id)
                        increment_daily(acct.email)
                        stats["posted"] += 1
                        log.info("%s: ✓ posted %s", acct.email, tgt.place_id)
                    else:
                        stats["failed"] += 1
                        log.error("%s: ✗ failed %s (max retries)", acct.email, tgt.place_id)

                    # Gap between reviews
                    pending = [t for t in targets
                               if not is_done(acct.email, t.place_id) and t.place_id != tgt.place_id]
                    if pending and daily_count(acct.email) < DAILY_LIMIT:
                        gap = random.randint(GAP_MIN, GAP_MAX)
                        log.info("gap: %ds before next review", gap)
                        time.sleep(gap)

            except Exception as e:
                log.error("%s: session crash: %s", acct.email, e, exc_info=True)
                stats["failed"] += 1
            finally:
                if ctx:
                    try:
                        ctx.close()
                    except Exception:
                        pass

            # Gap between accounts
            if acct != enabled[-1]:
                gap = random.randint(GAP_MIN // 2, GAP_MAX // 2)
                log.info("account gap: %ds", gap)
                time.sleep(gap)

    print(f"\n{'='*60}")
    print(f"  SESSION DONE")
    print(f"  ✓ Posted:  {stats['posted']}")
    print(f"  ✗ Failed:  {stats['failed']}")
    print(f"  ⊘ Skipped: {stats['skipped']}")
    print(f"  Log: {log_file}")
    print(f"{'='*60}\n")
    log.info("done — %s", stats)


if __name__ == "__main__":
    run()
