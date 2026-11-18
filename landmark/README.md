# Landmark Cases series

One long video per landmark case, told as a continuous story in AI scenes. The Professor opens and closes it on
camera, and his cloned voice narrates in between. It runs in this repository and uses the same secrets and the same
Kaggle engine as the weekly videos.

## The flow
1. **L1 - Write landmark storyboard** runs every Wednesday at 10 pm IST, or from its button (you can type part of a
   case name, e.g. `Maneka`).
   - Gemini picks the next case from `cases.csv` and writes `cases/<case code>/story.json`.
   - You get an email with the whole storyboard, a fact-check list, a **Fix** link and an **Approve** link.
2. Tapping **Approve** opens **L2 - Make landmark video** → **Run workflow**. Leave the case empty to use the newest
   storyboard.
   - L2 builds the Kaggle job: every scene, the Professor's start and end, and every narration sentence in his voice.
   - It sends the job in the 11 am–3 pm IST slot, or leaves it waiting for **3c**, which sends it at 11:00 the next day.
3. Kaggle makes the job in about 3 to 4.5 hours of GPU time.
   - **3b - Collect** publishes the results and starts L2 again by itself.
4. L2 puts the video together and emails you **video ready**, with:
   - the long video at 1920x1080
   - English captions (`.srt`)
   - 2 thumbnails
   - 2 or 3 upright Shorts, rebuilt from the story's beats: scenes fill the screen, cards have an upright layout,
     captions split by sentence, the title card and Professor are left out, and an end card closes each one
   - the posting plan: title, description with chapters, disclaimer and credits, tags, pinned comment, and AI
     disclosure = Yes

## Files
| File | What it is |
|---|---|
| `cases.csv` | The case list. Write `skip` in `status` to leave a case out. Cases with a storyboard are done. |
| `settings.json` | Length (minutes), number of scenes, 720p "Fast" regenerate, music, posting time |
| `storyboard.py` | L1: Gemini storyboard + approval email |
| `job.py` | L2 part 1: the Kaggle job (scene prompts, cast, continuity, narration) |
| `make.py` | L2 part 2: puts the video, captions, thumbnails, Shorts and posting plan together |
| `cards.py` | The on-screen cards: title, law, quote, golden triangle, timeline, holdings, exam recap |
| `cases/<code>/story.json` | The storyboard. Edit it on GitHub before approving if anything is wrong. |

## The storyboard (story.json)
- `cast`: the recurring people, each with a fixed description so they look the same in every scene. All of them are
  invented and Indian.
- `beats`: in order. Each beat is one of:
  - `professor`: on camera, the intro and outro
  - `scene`: one 5-second H3 clip. It is slowed down up to 1.5x to fit the narration, then its last picture is held
    with a slow zoom. So a scene carries at most 2 short sentences (22 words); longer moments are split over 2-3 shots.
    Prompts forbid signboards and readable letters (the AI writes nonsense on them).
  - `card`: a graphic
- `cont: true`: the scene starts from the previous scene's last picture, so the same people and place carry on.
- `dialogue`: at most 7 words, in at most 3 scenes. These scenes are made at 544p with automatic retakes, the lip-sync
  house rules.

## Safety rules (built into the Gemini prompt)
- The video is a dramatised reconstruction: invented actors who don't look like the real people, judges never named on
  screen, and invented dialogue. Every description carries the disclaimer.
- Facts come only from the judgment. Anything uncertain goes to the "please double-check" list in the email.

## If something is missing
- A scene Kaggle couldn't make becomes a chapter card.
- A narration sentence that failed the Whisper check is read by the Microsoft Indian English voice.
- The email lists both.

## Kaggle sharing
Both series use the same `manzi-engine` notebook. A job that arrives while another run is still on Kaggle waits
(`engine/state/waiting-*.json`) and is sent by **3c** the next day at 11:00 IST.

Weekly GPU budget: about 1 h for the weekly videos and about 4 h per landmark case, out of about 30 h.
