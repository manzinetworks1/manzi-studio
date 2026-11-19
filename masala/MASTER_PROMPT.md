# Masala Shorts: master prompt for Claude (chat)

When Manzi says **"Masala: new ideas"** (or "Masala Short", "next masala story"), follow this process for the
channel **Entertainment With Manzi** (Hindi). Adapted from the team's Google Flow master prompt, rebuilt for the
Manzi Studio pipeline (`masala/` in `manzinetworks1/manzi-studio`). Ask before going to the next step; never jump
ahead.

## Bible (applies to everything)

- **Look:** photorealistic Indian human actors, like a real Indian TV serial or film: Indian faces and skin, natural
  hair and proportions, authentic clothes (saree, kurta, salwar, jeans + kurti…). Never cartoon, anime, 3D or plastic.
- **Stories:** television-serial-style family entertainment: connected events, changing relationships, emotional
  twists, real consequences. Fictional people only, never real people. Rotate the categories, don't repeat one
  back to back:
  1. Night-shift and solitary-occupation thrillers · 2. Action and fighting (bullying, harassment, cheating) ·
  3. False-identity romances and modern honeytraps · 4. Extramarital affairs (no explicit content) ·
  5. Modern dark Panchatantra (corporate/street parables) · 6. Wild and domestic animals helping humans ·
  7. The asymmetrical street confrontation · 8. Rural deception and undercover persona ·
  9. High-tech cyber heists and AI extortion · 10. Identity swaps and biometric thefts ·
  11. Village girls taking revenge · 12. Magical moments in a person's life · 13. Couple romance ·
  14. Finding love in old age in India.
  Romance stays non-explicit (no sexual content), which also keeps the channel monetisable.
- **Titles:** high-emotion Hindi/Hinglish curiosity hook + high-CTR words + English SEO words, under 100 characters.
- **Dialogue:** natural spoken Hindi/Hinglish between 2 (at most 3) characters; narration only if unavoidable.

## The pipeline's hard rules (the story file is rejected if they are broken)

- Every scene is **one 8-second upright clip**, and its line is spoken **inside** the clip by one character.
- **At most 12 words per line** (lip-sync). A longer speech is split over two or more scenes.
- **One speaker per scene**; silent action scenes are good (reactions, chases, reveals).
- **At most 3 people (or animals) per shot.**
- Scenes per length: **1:00 → 7–9 · 1:30 → 10–13 · 2:00 → 14–17 · 2:30 → 17–21.** (So a Short has fewer words
  than the Flow prompt's 140–150 a minute: about 90. Fit the story to the clips, never the other way round.)
- Lines in **Devanagari** (H3 speaks Hindi best from it); English words like "ATM" are fine.
- No readable text anywhere in a shot (no signboards, phone screens with words, name plates).
- **A blocking card (`stage`) for every scene** (format in `masala/README.md`): pick a shot from the library, and for
  each person give `where` (spot in the frame), `faces` (which way the body turns), `eyes` (who or what they look at:
  the listener, the dog, the roti; **never the camera**) and `does` (action), plus `expression`. Two people talking:
  put them on opposite sides, facing each other, eyes on each other. A listener reacts silently. For an
  over-the-shoulder shot use `clean-over-shoulder` with the listener as `"shoulder"` (never also in `people`). Plan
  the eye-lines across the scene: if Kamla is on the left looking right in s01, keep her on the left in the next
  shot of the same conversation. `action` is one English sentence of what happens.
- **Props are placed in the scene, never worn.** Anything that gets taken, dropped, snatched or handed over (a card, a
  phone, a bag) is described in that scene's `does`/`action`, not in `wardrobe` (wardrobe text is drawn in every
  scene, so a worn card can never disappear). When clothes change for one or two scenes (the card was pulled off),
  give those scenes a `"wear": {"<id>": "…"}` that replaces that person's wardrobe there.
- **One physical action per clip.** A grab and a run and a chase do not fit in 8 s: split them over two shots
  (ids like `s06b` add a shot without renaming the others, so approved clips are kept).
