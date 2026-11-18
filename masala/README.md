# Masala Shorts (Entertainment With Manzi)

Hindi TV-serial-style drama Shorts, written with Claude in chat and made by the Manzi Engine on Kaggle.

## How to make one

1. **In the Claude chat** (Project "clickbank"), say *"Masala: new ideas"*. Claude follows
   `claude/masala-master-prompt.md`: ideas → you pick one and a length → script → characters → the **story file**.
2. **On GitHub:** open `masala/inbox/` → **Add file → Create new file**. Name it anything (for example
   `riya.json`), paste the whole story file, and press **Commit changes**. It works from the phone too.
3. **Wait for the emails.** "M - Make masala short" starts by itself:
   - **Please fix the story:** something in the file breaks a rule. The email lists exactly what; paste it to Claude,
     get the corrected file and paste it into `masala/inbox/` again. Nothing is made from a file with problems.
   - **Making the clips:** the file is fine and the clips go to Kaggle (sent between 11 am and 3 pm IST; outside that
     window it waits for "3c" at 11 am the next day). About 10–12 min of GPU per clip, so a 1-minute Short takes
     about 1.5 h.
   - **Short ready:** the Short, its thumbnail, Hindi captions (.srt) and the posting plan (title, description with
     credits, tags). Upload by hand from YouTube Studio and set *Altered or synthetic content = Yes*.

To make a story again (after changing it), paste the changed file again. A file whose scenes did not change re-uses
the clips Kaggle already made; any change to the characters, clothes or scenes makes new clips.

## Why it does not freeze

Every scene is **one upright (9:16) 8-second clip**, and the scene's line is spoken by the character **inside** that
clip, with lip-sync (MiniMax H3 speaks Hindi). Nothing is slowed down, stretched or held, so the length of the Short
is simply the number of scenes × 8 s. That is why the story file has rules:

| Rule | Why |
|---|---|
| at most 12 words per line | lip-sync stays good (about 1.5 words a second) |
| one speaker per scene | a second voice in the same clip gets mixed up |
| at most 3 people per shot | more people means mixed-up faces |
| a long face description per character, the same in every scene | the same face from clip to clip |
| clothes per day in `wardrobe` | the same clothes through a day, new ones on a new day |
| 7–9 scenes for 1:00, 10–13 for 1:30, 14–17 for 2:00, 17–21 for 2:30 | the length you asked for |
| `"continue": true` | the clip starts from the last picture of the scene before: same place, same people, same light |

## The story file

```json
{
  "slug": "moti-aur-nakli-bank-wala",          // lowercase English, numbers and dashes: the file and video name
  "title": "YouTube title (max 100 characters)",
  "duration": "1:00",                           // 1:00, 1:30, 2:00 or 2:30
  "category": "…", "hook_text": "big words on top for the first 3 s", "end_text": "last 2.5 s (optional)",
  "look": "film look (optional)",
  "characters": [{"id": "kamla", "name": "Kamla Devi", "age": 68, "gender": "woman", "role": "…",
                  "face": "long English description of face, skin, hair, body", "voice": "how she sounds"}],
  "wardrobe": {"1": {"kamla": "what she wears on day 1"}},
  "scenes": [{"id": "s01", "day": 1, "place": "…", "action": "English: shot, action, emotion, light",
              "cast": ["kamla", "moti"], "speaker": "kamla", "line": "Hindi line in Devanagari",
              "caption": "(optional) caption if different from the line", "sound": "(optional)", "continue": false}],
  "thumbnail": {"scene": "s05", "text": "big thumbnail words"},
  "youtube": {"description": "…", "tags": ["…"]}
}
```

A full example: `masala/examples/moti-aur-nakli-bank-wala.json`. Check a file yourself with
`python masala/story.py <file>`.

## Files

- `story.py`: reads and checks a story file (the rules above)
- `intake.py`: picks up pasted files from `inbox/` → `stories/<slug>/story.json`, or `rejected/` with an email
- `job.py`: the Kaggle job (one clip per scene: 9:16, 8 s, Hindi, 544p preview → 720p Fast; a size that does not fit
  the GPU memory falls back to 480p, then 384p)
- `make.py`: puts the Short together (hard cuts, the clips' own sound, hook and captions drawn by Chromium so Hindi is
  shaped correctly, soft music, loudness for Shorts), checks for still stretches, uploads and emails
- `settings.json`: clip length, sizes, word limit, scenes per duration, music

Credits (in every description): MiniMax H3 (MiniMax H3 Community License), Wan2GP, AIQUEST Academy's Kaggle engine.
