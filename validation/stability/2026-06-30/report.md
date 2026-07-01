# Length-stability study

_Generated 2026-06-30T21:24:21.998446Z_

## Corpus

| author | word count | windows@250 | windows@500 | windows@1000 | windows@2000 | windows@5000 |
|---|---|---|---|---|---|---|
| augustine | 111,821 | 12 | 12 | 12 | 12 | 12 |
| boethius | 42,710 | 12 | 12 | 12 | 12 | 8 |
| chesterton | 63,819 | 12 | 12 | 12 | 12 | 12 |
| edwards | 113,943 | 12 | 12 | 12 | 12 | 12 |
| james | 186,374 | 12 | 12 | 12 | 12 | 12 |
| kempis | 63,393 | 12 | 12 | 12 | 12 | 12 |
| mill | 52,045 | 12 | 12 | 12 | 12 | 10 |
| newman | 159,383 | 12 | 12 | 12 | 12 | 12 |

**Notes:**
- 6 tier-17 (keystroke) features were excluded — text-only input gives them constant 0.5, so F is undefined.

## Top 30 length-robust features (F(500) / F(5000) descending)

Features that keep most of their discriminating power on short inputs. Phase-2 weight schedule should LEAN INTO these at low word count.

| rank | feature | tier | F(500) | F(5000) | ratio |
|---|---|---|---|---|---|
| 1 | `adversative_ratio` | 2 | 0.680 | 0.053 | 12.904 |
| 2 | `repetition_gap_entropy` | 7 | 0.558 | 0.156 | 3.568 |
| 3 | `article_omission_rate` | 14 | 1.495 | 0.471 | 3.173 |
| 4 | `type_token_ratio` | 1 | 0.446 | 0.143 | 3.113 |
| 5 | `avg_paragraph_length` | 2 | 0.277 | 0.154 | 1.804 |
| 6 | `theological_register_score` | 3 | 0.222 | 0.159 | 1.402 |
| 7 | `abbreviation_tendency` | 6 | 0.482 | 0.375 | 1.288 |
| 8 | `signal_verb_assertiveness` | 16 | 0.061 | 0.047 | 1.285 |
| 9 | `signal_verb_entropy` | 16 | 0.080 | 0.074 | 1.080 |
| 10 | `paragraph_topic_position` | 2 | 0.076 | 0.070 | 1.080 |
| 11 | `semicolon_colon_rate` | 4 | 0.698 | 0.715 | 0.976 |
| 12 | `temporal_ratio` | 2 | 0.044 | 0.058 | 0.766 |
| 13 | `char_trigram_entropy` | 4 | 1.032 | 1.372 | 0.752 |
| 14 | `breath_group_regularity` | 13 | 0.399 | 0.533 | 0.749 |
| 15 | `burstiness` | 7 | 0.677 | 0.944 | 0.717 |
| 16 | `discourse_marker_density` | 2 | 1.111 | 1.598 | 0.696 |
| 17 | `hapax_legomena_rate` | 1 | 0.641 | 1.000 | 0.641 |
| 18 | `stress_entropy_bigram` | 8 | 1.856 | 3.041 | 0.610 |
| 19 | `appeal_to_authority_density` | 3 | 0.107 | 0.185 | 0.579 |
| 20 | `paraphrase_density` | 16 | 0.086 | 0.160 | 0.539 |
| 21 | `assertion_density` | 3 | 0.382 | 0.713 | 0.536 |
| 22 | `lexical_chain_density` | 2 | 0.345 | 0.646 | 0.534 |
| 23 | `additive_ratio` | 2 | 0.203 | 0.402 | 0.505 |
| 24 | `avg_word_length` | 1 | 1.861 | 3.804 | 0.489 |
| 25 | `clausula_type_consistency` | 13 | 0.262 | 0.541 | 0.484 |
| 26 | `stress_entropy_unigram` | 8 | 1.809 | 3.748 | 0.483 |
| 27 | `question_ratio` | 3 | 0.409 | 0.916 | 0.446 |
| 28 | `nominalization_density` | 15 | 0.862 | 2.048 | 0.421 |
| 29 | `cohesion_device_ratio` | 2 | 0.854 | 2.071 | 0.412 |
| 30 | `structural_centrist_penalty` | 9 | 0.300 | 0.756 | 0.397 |

## Bottom 20 length-fragile features (F(500) / F(5000) ascending)

Features that lose most of their discriminating power on short inputs. Phase-2 weight schedule should DOWN-WEIGHT these at low word count.