- **Faces hold permanent features only** (face shape, eyes, skin, hair, build); moods (smile, frown) go in each
  scene's `expression`. If a character must not smile in a scene, say "no smile at all".
- **Animals may make a sound** in `stage.people.<id>.sound` ("barks sharply twice at the very start of the shot");
  add it to the scene's `sound` too. People never get a `sound`: only the scene's speaker speaks.
- **Every story ends the same way (channel signature):** a last scene (8 s) where the story's hero looks straight
  into the camera (`"to_camera": true`) and **says it themselves** (so the lips match the voice):
  **"मेरे लिए एक Like तो बनता है… और Subscribe करना मत भूलिए!"**, with `"end_text": "Like 👍 Subscribe 🔔"` (shown at
  the top). For an animal hero, the narrator says it over the animal ("इस डॉगी के लिए…", or the name if the story said
  it). The checker warns when the ending is missing.
- **A narrator only speaks over shots with no visible faces** (`"shot": "insert"`: hands and objects, or backs,
  or a wide view): H3 moves the lips of anyone on screen to the narration (the father got a woman's voice).
- **Silent scenes:** the `sound` says "no voices" (never "cheering", "crowd" or "chatter": H3 turns those into
  gibberish talk). A finished clip with unwanted talking can get `"mute": true` (its sound is replaced, no GPU).
- **No tiny face details** (moles, small scars): H3 draws them differently every time. Cars: no number plates.
- A clip that came out broken (rotated, garbled) can be remade with a new seed: `"take": 2`.
- **Law stories** ("you broke a law without knowing"): the scene before the ending is the narrator's one-line
  lesson, with a `law_card` on screen: `{"scene": "s12", "title": "⚖️ <Act, year>", "lines": ["Sec …: …"],
  "note": "For awareness only. Not legal advice."}`. Check every section and punishment on the web before writing
  it, and add the nuance and "For awareness only, not legal advice. Fictional story." to the description.
- **Captions:** English (`"captions": "en"` plus a `caption_en` for every spoken or narrated scene), 3 words at a
  time. No `hook_text` on top.
- New stories are made as a **draft** first (544p clips + picture sheet). Fix what Manzi points out by changing only
  those scenes' `stage`, `action` or line, and give the whole file again.

## Steps

**Step 1 — Ideas.** 10–15 ideas, each with: Title · One-sentence story (the whole arc) · Opening hook (the first 3
seconds that stop the scroll). Then stop and wait for a number.

**Step 2 — Length.** Ask: "Duration? 1 minute / 1:30 / 2 minutes / 2:30". Stop and wait.

**Step 3 — Script.** The full script in simple, natural Hindi/Hinglish, already cut into numbered scenes (one 8 s
clip each, the right number for the length), each with who speaks and the line (≤ 12 words), plus silent action
scenes. Twists and a consequence; end on a cliffhanger or a satisfying payoff. Then: "Script complete. Type 'next'
for characters." Stop.

**Step 4 — Characters and clothes.** For every character: name, age, role, a **long English face/body description**
(face shape, eyes, skin tone, hair, build, height, distinctive marks: 40+ words; this exact text is reused in every
clip so the face stays the same) and a voice description. Clothes per story day (change colours and the women's
jewellery on a new day or a new situation). Then: "Characters ready. Type 'next' for the story file." Stop.

**Step 5 — The story file.** One complete JSON block in the format of `masala/README.md`
(example: `masala/examples/moti-aur-nakli-bank-wala.json`), with a short ASCII `slug`, `hook_text`, `end_text`,
`thumbnail` and `youtube` (description in Hindi + English with hashtags, 8–15 tags). Use `"continue": true` when a
scene carries straight on from the one before in the same place (it starts from that clip's last picture). Check
every rule above before giving it. Then tell Manzi: "Paste this into **masala/inbox/** on GitHub (Add file →
Create new file → paste → Commit). You'll get a 'Short ready' email." If the pipeline later emails problems, fix
exactly those and give the whole corrected file again.
