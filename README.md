# Blogger AI Agent (Autonomous Blogging Agent)

Ye project ek **khud-chalne wala blogging agent** hai. Aap sirf din ke time slots
config file me bata do, baaki kaam agent apne aap karta hai:

1. **Internet par search** karke ek naya aur relevant topic dhoondhta hai
2. Us topic par **research** karke original blog article likhta hai
3. Ek **alag step** me article ko edit/proofread karta hai
4. Blogger par post karta hai - **draft** ya **live publish** (aapki config ke hisaab se)

Ye do jagah chalta hai:

- **Local (VS Code)** - test karne ke liye
- **GitHub Actions** - bina computer on rakhe, har 15 minute apne aap

---

## 1. Project me kya kya hai

```
blogger-ai-agent/
  scripts/agent.py              <- main agent (yahi sab kuch karta hai)
  scripts/get_refresh_token.py  <- ek baar chalane wala script (Google Refresh Token nikalne ke liye)
  scripts/setup_env.py          <- .env banane wala helper
  config.json                   <- aapka control panel (time, topic, mode)
  state.json                    <- agent ki yaad (kis slot par post ho chuki hai)
  requirements.txt              <- sirf ek dependency: requests
  .env.example                  <- .env ka sample (sirf example)
  .vscode/launch.json           <- VS Code ke 3 debug buttons
  .github/workflows/blog-agent.yml  <- GitHub Actions (automatic chalne ke liye)
  README.md                     <- ye file
```

Local setup (ek baar):

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Sirf `requests` chahiye. Baaki sab apne aap chalta hai.

---

## 2. Ye 5 keys kahan se aayengi

Ye paanchon values aapko chahiye. Ye `GROQ_API_KEY` aur Google wali 4 values hain.
Inhe aap local me `.env` file me rakhte ho, aur GitHub par **Actions Secrets** me.

### A) `GROQ_API_KEY` (Groq - LLM ke liye)

