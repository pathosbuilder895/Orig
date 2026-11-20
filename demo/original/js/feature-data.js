/* feature-data.js: the 97 active Original features (Tiers 1-16 plus the
   baseline-comparison pair) as plain-English cards for the live suite.
   Codes, tier membership and order match original/constants.py
   (tests/test_original_suite_static.py pins this). Tier 17 (behavioural)
   and Tier 18 (uniformity) are disabled in the product and are not listed.
   Each habit's name is its plain name from original/explainer.py
   (FEATURE_PLAIN_NAMES) with the first letter capitalised, never the
   engine's own label: tests/test_original_suite_static.py pins that too,
   and the evidence API reads its names from this file
   (original/evidence.py, describe()). `phrase` is the same name for use
   inside a sentence (first letter lower case; every plain name starts
   lower case, so the two forms are exact inverses).

   Taken from the navy design's js/feature-data.js with its invented
   baseline and submission values removed: this file carries names and
   descriptions only. Every number a page shows comes from the API.
   One display name differs from the design: Tier 7 is renamed "Natural
   Unevenness" (the pages' own plain label for it), because the design's
   name for that tier used verdict wording. Descriptions and tier blurbs are
   written in neutral third person ("the writer's", "this paper's"), not the
   design's second person: a teacher reads them about a student.

   The rule for descriptions (ADR-015 W2): a description says what the
   code computes, never more. Each one was checked against its extractor
   in original/features/ (and original/tension_arc.py for the tension
   score). It names what is counted or compared and, where the code makes
   it clear, what a higher value means. It makes no claim the code does
   not support: no reading of intent or awareness, no spelling or grammar
   check where the code only matches a word pattern, no "how often" for a
   measure that counts each word once, and nothing about AI or who wrote
   the paper. When an extractor changes, its description changes with it.

   window.OriginalFeatures = {
     tiers:  [ {key,pill,name,status,c,blurb,word,group,features:[{code,name,phrase,desc,tier,tierName,c}]} ],
     flat:   [ ...all 97 feature objects in tier order ],
     byCode: { code: featureObj },   (no prototype, so any code is only a key)
     total:  97,
   } */
