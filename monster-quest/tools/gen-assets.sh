#!/usr/bin/env bash
# Generates all Monster Quest assets via assetforge. Resilient: continues on error.
set +e
cd "$(dirname "$0")/.."   # run from the monster-quest project root
SPR=assets/sprites
TEX=assets/textures
CUT=assets/cutscene
AUD=assets/audio
UI=assets/ui
log(){ echo "[$(date +%H:%M:%S)] $*"; }

gen_sprite(){ # name prompt
  local out="$SPR/$1.png"; shift; local name="$out"
  [ -f "$name" ] && { log "skip $name"; return; }
  log "sprite -> $name"
  assetforge image "$1, centered, full body, vibrant saturated colors, clean cel-shaded cartoon style, soft rim light, isolated on solid flat #00ff00 chroma green background, no shadows on ground" -o "$name" --aspect 1:1 2>&1 | tail -1
  [ -f "$name" ] && assetforge cutout "$name" -o "$name" 2>&1 | tail -1
}

gen_tex(){ # name prompt
  local out="$TEX/$1.png"; shift
  [ -f "$out" ] && { log "skip $out"; return; }
  log "tex -> $out"
  assetforge image "$1, seamless tileable texture, top-down, even flat lighting, high detail, no shadows, fills frame" -o "$out" --aspect 1:1 2>&1 | tail -1
}

gen_img(){ # path aspect prompt
  local out="$1" asp="$2"; shift 2
  [ -f "$out" ] && { log "skip $out"; return; }
  log "img -> $out"
  assetforge image "$1" -o "$out" --aspect "$asp" 2>&1 | tail -1
}

# ---------- CHARACTER SPRITES ----------
gen_sprite hero "a brave young adventurer hero named Kael, green tunic, brown boots, small leather satchel, determined smile, spiky brown hair, chibi proportions, heroic pose, video game character"
gen_sprite ember "a cute fire elemental creature companion, round body made of orange and yellow flames, big friendly eyes, tiny arms, glowing ember spots, pokemon-style monster, chibi"
gen_sprite aqua "a cute water elemental creature companion, translucent blue water droplet body, big sparkly eyes, fin ears, glowing aqua core, pokemon-style monster, chibi"
gen_sprite vine "a cute grass elemental creature companion, round green leafy body, flower petals as a collar, big cheerful eyes, sprout on head, pokemon-style monster, chibi"
gen_sprite boss "a menacing shadow boss monster, towering dark void demon with glowing purple cracks, jagged crystal horns, burning violet eyes, wisps of dark smoke, epic video game boss, intimidating"
gen_sprite sage "a wise old sage, long white beard, glowing teal robe with star patterns, wooden staff with a crystal, kind eyes, fantasy mentor character"

# ---------- ITEMS ----------
gen_sprite gem "a glowing magical crystal gem collectible, faceted cyan crystal emitting light, sparkles, video game pickup item icon"
gen_sprite heart "a glowing red heart life pickup, soft glow, video game health item icon, cute"
gen_sprite key "a ornate golden ancient key collectible, glowing runes, video game pickup item"
gen_sprite orb_fire "a fiery orange capture orb, swirling flame energy inside a glass sphere, video game item"

# ---------- TEXTURES ----------
gen_tex grass "lush stylized fantasy grass meadow ground, vibrant green blades with tiny flowers, cartoon game texture"
gen_tex stone "ancient mossy dungeon stone floor bricks, ornate carved runes, weathered grey blocks, fantasy game texture"
gen_tex crystal "glowing magic crystal floor, purple and teal luminescent crystalline surface, fantasy game texture"
gen_tex wood "wooden plank platform, weathered planks with metal bolts, warm brown, cartoon game texture"
gen_tex lava "bubbling molten lava, glowing orange cracks over dark rock, fantasy game texture"

# ---------- CUTSCENE / BACKGROUNDS ----------
gen_img "$CUT/scene1.png" 16:9 "epic wide establishing shot of a lush fantasy valley at golden hour, floating islands, a glowing ancient temple in distance, waterfalls, dramatic god rays, Studio Ghibli inspired, painterly, no text"
gen_img "$CUT/scene2.png" 16:9 "a young hero in green tunic kneeling to meet a tiny glowing fire elemental creature in a sunlit forest clearing, magical sparkles, warm cinematic lighting, painterly fantasy art, no text"
gen_img "$CUT/scene3.png" 16:9 "a towering shadow demon with glowing purple cracks rising over a darkened fantasy valley, swirling storm clouds, ominous purple lightning, epic dramatic, painterly fantasy art, no text"
gen_img "$CUT/title_bg.png" 16:9 "majestic fantasy world panorama, floating crystal islands above clouds at sunrise, distant glowing castle, vibrant magical atmosphere, painterly key art, no text"
gen_img "$TEX/sky.png" 16:9 "dreamy fantasy sky, soft gradient from warm peach horizon to deep blue zenith, fluffy clouds, distant floating islands silhouettes, no characters"

# ---------- AUDIO ----------
[ -f "$AUD/overworld.ogg" ] || { log "music overworld"; assetforge music "uplifting heroic fantasy adventure overworld theme, orchestral with light flute and strings, whimsical, looping, 100 bpm" -o "$AUD/overworld.ogg" --format ogg 2>&1 | tail -1; }
[ -f "$AUD/boss.ogg" ] || { log "music boss"; assetforge music "intense epic boss battle music, dramatic orchestral, pounding drums, dark choir, fast tempo, fantasy" -o "$AUD/boss.ogg" --format ogg 2>&1 | tail -1; }
[ -f "$AUD/calm.ogg" ] || { log "music calm"; assetforge music "peaceful magical forest ambient, gentle harp and soft pads, serene fantasy, looping" -o "$AUD/calm.ogg" --format ogg 2>&1 | tail -1; }

# ---------- NARRATION ----------
[ -f "$AUD/narration1.mp3" ] || { log "tts n1"; assetforge tts "Long ago, the valley of Lumina thrived in harmony with the elemental spirits. But when the Shadow King shattered the Crystal of Balance, darkness crept across the land." -o "$AUD/narration1.mp3" --voice Charon --format mp3 2>&1 | tail -1; }
[ -f "$AUD/narration2.mp3" ] || { log "tts n2"; assetforge tts "You are Kael, the last Spirit Warden. With the elemental companions at your side, you must restore the shards of light and face the darkness within the Shadow Temple." -o "$AUD/narration2.mp3" --voice Charon --format mp3 2>&1 | tail -1; }

log "ALL DONE"