| rank | feature | tier | F(500) | F(5000) | ratio |
|---|---|---|---|---|---|
| 1 | `citation_style_consistency` | 6 | 0.000 | 0.080 | 0.000 |
| 2 | `chiasmus_rate` | 15 | 0.681 | 15.058 | 0.045 |
| 3 | `parenthetical_rate` | 4 | 0.083 | 1.646 | 0.050 |
| 4 | `block_quote_rate` | 16 | 0.340 | 6.144 | 0.055 |
| 5 | `clausula_shape_preference` | 13 | 0.075 | 1.137 | 0.066 |
| 6 | `noun_verb_ratio` | 5 | 2.016 | 28.451 | 0.071 |
| 7 | `filler_hedge_cluster_rate` | 7 | 0.475 | 4.815 | 0.099 |
| 8 | `vocabulary_introduction_rate` | 7 | 0.084 | 0.718 | 0.117 |
| 9 | `first_person_ratio` | 3 | 0.628 | 5.340 | 0.117 |
| 10 | `function_word_ratio` | 1 | 4.110 | 33.536 | 0.123 |
| 11 | `counter_argument_ratio` | 3 | 0.235 | 1.844 | 0.127 |
| 12 | `list_marker_preference` | 6 | 0.071 | 0.524 | 0.136 |
| 13 | `pronoun_ambiguity_rate` | 14 | 0.380 | 2.683 | 0.142 |
| 14 | `stop_word_ratio` | 1 | 5.784 | 37.520 | 0.154 |
| 15 | `vowel_sonority_ratio` | 13 | 1.564 | 9.948 | 0.157 |
| 16 | `polysyndeton_ratio` | 15 | 0.223 | 1.415 | 0.158 |
| 17 | `sentence_opener_variety` | 2 | 1.339 | 8.233 | 0.163 |
| 18 | `that_which_ratio` | 6 | 0.151 | 0.927 | 0.163 |
| 19 | `imperative_density` | 3 | 0.189 | 1.116 | 0.170 |
| 20 | `clause_depth_mean` | 5 | 1.102 | 6.460 | 0.171 |

## Per-tier aggregate

Mean Fisher ratio per tier across the 5 length buckets. **HOLDS** = stability ratio ≥ 0.7; **DEGRADES** = 0.3 ≤ ratio < 0.7; **COLLAPSES** = ratio < 0.3. Tier 0 (comparison features) and tier 17 (keystroke) are excluded from this aggregate.

| tier | n features | mean F(250) | mean F(500) | mean F(1000) | mean F(2000) | mean F(5000) | mean ratio | flag |
|---|---|---|---|---|---|---|---|---|
| 1 | 9 | 1.078 | 1.690 | 3.135 | 4.686 | 9.239 | 0.659 | DEGRADES |
| 2 | 13 | 0.500 | 0.676 | 0.971 | 1.486 | 2.087 | 1.539 | HOLDS |
| 3 | 12 | 0.223 | 0.333 | 0.592 | 0.792 | 1.360 | 0.404 | DEGRADES |
| 4 | 7 | 0.795 | 1.696 | 2.495 | 3.838 | 7.048 | 0.399 | DEGRADES |
| 5 | 7 | 1.611 | 2.810 | 3.777 | 8.637 | 15.565 | 0.251 | COLLAPSES |
| 6 | 6 | 0.327 | 0.446 | 0.627 | 0.871 | 1.458 | 0.361 | DEGRADES |
| 7 | 6 | 2.734 | 6.215 | 12.002 | 15.138 | 24.339 | 0.951 | HOLDS |
| 8 | 4 | 0.642 | 0.983 | 1.538 | 2.070 | 1.980 | 0.387 | DEGRADES |
| 9 | 2 | 0.091 | 0.150 | 0.104 | 0.282 | 0.378 | 0.397 | DEGRADES |
| 10 | 2 | 0.195 | 0.191 | 0.278 | 0.743 | 0.566 | 0.338 | DEGRADES |
| 11 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | n/a |
| 12 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | n/a |
| 13 | 6 | 0.362 | 0.391 | 0.563 | 0.976 | 2.049 | 0.360 | DEGRADES |
| 14 | 4 | 0.407 | 0.575 | 0.612 | 0.884 | 1.199 | 0.953 | HOLDS |
| 15 | 5 | 0.355 | 0.640 | 1.019 | 1.772 | 4.545 | 0.256 | COLLAPSES |
| 16 | 8 | 0.090 | 0.081 | 0.113 | 0.359 | 0.847 | 0.638 | DEGRADES |
