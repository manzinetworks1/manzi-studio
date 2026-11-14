# Manzi Engine (Kaggle GPU)

Makes the AI scenes and the Professor's narration on Kaggle's free **GPU T4 x2**, in the background. Your laptop isn't needed.

## How to run it
GitHub → **Actions** → **3 - Manzi Engine (Kaggle GPU)** → **Run workflow** → pick a job file from `engine/jobs/`.

- Kaggle may keep the job in a queue before it starts.
- If the job takes longer than the wait time, **3b - Collect engine results** picks it up. It checks every 3 hours, or you can press its button.
- The results arrive as a **Release** (videos, voices and a report), and you get a "Run … is ready" email.

## What is inside
| File | What it does |
|---|---|
| `kernel_main.py` | The Kaggle job: AIQUEST's setup → H3 scenes → narration in the cloned voice → Whisper check |
| `runner_snippet.py` | Headless job runner, used in place of AIQUEST's web page |
| `voice_stage.py` | Clones the Professor's voice (Chatterbox and Qwen3-TTS), checks each piece with Whisper and matches the pace |
| `build_kernel.py` | Packs everything plus the job into one Kaggle script |
| `collect.py` | Downloads the results, publishes the Release and sends the email |
| `vendor/aiquest_h3.ipynb` | Frozen copy of AIQUEST's notebook (Apache 2.0), saved on the first run |
| `cast/professor.json` | Recipe for the approved Professor (Take 3): seed, prompt and settings |
| `jobs/*.json` | Jobs: lists of scenes and narration |

## Secrets needed
- `KAGGLE_USERNAME`, `KAGGLE_KEY` (kaggle.com → Settings → API → Create New Token)
- `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` (already set)

## Credits (keep these in every video description)
Scenes made with **MiniMax H3** (MiniMax H3 Community License). Built with **Wan2GP** (https://github.com/deepbeepmeep/Wan2GP) and AIQUEST Academy's Kaggle H3 engine (Apache 2.0).