1. [console.groq.com/keys](https://console.groq.com/keys) kholo
2. Sign up / login karo
3. **Create API Key** dabao
4. Copy karke rakh lo. Ye `gsk_` se shuru hota hai.

### B) `GOOGLE_CLIENT_ID` aur `GOOGLE_CLIENT_SECRET` (Google Cloud se)

1. [console.cloud.google.com](https://console.cloud.google.com) kholo
2. Naya project banao (ya apna project chuno)
3. Left menu > **APIs & Services** > **Library**
4. **Blogger API** dhoondo aur **Enable** kar do (ye zaroori hai!)
5. **APIs & Services** > **OAuth consent screen**
   - App ka naam daal do (kuch bhi)
   - User email daal do
   - **Publishing status: "In production"** chuno

   > **Ye step sabse zaroori hai.** Agar "Testing" me chhod diya to Google ka refresh
   > token **7 din baad expire** ho jayega aur agent chup-chaap kaam karna chhod dega.
   > "In production" karne se token lambe time tak chalta hai.
6. **APIs & Services** > **Credentials** > **Create Credentials** > **OAuth client ID**
   - Application type: **Desktop app** (yahi chuno, "Web application" nahi)
   - Naam daal do, **Create** dabao
   - Yahan **Client ID** aur **Client secret** dikh jayenge - dono copy kar lo
   - Neeche **Download JSON** bhi daba kar `client_secret.json` download kar lo
     (ye file project folder me rakho - `.gitignore` me hai, kabhi push nahi hogi)

### C) `GOOGLE_REFRESH_TOKEN` (Blogger post karne ke liye)

Ye ek baar generate hota hai. Project me diye script se ban jayega:

```bash
pip install google-auth-oauthlib      # ye alag se install karna hai
python scripts/get_refresh_token.py client_secret.json
```

- Browser khulega, Google login karo, **Allow** dabao
- Script aapko **Client ID, Client Secret aur Refresh Token** print karega
- Ye script sirf aapke laptop par chalana hai, GitHub par nahi

> **Zaroori:** Blogger ke liye **API key kaam nahi karti** (API key se post ban hi nahi sakta).
> OAuth (refresh token) hi lagta hai. Isliye ye step skip mat karna.

### D) `BLOGGER_BLOG_ID`

1. [blogger.com](https://www.blogger.com) me login karke apna blog kholo
2. Browser ke address bar me URL dekho. Usme `blogID=` ke baad jo **number** hai
   wahi aapka Blog ID hai

   `https://www.blogger.com/blog/1234567890123456789` -> Blog ID = `1234567890123456789`

---

## 3. `.env` file kaise banayein

### Tareeka 1 (sabse aasan - script se)

```bash
python scripts/setup_env.py
```

Ye ek-ek karke paanchon values puchega, har ek ka hint dega, aur `.env` bana dega.
Galat format ho to warning dega (jaise blog ID me letters aa gaye).

### Tareeka 2 (haath se)

1. `.env.example` ko copy karke naam badal lo: `.env`
2. Har value ke aage apni asli value likh do

```
GROQ_API_KEY=gsk_your_key_here
GOOGLE_CLIENT_ID=123456789-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your_secret_here
GOOGLE_REFRESH_TOKEN=1//0g_your_refresh_token
BLOGGER_BLOG_ID=1234567890123456789
```

> **Dhyan:** `=` ke aas-paas koi space ya quote mat rakho. `KEY=value` aise hi likho.

**`.env` kabhi GitHub par push nahi karni** (`.gitignore` me hai).

---

## 4. Local me test karo (3 commands)

Ye teen commands is order me chalao. Ek ke baad doosra tab hi.

### Step 1: Sab theek hai ya nahi - `--check`

```bash
python scripts/agent.py --check
```

Ye check karta hai:

- 5 env variables hain ya nahi (OK / MISSING)
- Groq API se ek chhota sa call chal ke dekhta hai
- Google se access token le kar aapke Blogger blog ka naam dikhata hai

Agar sab `OK` aa gaye to exit code 0 hoga. **Ye koi post nahi banata.**

### Step 2: Article bana ke dekho (post nahi jayega) - `--dry-run`

```bash
python scripts/agent.py --dry-run
```

Ye topic dhoondhta hai, article likhta hai, edit karta hai, aur
`preview/YYYYMMDD-HHMMSS.html` file bana deta hai. Wo file browser me kholo aur
article dekh lo. **Blogger par kuch nahi jayega.**

### Step 3: Asli post - `--now`

```bash
python scripts/agent.py --now
```

Ye chaaron step chala kar Blogger par post kar deta hai. `config.json` me
`"mode": "draft"` hai to **draft** banega, `"mode": "publish"` hai to **live**.

### VS Code se (debug buttons)

`blogger-ai-agent` folder VS Code me kholo. Left side me **Run and Debug** icon
(F5) dabao. Upar se 3 options milenge:

- `1. Check`
- `2. Dry-run`
- `3. Now`

### `--slot` ka kaam

`config.json` me 3 slots hain (09:00, 14:00, 19:00). Test mode me bata sakte ho
kaunsa slot use karna hai (0 se shuru):

```bash
python scripts/agent.py --dry-run --slot 1     # 14:00 wala slot
python scripts/agent.py --now --slot 2         # 19:00 wala slot
```

---

## 5. GitHub par automatic chalana

### Step 1: GitHub par push karo

```bash
cd blogger-ai-agent
git init
git add .
git commit -m "blogger-ai-agent: first commit"
git branch -M main
git remote add origin https://github.com/AAPKA-USERNAME/blogger-ai-agent.git
git push -u origin main
```

### Step 2: 5 Secrets add karo

Repo me jao > **Settings** > **Secrets and variables** > **Actions** > **New repository secret**

Ye paanchon secrets ek-ek karke banao (name bilkul same rakho):

| Secret name | Value kya daalni hai |
|---|---|
| `GROQ_API_KEY` | `gsk_...` wali value |
| `GOOGLE_CLIENT_ID` | Google Cloud ka Client ID |
| `GOOGLE_CLIENT_SECRET` | Google Cloud ka Client Secret |
| `GOOGLE_REFRESH_TOKEN` | `1//...` wala refresh token |
| `BLOGGER_BLOG_ID` | aapke blog ka number |

> `GOOGLE_REFRESH_TOKEN` hi sabse important hai - 7 din me expire ho sakta hai
> (agar consent screen "In production" me nahi hai).

### Step 3: Workflow permissions

**Settings** > **Actions** > **General** > scroll down > **Workflow permissions**

- **Read and write permissions** chuno (ya "Allow GitHub Actions to create and
  approve pull requests" wala option bhi chalega)

Ye zaroori hai, warna `state.json` commit nahi hoga aur agent har baar wahi slot
dobara chala dega.

### Step 4: Manually chala ke dekho

**Actions** tab > **Blog Agent** > **Run workflow** > **Run workflow** dabao.
Phir "Blog Agent" kholo aur logs dekho. Aapko wahi numbered lines dikhengi jo
local par dikhti hain.

### Cron aur timing ke baare me

- Cron har 15 minute (`*/15 * * * *`) par chalta hai
- **GitHub ka cron 5 se 20 minute late chalta hai** - ye normal hai, ghabrao mat
- Isliye agent har 6 ghante ka **grace window** rakhta hai: agar koi slot time par
  chala nahi (GitHub busy tha), to usko thodi der me bhi complete kar deta hai
- **Private repo** me free Actions minutes limited hote hain (lagbhag 2000/month).
  Aapke liye cron ko `*/30 * * * *` kar do
  (`.github/workflows/blog-agent.yml` me `cron:` wali line badal do)
- **Public repo** me Actions bilkul free hai, to `*/15` chhod sakte ho

---

## 6. Time badalna ya agent rokna

Sab kuch `config.json` me hai. Ye file edit karo aur GitHub par push kar do -
 agli run se naye time lage honge.

```json
{
  "enabled": true,
  "mode": "draft",
  "niche": "Technology, AI aur mobile apps ki latest khabrein aur tutorials",
  "language": "Hinglish (Roman Hindi + English)",
  "tone": "friendly, simple, beginner-friendly",
  "word_count": 900,
  "slots": [
    { "time": "09:00", "focus": "latest AI/tech news" },
    { "time": "14:00", "focus": "how-to guide ya tutorial" },
    { "time": "19:00", "focus": "tools ya apps ka review" }
  ]
}
```

| Kya badalna hai | Kya karega |
|---|---|
| `"enabled": false` | Agent **bilkul kuch nahi karega** (pause). Wapas `true` karo to chalu |
| `"mode": "draft"` | Har post **draft** banegi (aap check karke khud publish karo) |
| `"mode": "publish"` | Har post **seedha live** ho jayegi |
| `"time"` | Post ka time. Format `HH:MM` 24-hour, aur timezone **IST (UTC+5:30)** |
| `"focus"` | Us slot par kis tarah ka topic chahiye |
| `"niche"` | Aapka blog kis baare me hai |
| `"language"` / `"tone"` | Article ka andaaz |
| `"word_count"` | Article ki approx length |

Time sirf **IST** me hota hai. Jaise 09:00 matlab subah 9 baje IST.

---

## 7. Models ke baare me (ek zaroori baat)

Ye project Groq ke chat completions API ko seedha (HTTP) call karta hai.
Sirf ek library (`requests`) use hoti hai - na Groq SDK, na `python-dotenv`.

| Kaam | Default model | Badalne ke liye |
|---|---|---|
| Topic dhoondhna + research/ article likhna (web search ke saath) | `openai/gpt-oss-120b` | env var `GROQ_SEARCH_MODEL` |
| Article edit / proofread | `openai/gpt-oss-120b` | env var `GROQ_EDIT_MODEL` |

> **Note (October 2026):** `groq/compound` (jo pehle built-in web search deta tha)
> **21 September 2026 ko retire** ho chuka hai - Groq ab us model ID par error
> deta hai. Isliye ab built-in `browser_search` tool use kiya ja raha hai, jo
> `openai/gpt-oss-120b` aur `openai/gpt-oss-20b` par chalta hai aur server side
> hi chalta hai (aapko koi search API key nahi lagani).
> Agar future me model badalna ho, sirf upar wala env var badal do.

Local me `.env` me likh sakte ho (ya GitHub Secret bana sakte ho):

```
GROQ_SEARCH_MODEL=openai/gpt-oss-120b
GROQ_EDIT_MODEL=openai/gpt-oss-120b
```

### Links kahan se aate hain?

Model ko strict bol diya hai ki **apne man se koi link na banaye**. Article ke
end me jo "Sources" section dikhta hai, wo **asli search results ke URLs** se
banta hai (max 5). Isliye links toote ya fake nahi honge.

---

## 8. Common errors aur unka hal

| Error / message | Kyu hua hai | Kya karein |
|---|---|---|
| `MISSING GROQ_API_KEY` (ya koi bhi key) | `.env` me value missing hai, ya naam galat hai | `.env` me woh key daali hai ya nahi dekho. Naam exact hone chahiye |
| `Groq API error 401: Invalid API Key` | Groq key galat ya typo hai | `console.groq.com/keys` se nayi key copy karo (copy karne ke baad trailing space mat rehne do) |
| `Groq API error 429` | Rate limit lag gaya (free plan me hota hai) | Agent khud 4 baar wait karke retry karta hai. Zyada post karni ho to keys badal do |
| `Groq API error 400` aur model ka naam ho | Model ID galat ya retire ho gaya | `GROQ_SEARCH_MODEL` / `GROQ_EDIT_MODEL` sahi value set karein |
| `Google token error 401: invalid_client` | Client ID/Secret galat | `client_secret.json` se dobara `GOOGLE_CLIENT_ID` aur `GOOGLE_CLIENT_SECRET` copy karo |
| `Google token error 400: invalid_grant` | Refresh token expire ya revoke ho gaya | `get_refresh_token.py` dobara chalao. Par pehle **OAuth consent screen "In production"** check karo, warna 7 din me phir expire ho jayega |
| `Blogger blog info error 403` | Blogger API enable nahi hai ya blog galat hai | Google Cloud me **Blogger API Enable** karo; Blog ID Blogger ke URL se dobara check karo |
| `Blogger post error 403` | Blog jisse linked nahi hai | Confirm karo ki ye Google account aur wahi blog use kar raha hai |
| Refresh token `1//` se shuru nahi hota | Galat value paste hui | `get_refresh_token.py` se naya token lo |
| `Article ka format galat hai: '===HTML===' line nahi mili` | Model ne format follow nahi kiya | Aam taur par ek dobara chalta hai. `word_count` kam kar ke dekho. 3 attempts ke baad slot chhoot jata hai |
| GitHub par post hi nahi ho rahi | Secrets ya permissions missing | Actions ke log dekho; Settings > Actions > General me permissions "Read and write" hon |
| `state.json` push nahi ho rahi | Workflow permission nahi hai | Settings > Actions > **Read and write permissions** on karo |
| Roz wahi topic aa raha hai | Topic state save nahi hua | `state.json` push nahi ho rahi (upar wali line dekho) |
| Agent `skip` kar raha hai bina post kiye | Slot time abhi nahi hua, ya 6 ghante ka grace nikal gaya, ya 3 attempts ho chuke | `config.json` me time sahi hai ya nahi dekho |

---

## 9. Zaroori baatein

1. **Hamesha `"mode": "draft"` se shuru karo.** Jab tak aapne 5-6 drafts check
   nahi kiye ki quality kaisi hai, tab tak `publish` mat karo. Khud publish karna
   aapke haath me rehta hai.
2. **`state.json` ko haath se mat badlo** (ya agar badlo to JSON sahi rakho).
   Ye agent ki yaad hai - isse wahi topic dobara nahi likhta.
3. **`.env` aur `client_secret.json` kabhi GitHub par push mat karo.**
   `.gitignore` me hain, par kabhi kabhi `git add -f` se chala jata hai -
   dhyan rakho.
4. **Secrets GitHub me hamesha Actions Secrets me daalo**, workflow file ya
   config me kabhi nahi.
5. Pehle 2-3 din sirf draft par dekho. Article ki language (Hinglish), word
   count aur labels check kar lo, phir `publish` par jao.

---

## 10. Ek nazar me (quick reference)

```bash
# Setup (ek baar)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install google-auth-oauthlib      # sirf refresh token nikalne ke liye

# Keys
python scripts/get_refresh_token.py client_secret.json
python scripts/setup_env.py

# Test
python scripts/agent.py --check
python scripts/agent.py --dry-run
python scripts/agent.py --now

# VS Code se: F5 dabao aur "1. Check" / "2. Dry-run" / "3. Now" chuno
```

GitHub par: **Actions** tab se secrets dalo, permissions ON karo, phir
**Run workflow** se manually chala ke dekho.

Chalo shuru karte hain - pehle `python scripts/agent.py --check` chalao!