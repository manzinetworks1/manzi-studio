# Manzi Studio: one-time setup (about 30 minutes)

Everything runs in the cloud on GitHub's free computers. Your laptop is never used.
You can do all of this in a phone or computer browser.

## 1. GitHub account and the repository
1. Go to **github.com/signup** and make a free account. Remember your username.
2. Tap **+** (top right) → **New repository**.
   - Name: `manzi-studio`
   - Choose **Private**
   - Do **not** tick "Add a README"
   - Tap **Create repository**
3. Tell Claude your GitHub username. Claude puts the code into the repository for you.
   (Or upload the files yourself: on the repository page → "uploading an existing file" → drag the whole unzipped folder.)

## 2. Gemini API key (free), for writing the scripts
1. Go to **aistudio.google.com** → **Get API key** → **Create API key**. Copy it.

## 3. Gmail app password, for the emails
1. Go to **myaccount.google.com** → **Security** → turn on **2-Step Verification** (if it is off).
2. Go to **myaccount.google.com/apppasswords** → name it `Manzi Studio` → **Create**.
3. Copy the 16-letter password it shows. (It only works for sending these emails, not for logging in.)

## 4. Put the keys into GitHub (they stay secret)
On your repository page: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Add these one by one:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | the key from step 2 |
| `GMAIL_ADDRESS` | your Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-letter password from step 3 |
| `SARVAM_API_KEY` | only if you use Sarvam voices (see below) |

## 5. Your topic list
Open `topics.csv` in the repository → ✏️ (edit) → add one exam question per line:

```
subject,question,marks,asked_years,status
Administrative Law,Discuss the main grounds on which ...,15,2019 2022 2023,
```

- `asked_years`: years this question came in your university exam (optional). With years, you also get the "Asked 3× in exams" Short.
- `status`: write `skip` to leave a question out. Questions that are done are remembered automatically.
- Tap **Commit changes**.

(Prefer Google Sheets? Make a sheet with the same columns → File → Share → **Publish to web** → choose **CSV** → copy the link into `topics_csv_url` in `config.json`.)

## 6. Settings (optional): `config.json`
- `channel`, `course`, `language` (`english` or `hindi`)
- `topics_per_week` (2) and `shorts_per_topic` (4): 2 topics → 2 long videos + 8 Shorts a week
- Voice: `"engine": "edge"` = Microsoft Indian voices (free). `edge_voice`: `en-IN-PrabhatNeural` (male) or `en-IN-NeerjaNeural` (female); `edge_rate` "+8%" = a little faster than normal.
- For Sarvam: `"engine": "sarvam"`, add the `SARVAM_API_KEY` secret. About ₹3-4 per video.
- Posting times: `long_time`, `short_time`, `short_time_2`.

## 7. First test
1. Repository → **Actions** tab → if asked, tap **I understand my workflows, go ahead and enable them**.
2. Tap **1 - Write scripts** → **Run workflow** → **Run workflow**.
3. In a few minutes you get an email: **"Check this week's scripts"**. Read them.
   - Wrong fact? Tap **Fix this topic**, change the text between the quotes "…", tap **Commit changes**.
4. Tap **Approve and make the videos** → **Run workflow**.
5. About 20-40 minutes later: email **"videos ready"** with the posting plan and download links.

## Every week after that
- **Sunday 10 pm**: scripts are written automatically → email → you check and approve (10-20 min on your phone).
- **Videos ready** email → download → YouTube Studio app → Upload → paste title and description → **Schedule** (15-20 min).

## Good to know
- Free GitHub allows 2,000 minutes a month for private repositories; one week uses roughly 40-80.
- Downloads come from your repository's **Releases** page (you must be signed in to GitHub).
- If something fails you get no "ready" email: open **Actions**, tap the red ✗ run, and send Claude a screenshot.
