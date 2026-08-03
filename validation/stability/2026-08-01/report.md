# Length-stability study

_Generated 2026-08-02T03:39:04.685883Z_

## Corpus

| author | word count | windows@250 | windows@500 | windows@1000 | windows@2000 | windows@5000 |
|---|---|---|---|---|---|---|
| augustine | 111,821 | 12 | 12 | 12 | 12 | 12 |
| boethius | 42,700 | 12 | 12 | 12 | 12 | 8 |
| chesterton | 63,807 | 12 | 12 | 12 | 12 | 12 |
| edwards | 61,448 | 12 | 12 | 12 | 12 | 12 |
| james | 154,568 | 12 | 12 | 12 | 12 | 12 |
| kempis | 63,393 | 12 | 12 | 12 | 12 | 12 |
| mill | 52,040 | 12 | 12 | 12 | 12 | 10 |
| newman | 157,478 | 12 | 12 | 12 | 12 | 12 |

**Notes:**
- 6 tier-17 (keystroke) features were excluded — text-only input gives them constant 0.5, so F is undefined.

## Top 30 length-robust features (F(500) / F(5000) descending)

Features that keep most of their discriminating power on short inputs. Phase-2 weight schedule should LEAN INTO these at low word count.

| rank | feature | tier | F(500) | F(5000) | ratio |
|---|---|---|---|---|---|
| 1 | `additive_ratio` | 2 | 0.099 | 0.007 | 14.351 |
| 2 | `type_token_ratio` | 1 | 0.437 | 0.116 | 3.760 |
| 3 | `modal_verb_ratio` | 1 | 0.312 | 0.090 | 3.449 |
| 4 | `paragraph_topic_position` | 2 | 0.097 | 0.043 | 2.274 |
| 5 | `repetition_gap_entropy` | 7 | 0.350 | 0.156 | 2.244 |
| 6 | `avg_paragraph_length` | 2 | 0.256 | 0.142 | 1.797 |
| 7 | `causal_ratio` | 2 | 0.234 | 0.165 | 1.423 |
| 8 | `appeal_to_authority_density` | 3 | 0.103 | 0.073 | 1.418 |
| 9 | `avg_word_length` | 1 | 2.205 | 1.557 | 1.416 |
| 10 | `theological_register_score` | 3 | 0.574 | 0.411 | 1.396 |
| 11 | `signal_verb_assertiveness` | 16 | 0.061 | 0.048 | 1.274 |
| 12 | `hapax_legomena_rate` | 1 | 0.763 | 0.713 | 1.070 |
| 13 | `stress_entropy_bigram` | 8 | 2.046 | 1.942 | 1.054 |
| 14 | `stress_entropy_unigram` | 8 | 1.962 | 2.022 | 0.970 |
| 15 | `breath_group_regularity` | 13 | 0.457 | 0.488 | 0.937 |
| 16 | `cohesion_device_ratio` | 2 | 0.969 | 1.077 | 0.900 |
| 17 | `chiasmus_rate` | 15 | 0.040 | 0.045 | 0.898 |
| 18 | `semantic_field_dispersion` | 10 | 0.093 | 0.110 | 0.844 |
| 19 | `first_person_ratio` | 3 | 0.931 | 1.224 | 0.761 |
| 20 | `noun_verb_ratio` | 5 | 0.269 | 0.372 | 0.724 |
| 21 | `article_omission_rate` | 14 | 0.309 | 0.428 | 0.723 |
| 22 | `burstiness` | 7 | 0.396 | 0.567 | 0.699 |
| 23 | `semicolon_colon_rate` | 4 | 0.631 | 0.921 | 0.686 |
| 24 | `assertion_density` | 3 | 0.254 | 0.376 | 0.675 |
| 25 | `lexical_chain_density` | 2 | 0.419 | 0.652 | 0.642 |
| 26 | `arc_resolution_score` | 13 | 0.082 | 0.129 | 0.638 |
| 27 | `conclusion_strategy_score` | 3 | 0.135 | 0.228 | 0.590 |
| 28 | `subordination_ratio` | 5 | 0.239 | 0.406 | 0.588 |
| 29 | `filler_hedge_cluster_rate` | 7 | 0.110 | 0.188 | 0.586 |
| 30 | `claim_density` | 3 | 0.214 | 0.365 | 0.585 |

## Bottom 20 length-fragile features (F(500) / F(5000) ascending)

Features that lose most of their discriminating power on short inputs. Phase-2 weight schedule should DOWN-WEIGHT these at low word count.

