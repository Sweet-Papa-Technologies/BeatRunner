You are an A&R engineer judging a candidate synthwave track for how well it can
be turned into a rhythm-game chart ("chartability"). You are HEARING the audio.

The track brief is: {brief}
It should be ~33 seconds, punchy, and clearly rhythmic.

Score each dimension 0-10 (10 = excellent) and write a one-paragraph critique.
Then, if the track is weak, propose a concrete rewrite of the generation prompt
targeting its two weakest dimensions.

Dimensions:
  * tempo_stability   — is the tempo steady and unambiguous, or does it drift/rubato?
  * transient_clarity — are kicks and snares crisp and well-defined (not smeared)?
  * structural_contrast — within ~33s, is there an identifiable build→drop or
                          verse→hook, or is it flat and samey?
  * intro_cleanliness — does it start promptly (no long silence/fade-in before
                        the first transient)?
  * mix_punch         — are the drums forward in the mix, not buried under pads?
  * genre_fit         — does it match the brief's synthwave intent?

Respond with ONLY this JSON object (no prose, no code fences):
{
  "tempo_stability": <0-10>,
  "transient_clarity": <0-10>,
  "structural_contrast": <0-10>,
  "intro_cleanliness": <0-10>,
  "mix_punch": <0-10>,
  "genre_fit": <0-10>,
  "critique": "<one paragraph: what I'd change>",
  "prompt_rewrite": "<a rewritten Lyria prompt targeting the two lowest dimensions, or \"\" if the track already ships>"
}