(function () {
  const TIERS = [
    { key:'tier1', pill:'Tier 1', name:'Surface Stylometrics', status:'active', c:'#4d90c8',
      blurb:'word & sentence choices so automatic a writer does not notice making them', features:[
      ['type_token_ratio','Vocabulary range','How many different words the writer uses compared with the total word count.'],
      ['hapax_legomena_rate','Words used only once','Share of words that appear exactly once: wide vocabularies use many one-offs.'],
      ['mean_sentence_length','Typical sentence length','Average words per sentence: short and punchy, or long and winding.'],
      ['sentence_length_variance','Variation in sentence length','How much the writer\'s sentence lengths bounce around compared with staying even.'],
      ['function_word_ratio','Small everyday words (the, of)','Share of words that are small function words (the, of, and, to, in and the others on Original\'s list).'],
      ['passive_voice_ratio','Use of passive voice','Passive-looking phrases per sentence, capped at 1: is, was, been or a similar word followed by an -ed or -en word ("was thrown"). A word pattern, so some matches (such as "is often") are not passives.'],
      ['modal_verb_ratio','Use of might, could, must','Share of words that are modal verbs: can, could, may, might, must, should, will, would and similar.'],
      ['stop_word_ratio','Very common words (a, is, at)','Share of common connector words (a, is, at) that carry little meaning alone.'],
      ['avg_word_length','Average word length','How long the writer\'s words tend to be: "utilize" writes differently than "use."'],
    ]},
    { key:'tier2', pill:'Tier 2', name:'Discourse Analysis', status:'active', c:'#9a7ad0',
      blurb:'how the writer connects one idea to the next', features:[
      ['discourse_marker_density','Linking words (therefore, also)','How many different linking words and phrases from Original\'s list (however, therefore, in addition) appear, per 100 words. Each one counts once, however often it is used.'],
      ['additive_ratio','Add-on words (also, moreover)','Of the different linking words used, the share that add on (also, furthermore, moreover, in addition). The rest are contrast, cause or sequence words.'],
      ['adversative_ratio','Contrast words (but, however)','Of the different linking words used, the share that contrast (but, however, although, on the other hand).'],
      ['causal_ratio','Cause-and-effect words (because, so)','Of the different linking words used, the share that give a cause or a result (because, therefore, so, as a result).'],
      ['temporal_ratio','Sequence words (first, then)','Of the different linking words used, the share about order or time (first, then, next, finally, in conclusion).'],
      ['thematic_progression_score','Building on the previous sentence','Share of neighbouring sentence pairs where the first half of the second sentence\'s content words repeats a word from the second half of the one before. A word-overlap stand-in for picking up where the last sentence ended.'],
      ['pronoun_reference_density','Pronouns like it and this','Pointing words per sentence: he, she, it, they, this, that, these, those, such and their forms. It counts the words, not whether each one refers back to something.'],
      ['lexical_chain_density','Word overlap between sentences','How much neighbouring sentences share words: the average overlap of their content words (three letters or more, very common words left out). Exact repeats only, not related words.'],
      ['paragraph_topic_position','Content-heavy paragraph openings','Share of paragraphs whose first sentence has the highest share of content words in that paragraph (one-sentence paragraphs count). A stand-in for opening a paragraph with its main point.'],
      ['avg_paragraph_length','Average paragraph length','How many sentences are packed into a paragraph before a new one starts.'],
      ['sentence_opener_variety','Variety in sentence starters','How evenly sentence openings spread across six kinds: a pronoun, a word such as although or because, a linking word such as however, the, a or an, a lower-case start, or anything else. Higher means a more even mix.'],
      ['cohesion_device_ratio','Words tying the text together','Share of words that are pronouns, repeats of a content word of four letters or more, or linking words (each different linking word counted once), capped at 1.'],
      ['transition_density','Transition phrases (for example, in fact)','Transition words and phrases (for example, in fact, however, therefore) per 100 words, every use counted wherever it falls in a sentence.'],
    ]},
    { key:'tier3', pill:'Tier 3', name:'Rhetorical Register', status:'active', c:'#5aab7a',
      blurb:'the voice taken with a reader: certain, formal, persuasive', features:[
      ['epistemic_certainty_ratio','Certainty versus hedging','Of all the hedging and certainty words found (perhaps, may, seems against clearly, certainly, must), the share that are certainty words. 0.5 when neither kind appears.'],
      ['hedging_density','Use of hedging words','Hedging words and phrases from Original\'s list (perhaps, may, seems, somewhat, to some extent) per 100 words. The list includes everyday words such as about and often, so not every match softens a claim.'],
      ['assertion_density','Certainty words (clearly, obviously)','Certainty words and phrases from Original\'s list (clearly, certainly, undoubtedly, must, it is obvious) per 100 words.'],
      ['source_integration_style','Commenting on sources','After a sentence that cites (a reference such as Romans 8:28, or a phrase such as according to or argues), how often the next sentence is the writer\'s own, with four or more longer content words and no citation. Without citations, a small score from phrases such as in other words.'],
      ['counter_argument_ratio','Sentences that concede or contrast','Share of sentences with a contrast or concession word in their first six words (however, but, although, granted, one might argue). It does not check whether an opposing view is stated or answered.'],
      ['claim_density','Claim words (therefore, this shows)','How often claim and conclusion phrases appear: therefore, this shows, I argue.'],
      ['question_ratio','Use of questions','How often a question is asked instead of just stating something.'],
      ['imperative_density','Direct commands (consider, note)','Sentences that begin with a verb from a fixed list (consider, note, remember, pray), per 100 words. Some list words (be, let, know) can open a sentence that is not a command.'],
      ['first_person_ratio','Share of I and we','Of all personal pronouns, the share that are first person (I, me, my, we, us, our).'],
      ['appeal_to_authority_density','Appeals to authority','Phrases that point to a source or authority (according to, as noted by, argues, et al., cf.) per 100 words. Common verbs on the list, such as states and suggests, count whoever their subject is.'],
      ['conclusion_strategy_score','How the conclusion is built','In the last fifth of the paper, how many of three kinds of closing phrase appear: a summing-up phrase (in conclusion, therefore), an implication phrase (this means, consequently) and an open-question phrase (further research, remains to be seen). 0, one third, two thirds or 1.'],
      ['theological_register_score','Theological vocabulary','How much specialised theological vocabulary appears.'],
    ]},
    { key:'tier4', pill:'Tier 4', name:'Char & Punctuation', status:'active', c:'#c88a3a',
      blurb:'tiny punctuation & letter habits below conscious control', features:[
      ['char_trigram_entropy','Variety of letter combinations','How varied the three-character sequences (letters, spaces and punctuation) are across the whole paper; higher means more varied. Longer papers tend to score higher.'],
      ['punctuation_diversity','Punctuation variety','How evenly the paper\'s punctuation is spread across different marks; higher means more kinds of mark, used in more even amounts.'],
      ['comma_rate','Comma usage','How often a comma appears per stretch of words.'],
      ['semicolon_colon_rate','Semicolon and colon usage','How often semicolons and colons appear: some writers never touch them.'],
      ['parenthetical_rate','Use of parentheses','How often an opening parenthesis appears, per 100 words, whether it starts a side note or a citation.'],
      ['dash_rate','Use of dashes','How often a dash (an em dash, an en dash or a double hyphen) appears, per 100 words, including dashes in number ranges.'],
      ['quote_rate','Use of quotation marks','How often an opening double quotation mark appears, per 100 words, whatever it is used for.'],
    ]},
    { key:'tier5', pill:'Tier 5', name:'POS & Syntax', status:'active', c:'#4db0c8',
      blurb:'the grammatical skeleton under the sentences', features:[
      ['pos_bigram_entropy','Variety of grammar patterns','How predictable the two-word grammar patterns are.'],
      ['pos_trigram_entropy','Variety of longer grammar patterns','Same idea, one layer deeper: three-word grammar patterns.'],
      ['noun_verb_ratio','Noun-to-verb balance','Whether the writing leans on naming things (nouns) or describing action (verbs).'],
      ['adjective_rate','Adjective frequency','Adjectives per 100 words and punctuation marks, as labelled by Original\'s grammar tagger, whether or not they sit before a noun.'],
      ['adverb_rate','Adverb frequency','Adverbs (quickly, very, also) per 100 words and punctuation marks, as labelled by Original\'s grammar tagger, whatever word they modify.'],
      ['subordination_ratio','Subordinate clauses per sentence','Subordinating words (because, although, if, whether) per sentence, as labelled by Original\'s grammar tagger.'],
      ['clause_depth_mean','Depth of sentence structure','How deeply nested the sentences get.'],
    ]},
    { key:'tier6', pill:'Tier 6', name:'Idiosyncratic Patterns', status:'active', c:'#c85a9a',
      blurb:'personal quirks below the level of any taught rule', features:[
      ['contraction_rate','Use of contractions (don\'t, it\'s)','How often don\'t is written instead of do not.'],
      ['sentence_initial_conjunction_rate','Sentences opening with and/but','How often a sentence starts with And, But or So.'],
      ['that_which_ratio','That vs. which usage','The preference between these two when introducing a clause.'],
      ['citation_style_consistency','Mix of citation formats','How many different citation formats are mixed together, compared with one format each time.'],
      ['list_marker_preference','List style (numbers, bullets)','Whether numbers, letters or bullets are used when listing.'],
      ['abbreviation_tendency','Abbreviation usage','For a fixed list of short forms used in theology and Bible study (NT, cf., e.g., Rom., ch.), the share written short rather than in full. 0.5 when neither form appears.'],
    ]},
    { key:'tier7', pill:'Tier 7', name:'Natural Unevenness', status:'active', c:'#4d6fc8',
      blurb:'how evenly words, repetitions and transitions spread through the writing', features:[
      ['burstiness','Mix of short and long sentences','How uneven sentence lengths are: the variance of words per sentence divided by the average sentence length. Higher means more spread between short and long sentences.'],
      ['perplexity_proxy','Rarity of word choices','How rare the paper\'s words are on average in a general English word-frequency list; higher means rarer words. Each word is looked up on its own, not in context.'],
      ['repetition_gap_entropy','Spacing of repeated words','How varied the distances are between repeats of the same word (four letters or more, small function words left out); higher means the gaps come in more different sizes.'],
      ['transition_predictability','Word overlap between paragraphs','How much each paragraph\'s vocabulary repeats the paragraph before it.'],
      ['vocabulary_introduction_rate','How early new words appear','How quickly new words are introduced compared with recycling the same ones.'],
      ['filler_hedge_cluster_rate','Bunching of hedge words','Whether hedging words (perhaps, may, seems) bunch together or spread out, from how uneven the gaps between them are. Higher means more bunched; 0 with fewer than three.'],
    ]},
    { key:'tier8', pill:'Tier 8', name:'Prosodic Rhythm', status:'active', c:'#7aab2a',
      blurb:'the musical rhythm of the sentences read aloud', features:[
      ['stress_entropy_unigram','Balance of stressed syllables','How evenly syllables split between stressed and unstressed under a rough spelling rule (each vowel group is a syllable; longer words are stressed on the second-to-last). Higher means a more even split.'],
      ['stress_entropy_bigram','Variety in syllable rhythm','The same rough stress rule over pairs of neighbouring syllables; higher means the four possible pairs occur in more even amounts.'],
      ['clausulae_consistency','Steady final-syllable stress','How consistently sentences end on the same kind of syllable, stressed or not, under the same rough stress rule. In practice it tracks how consistently sentences end on a one-syllable word.'],
      ['breath_group_variance','Variation in syllables per sentence','How much the number of syllables in a sentence varies through the paper.'],
    ]},
    { key:'tier9', pill:'Tier 9', name:'Cognitive Sequencing', status:'active', c:'#a06a3a',
      blurb:'the shape of how an argument is built, point by point', features:[
      ['structural_centrist_penalty','Repetitive argument steps','Each sentence is tagged by keyword rules as a question, contrast, conclusion, evidence, claim or other. Higher means fewer different step-to-step pairs, so the same few sequences repeat.'],
      ['argument_sequence_likelihood','Usual order of argument steps','How usual this paper\'s order of sentence types (question, contrast, conclusion, evidence, claim, other, tagged by keyword rules) is, judged by the order those types follow in the past papers. Higher means a more familiar order.'],
    ]},
    { key:'tier10', pill:'Tier 10', name:'Semantic Gravity', status:'active', c:'#4a9b9b',
      blurb:'whether ideas stay focused or wander', features:[
      ['semantic_field_dispersion','Spread of ideas across sentences','How much the distance in content between pairs of sentences varies, from a numerical summary of each sentence; higher means some pairs are much closer than others.'],
      ['semantic_centroid_proximity','Closeness to usual topics','How close this paper\'s sentences sit in content to the nearest past paper\'s average, from a numerical summary of each sentence; higher means closer.'],
    ]},
    { key:'tier11', pill:'Tier 11', name:'Error Ecology', status:'active', c:'#c85a5a',
      blurb:'the mistakes made, and whether they match the usual ones', features:[
      ['error_kl_divergence','Mix of mistake types','How closely this paper\'s mix of three rough counts matches the past papers\' mix; higher means closer. The counts are commas straight after a clause\'s main word (a rough comma-splice sign), runs of three or more adjectives before a noun, and doubled punctuation such as ?! or ,, with no spelling check.'],
      ['stumble_rate_consistency','Overall mistake rate','How close this paper\'s combined rate of the same three rough counts (comma-splice signs, adjective runs, doubled punctuation) is to the past papers\' rate; higher means closer. It is not a spelling or grammar check.'],
      ['punctuation_error_ratio','Doubled punctuation marks','How close this paper\'s rate of doubled punctuation (two or more of . , ; ! ? in a row, which includes an ellipsis typed as full stops) is to the past papers\' rate; higher means closer.'],
    ]},
    { key:'tier12', pill:'Tier 12', name:'Tension Arc', status:'active', c:'#c8802a',
      blurb:'the emotional/dramatic shape of the essay start to finish', features:[
      ['catastrophe_index','Loose ends across paragraphs','Built from a rough tension reading for each sentence (unfinished clauses, questions and contrast words, shifts in content). For each paragraph Original notes how often a tension peak is followed by a drop; higher means fewer drops overall and more difference between paragraphs.'],
    ]},
    { key:'tier13', pill:'Tier 13', name:'Prosodic Depth', status:'active', c:'#5aab7a',
      blurb:'a deeper layer of sentence music & whether structure resolves', features:[
      ['clausula_type_consistency','Same rhythm at sentence ends','How consistently sentences close on the same rhythm pattern, read from their last syllables under the rough stress rule; higher means more alike.'],
      ['breath_group_regularity','Even spacing between pauses','How even the stretches of words are between commas, semicolons, colons, dashes and ellipses (full stops do not end a stretch); higher means more even.'],
      ['vowel_sonority_ratio','Share of long vowel sounds','Share of vowel groups spelled as common long-vowel pairs (ee, ea, oo, ou, ai and similar). It goes by spelling, not sound.'],
      ['arc_resolution_score','Shorter sentences toward the end','Whether sentences in the last quarter run shorter than those earlier in the paper.'],
      ['metric_flatness_score','Rhythm evenness across paragraphs','How alike paragraphs are in their share of words with two or more syllables (counted roughly by vowel groups); higher means more alike.'],
      ['clausula_shape_preference','Light or heavy sentence endings','The usual sentence ending, from light (0) to heavy classical endings (1), read from the last syllables under the rough stress rule.'],
    ]},
    { key:'tier14', pill:'Tier 14', name:'Error Topology', status:'active', c:'#c8955a',
      blurb:'where and how the mistakes show up, not just how many', features:[
      ['error_topology_consistency','Where comma splices fall','Where likely comma splices fall in their paragraphs (early, middle or late); higher means they cluster in one position within this paper. 0.5 with fewer than two, and splices are found by a word pattern, not a grammar check.'],
      ['article_omission_rate','Likely missing a, an, the','A rough count of singular nouns after a preposition with no a, an, the or similar word before them, per 100 words, scaled 0 to 1. Many are correct English (by faith, in practice), so this is not a count of mistakes.'],
      ['pronoun_ambiguity_rate','Possibly unclear pronouns','Of the sentences with he, she, it, they or their forms, the share whose two sentences before hold four or more noun-like words. A rough sign of where a reference could be unclear, not a check of what each pronoun refers to.'],
      ['comma_splice_rate','Comma splice frequency','Likely comma splices per 100 sentences, scaled 0 to 1: a comma followed by a word such as he, it, this or the, with a common verb on both sides. A word pattern, not a grammar check.'],
    ]},
    { key:'tier15', pill:'Tier 15', name:'Lexical Architecture', status:'active', c:'#8a7ad0',
      blurb:'the shape of the vocabulary: where words come from & how arranged', features:[
      ['semantic_field_concentration','How related the main nouns are','How related in meaning the 20 most frequent longer words are (four letters or more, nouns or not), from a table of word meanings; without that table, the share that start with the same four letters.'],
      ['polysyndeton_ratio','And-chains vs. comma lists','Whether items are strung with repeated "and"s instead of commas.'],
      ['chiasmus_rate','Mirrored sentence patterns (A-B-B-A)','How often the last three word classes (noun, verb, adjective and so on) of one sentence appear in reverse order at the start of the next, per 100 sentence pairs, scaled 0 to 1. It compares grammar labels only, not words or meaning.'],
      ['latinate_ratio','Words with Latin endings (-ous, -ive)','Share of content words with Latin- or French-style endings (-tion, -ment, -ity, -ous, -ive, -ate and similar). It goes by the ending, not the word\'s history.'],
      ['nominalization_density','Abstract nouns (-tion, -ness)','How often words ending in -tion, -ment, -ness, -ity, -ance or -ence appear, per 100 words, scaled 0 to 1. It goes by the ending, so words such as moment count too.'],
    ]},
    { key:'tier16', pill:'Tier 16', name:'Citation Patterns', status:'active', c:'#4d90c8',
      blurb:'personal habits in how sources are used and cited', features:[
      ['signal_verb_entropy','Variety of citing verbs','How varied the signal verbs are (argues, claims, notes) vs. always one.'],
      ['signal_verb_assertiveness','Strength of citing verbs','How forcefully the signal verbs frame a claim: "asserts" vs. "suggests."'],
      ['source_loyalty_index','Returning to the same authors','Share of parenthetical citations, such as (Calvin 1559), that name an author already cited. 0.5 with fewer than three.'],
      ['block_quote_rate','Use of block quotes','Words inside long quotations (more than 40 words in quotation marks, or an indented block) per 1,000 words of the writer\'s own prose.'],
      ['citation_density_cv','Bunching of citations','Whether citations spread evenly or clump in certain paragraphs.'],
      ['ibid_usage_rate','Use of ibid. and op. cit.','How often ibid. or op. cit. shorthand is used.'],
      ['citation_position_pref','Where citations sit in sentences','Whether citations are placed at the start, middle or end of a sentence.'],
      ['paraphrase_density','Paraphrases credited to sources','Attribution phrases (according to, as Calvin noted, following Barth) per 100 words of the writer\'s own prose. It counts the phrases, whether or not a quotation follows.'],
    ]},
    { key:'tiercomp', pill:'Comparison', name:'Comparison', status:'active', c:'#8a8a8a',
      blurb:'computed only against the baseline, not stored on their own', features:[
      ['char_trigram_profile_divergence','Drift in letter patterns','How far this paper\'s letter-pattern habits drift from the baseline.'],
      ['function_word_profile_divergence','Drift in small everyday words','How far the glue-word habits drift from the baseline.'],
    ]},
  ];

  const flat = [], byCode = Object.create(null);
  TIERS.forEach(tier => {
    tier.features = tier.features.map(([code, name, desc]) => {
      const phrase = name.charAt(0).toLowerCase() + name.slice(1);
      const obj = { code, name, phrase, desc, tier: tier.key, tierName: tier.name, c: tier.c };
      flat.push(obj); byCode[code] = obj;
      return obj;
    });
  });

  const WORDS = { tier1:'Wording', tier2:'Flow', tier3:'Tone', tier4:'Punctuation', tier5:'Grammar',
    tier6:'Quirks', tier7:'Evenness', tier8:'Rhythm', tier9:'Structure', tier10:'Focus', tier11:'Mistakes',
    tier12:'Suspense', tier13:'Cadence', tier14:'Slip-ups', tier15:'Vocabulary', tier16:'Sourcing', tiercomp:'Drift' };
  TIERS.forEach(t => { t.word = WORDS[t.key] || ''; });

  // Three high-level groups (from the original three-tier framing)
  const GROUPS = {
    tier1:'Surface', tier4:'Surface', tier5:'Surface', tier6:'Surface', tier11:'Surface', tier14:'Surface', tier15:'Surface',
    tier2:'Discourse', tier8:'Discourse', tier9:'Discourse', tier12:'Discourse', tier13:'Discourse',
    tier3:'Rhetorical', tier7:'Rhetorical', tier10:'Rhetorical', tier16:'Rhetorical', tiercomp:'Rhetorical',
  };
  TIERS.forEach(t => { t.group = GROUPS[t.key] || 'Surface'; });

  window.OriginalFeatures = {
    tiers: TIERS, flat, byCode,
    total: flat.length,
  };
})();