| rank | feature | tier | F(500) | F(5000) | ratio |
|---|---|---|---|---|---|
| 1 | `citation_style_consistency` | 6 | 0.000 | 0.080 | 0.000 |
| 2 | `citation_position_pref` | 16 | 0.000 | 0.080 | 0.000 |
| 3 | `parenthetical_rate` | 4 | 0.021 | 0.872 | 0.024 |
| 4 | `counter_argument_ratio` | 3 | 0.062 | 0.940 | 0.066 |
| 5 | `list_marker_preference` | 6 | 0.018 | 0.229 | 0.078 |
| 6 | `block_quote_rate` | 16 | 0.563 | 6.032 | 0.093 |
| 7 | `function_word_ratio` | 1 | 0.215 | 2.219 | 0.097 |
| 8 | `pos_bigram_entropy` | 5 | 0.242 | 2.493 | 0.097 |
| 9 | `that_which_ratio` | 6 | 0.187 | 1.817 | 0.103 |
| 10 | `clause_depth_mean` | 5 | 0.337 | 2.936 | 0.115 |
| 11 | `perplexity_proxy` | 7 | 0.324 | 2.666 | 0.122 |
| 12 | `breath_group_variance` | 8 | 0.054 | 0.389 | 0.139 |
| 13 | `clausula_shape_preference` | 13 | 0.104 | 0.736 | 0.141 |
| 14 | `pos_trigram_entropy` | 5 | 0.278 | 1.799 | 0.154 |
| 15 | `adversative_ratio` | 2 | 0.033 | 0.209 | 0.156 |
| 16 | `polysyndeton_ratio` | 15 | 0.222 | 1.375 | 0.162 |
| 17 | `punctuation_diversity` | 4 | 0.266 | 1.561 | 0.170 |
| 18 | `temporal_ratio` | 2 | 0.023 | 0.132 | 0.172 |
| 19 | `stop_word_ratio` | 1 | 0.282 | 1.553 | 0.182 |
| 20 | `pronoun_reference_density` | 2 | 0.236 | 1.112 | 0.212 |

## Per-tier aggregate

Mean Fisher ratio per tier across the 5 length buckets. **HOLDS** = stability ratio ≥ 0.7; **DEGRADES** = 0.3 ≤ ratio < 0.7; **COLLAPSES** = ratio < 0.3. Tier 0 (comparison features) and tier 17 (keystroke) are excluded from this aggregate.

| tier | n features | mean F(250) | mean F(500) | mean F(1000) | mean F(2000) | mean F(5000) | mean ratio | flag |
|---|---|---|---|---|---|---|---|---|
| 1 | 9 | 0.504 | 0.600 | 0.443 | 0.619 | 0.949 | 1.311 | HOLDS |
| 2 | 13 | 0.318 | 0.260 | 0.224 | 0.394 | 0.535 | 1.783 | HOLDS |
| 3 | 12 | 0.232 | 0.290 | 0.409 | 0.501 | 0.551 | 0.611 | DEGRADES |
| 4 | 7 | 0.416 | 0.558 | 0.613 | 1.125 | 1.588 | 0.334 | DEGRADES |
| 5 | 7 | 0.239 | 0.288 | 0.398 | 0.688 | 1.386 | 0.362 | DEGRADES |
| 6 | 6 | 0.263 | 0.297 | 0.450 | 0.642 | 1.033 | 0.235 | COLLAPSES |
| 7 | 6 | 0.242 | 0.228 | 0.340 | 0.433 | 0.711 | 0.784 | HOLDS |
| 8 | 4 | 0.699 | 1.067 | 0.948 | 1.145 | 1.208 | 0.648 | DEGRADES |
| 9 | 2 | 0.099 | 0.104 | 0.082 | 0.224 | 0.441 | 0.235 | COLLAPSES |
| 10 | 2 | 0.109 | 0.046 | 0.054 | 0.098 | 0.055 | 0.844 | HOLDS |
| 11 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | n/a |
| 12 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | n/a |
| 13 | 6 | 0.231 | 0.279 | 0.320 | 0.539 | 0.712 | 0.510 | DEGRADES |
| 14 | 4 | 0.208 | 0.219 | 0.213 | 0.444 | 0.492 | 0.454 | DEGRADES |
| 15 | 5 | 0.304 | 0.511 | 0.747 | 0.889 | 1.239 | 0.504 | DEGRADES |
| 16 | 8 | 0.066 | 0.097 | 0.126 | 0.326 | 0.809 | 0.469 | DEGRADES |
