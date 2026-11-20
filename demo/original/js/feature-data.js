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
      ['function_word_ratio','Small everyday words (the, of)','Share of glue words (the, of, and, but), used without thinking about it.'],
      ['passive_voice_ratio','Use of passive voice','How often the writer uses "the ball was thrown" instead of "she threw the ball."'],
      ['modal_verb_ratio','Use of might, could, must','How often should, might, could and must appear: signalling how sure the writer is.'],
      ['stop_word_ratio','Very common words (a, is, at)','Share of common connector words (a, is, at) that carry little meaning alone.'],
      ['avg_word_length','Average word length','How long the writer\'s words tend to be: "utilize" writes differently than "use."'],
    ]},
    { key:'tier2', pill:'Tier 2', name:'Discourse Analysis', status:'active', c:'#9a7ad0',
      blurb:'how the writer connects one idea to the next', features:[
      ['discourse_marker_density','Linking words (therefore, also)','How often linking phrases like however, therefore and in addition appear.'],
      ['additive_ratio','Add-on words (also, moreover)','Connecting ideas by adding on (and, also, furthermore) vs. contrasting.'],
      ['adversative_ratio','Contrast words (but, however)','How often the writer pushes back with but, however or on the other hand.'],
      ['causal_ratio','Cause-and-effect words (because, so)','How often cause and effect is explained: because, therefore, as a result.'],
      ['temporal_ratio','Sequence words (first, then)','How often events are sequenced in time: then, meanwhile, afterward.'],
      ['thematic_progression_score','Building on the previous sentence','How smoothly each sentence builds on the one before vs. jumping around.'],
      ['pronoun_reference_density','Pronouns like it and this','How often it, this and they refer back instead of repeating the noun.'],
      ['lexical_chain_density','Word overlap between sentences','How tightly word choices link back to earlier related words.'],
      ['paragraph_topic_position','Content-heavy paragraph openings','Where the main point is planted: up front, in the middle, or at the end.'],
      ['avg_paragraph_length','Average paragraph length','How many sentences are packed into a paragraph before a new one starts.'],
      ['sentence_opener_variety','Variety in sentence starters','How much sentence openings are mixed up compared with starting them alike.'],
      ['cohesion_device_ratio','Words tying the text together','Overall connective tissue holding the writing together.'],
      ['transition_density','Transition phrases (for example, in fact)','How often transition words appear between sentences specifically.'],
    ]},
    { key:'tier3', pill:'Tier 3', name:'Rhetorical Register', status:'active', c:'#5aab7a',
      blurb:'the voice taken with a reader: certain, formal, persuasive', features:[
      ['epistemic_certainty_ratio','Certainty versus hedging','How confidently things are stated: "this is true" vs. "this may be true."'],
      ['hedging_density','Use of hedging words','How often claims are softened with perhaps, it seems or somewhat.'],
      ['assertion_density','Certainty words (clearly, obviously)','How often flat, confident statements of fact are made.'],
      ['source_integration_style','Commenting on sources','How a quote is woven in: dropped in bluntly, or built around smoothly.'],
      ['counter_argument_ratio','Sentences that concede or contrast','How often an opposing view is raised before it is answered.'],
      ['claim_density','Claim words (therefore, this shows)','How often claim and conclusion phrases appear: therefore, this shows, I argue.'],
      ['question_ratio','Use of questions','How often a question is asked instead of just stating something.'],
      ['imperative_density','Direct commands (consider, note)','How often direct commands appear: "consider this," "note that."'],
      ['first_person_ratio','Share of I and we','How often I or we is used compared with staying impersonal.'],
      ['appeal_to_authority_density','Appeals to authority','How often a claim is backed with an expert: "as Aquinas argued."'],
      ['conclusion_strategy_score','How the conclusion is built','How the writing wraps up: summarising, restating the thesis, ending on a quote.'],
      ['theological_register_score','Theological vocabulary','How much specialised theological vocabulary appears.'],
    ]},
    { key:'tier4', pill:'Tier 4', name:'Char & Punctuation', status:'active', c:'#c88a3a',
      blurb:'tiny punctuation & letter habits below conscious control', features:[
      ['char_trigram_entropy','Variety of letter combinations','How predictable the three-letter-chunk patterns are: nearly unconscious.'],
      ['punctuation_diversity','Punctuation variety','How many different punctuation marks are actually used.'],
      ['comma_rate','Comma usage','How often a comma appears per stretch of words.'],
      ['semicolon_colon_rate','Semicolon and colon usage','How often semicolons and colons appear: some writers never touch them.'],
      ['parenthetical_rate','Use of parentheses','How often a side note is tucked in (like this) using parentheses.'],
      ['dash_rate','Use of dashes','How often dashes (like this) interrupt or extend a sentence.'],
      ['quote_rate','Use of quotation marks','How often quotation marks appear, for citing or emphasis.'],
    ]},
    { key:'tier5', pill:'Tier 5', name:'POS & Syntax', status:'active', c:'#4db0c8',
      blurb:'the grammatical skeleton under the sentences', features:[
      ['pos_bigram_entropy','Variety of grammar patterns','How predictable the two-word grammar patterns are.'],
      ['pos_trigram_entropy','Variety of longer grammar patterns','Same idea, one layer deeper: three-word grammar patterns.'],
      ['noun_verb_ratio','Noun-to-verb balance','Whether the writing leans on naming things (nouns) or describing action (verbs).'],
      ['adjective_rate','Adjective frequency','How often nouns are decorated with descriptive words.'],
      ['adverb_rate','Adverb frequency','How often verbs are modified with words like quickly or clearly.'],
      ['subordination_ratio','Subordinate clauses per sentence','How often dependent clauses are built compared with simple standalone sentences.'],
      ['clause_depth_mean','Depth of sentence structure','How deeply nested the sentences get.'],
    ]},
    { key:'tier6', pill:'Tier 6', name:'Idiosyncratic Patterns', status:'active', c:'#c85a9a',
      blurb:'personal quirks below the level of any taught rule', features:[
      ['contraction_rate','Use of contractions (don\'t, it\'s)','How often don\'t is written instead of do not.'],
      ['sentence_initial_conjunction_rate','Sentences opening with and/but','How often a sentence starts with And, But or So.'],
      ['that_which_ratio','That vs. which usage','The preference between these two when introducing a clause.'],
      ['citation_style_consistency','Mix of citation formats','How many different citation formats are mixed together, compared with one format each time.'],
      ['list_marker_preference','List style (numbers, bullets)','Whether numbers, letters or bullets are used when listing.'],
      ['abbreviation_tendency','Abbreviation usage','How often words are shortened (e.g., etc.) compared with written out.'],
    ]},
    { key:'tier7', pill:'Tier 7', name:'Natural Unevenness', status:'active', c:'#4d6fc8',
      blurb:'how evenly words, repetitions and transitions spread through the writing', features:[
      ['burstiness','Mix of short and long sentences','How much sentence length and complexity vary, burst to burst.'],
      ['perplexity_proxy','Rarity of word choices','How predictable the word choices are from one word to the next.'],
      ['repetition_gap_entropy','Spacing of repeated words','How evenly spaced the word repetitions are across the paper.'],
      ['transition_predictability','Word overlap between paragraphs','How much each paragraph\'s vocabulary repeats the paragraph before it.'],
      ['vocabulary_introduction_rate','How early new words appear','How quickly new words are introduced compared with recycling the same ones.'],
      ['filler_hedge_cluster_rate','Bunching of hedge words','Whether hedge words bunch together rather than spreading naturally.'],
    ]},
    { key:'tier8', pill:'Tier 8', name:'Prosodic Rhythm', status:'active', c:'#7aab2a',
      blurb:'the musical rhythm of the sentences read aloud', features:[
      ['stress_entropy_unigram','Balance of stressed syllables','How varied the stressed/unstressed pattern is, syllable by syllable.'],
      ['stress_entropy_bigram','Variety in syllable rhythm','Same idea for pairs of syllables: a bigger rhythmic pattern.'],
      ['clausulae_consistency','Steady final-syllable stress','How consistent the rhythm is at the end of the sentences.'],
      ['breath_group_variance','Variation in syllables per sentence','How much the number of syllables in a sentence varies through the paper.'],
    ]},
    { key:'tier9', pill:'Tier 9', name:'Cognitive Sequencing', status:'active', c:'#a06a3a',
      blurb:'the shape of how an argument is built, point by point', features:[
      ['structural_centrist_penalty','Repetitive argument steps','How closely the essay follows an even point, counterpoint, conclusion pattern.'],
      ['argument_sequence_likelihood','Usual order of argument steps','Compares the order points are introduced and resolved against the baseline.'],
    ]},
    { key:'tier10', pill:'Tier 10', name:'Semantic Gravity', status:'active', c:'#4a9b9b',
      blurb:'whether ideas stay focused or wander', features:[
      ['semantic_field_dispersion','Spread of ideas across sentences','How spread out or tightly clustered the core concepts are.'],
      ['semantic_centroid_proximity','Closeness to usual topics','How close this paper\'s topic sits to the writer\'s usual centre of gravity.'],
    ]},
    { key:'tier11', pill:'Tier 11', name:'Error Ecology', status:'active', c:'#c85a5a',
      blurb:'the mistakes made, and whether they match the usual ones', features:[
      ['error_kl_divergence','Mix of mistake types','Compares this paper\'s slip pattern to the writer\'s typical error pattern.'],
      ['stumble_rate_consistency','Overall mistake rate','Whether the overall error rate matches what\'s typical for the writer.'],
      ['punctuation_error_ratio','Doubled punctuation marks','Whether punctuation mistakes happen at the usual rate.'],
    ]},
    { key:'tier12', pill:'Tier 12', name:'Tension Arc', status:'active', c:'#c8802a',
      blurb:'the emotional/dramatic shape of the essay start to finish', features:[
      ['catastrophe_index','Loose ends across paragraphs','How often paragraphs leave the points they raise unresolved, and how unevenly.'],
    ]},
    { key:'tier13', pill:'Tier 13', name:'Prosodic Depth', status:'active', c:'#5aab7a',
      blurb:'a deeper layer of sentence music & whether structure resolves', features:[
      ['clausula_type_consistency','Same rhythm at sentence ends','How consistently the sentences land on the same rhythmic ending.'],
      ['breath_group_regularity','Even spacing between pauses','How evenly paced the breath pauses are.'],
      ['vowel_sonority_ratio','Share of long vowel sounds','The balance of open, resonant vowels vs. closed, clipped ones.'],
      ['arc_resolution_score','Shorter sentences toward the end','Whether sentences in the last quarter run shorter than those earlier in the paper.'],
      ['metric_flatness_score','Rhythm evenness across paragraphs','How uniform the rhythm is from paragraph to paragraph.'],
      ['clausula_shape_preference','Light or heavy sentence endings','The preferred way for a sentence\'s rhythm to fall at the end.'],
    ]},
    { key:'tier14', pill:'Tier 14', name:'Error Topology', status:'active', c:'#c8955a',
      blurb:'where and how the mistakes show up, not just how many', features:[
      ['error_topology_consistency','Where comma splices fall','Whether mistakes like comma splices show up in the same places each time.'],
      ['article_omission_rate','Likely missing a, an, the','How often a, an or the is left out where it would normally go.'],
      ['pronoun_ambiguity_rate','Possibly unclear pronouns','How often it or this is unclear about what it refers to.'],
      ['comma_splice_rate','Comma splice frequency','How often two full sentences are joined with just a comma.'],
    ]},
    { key:'tier15', pill:'Tier 15', name:'Lexical Architecture', status:'active', c:'#8a7ad0',
      blurb:'the shape of the vocabulary: where words come from & how arranged', features:[
      ['semantic_field_concentration','How related the main nouns are','How tightly clustered in meaning the most-used nouns are.'],
      ['polysyndeton_ratio','And-chains vs. comma lists','Whether items are strung with repeated "and"s instead of commas.'],
      ['chiasmus_rate','Mirrored sentence patterns (A-B-B-A)','How often a mirrored A-B-B-A structure is used for effect.'],
      ['latinate_ratio','Words with Latin endings (-ous, -ive)','How many words come from Latin roots (utilize) vs. plain (use).'],
      ['nominalization_density','Abstract nouns (-tion, -ness)','How often actions are turned into nouns: "we discussed" → "a discussion."'],
    ]},
    { key:'tier16', pill:'Tier 16', name:'Citation Patterns', status:'active', c:'#4d90c8',
      blurb:'personal habits in how sources are used and cited', features:[
      ['signal_verb_entropy','Variety of citing verbs','How varied the signal verbs are (argues, claims, notes) vs. always one.'],
      ['signal_verb_assertiveness','Strength of citing verbs','How forcefully the signal verbs frame a claim: "asserts" vs. "suggests."'],
      ['source_loyalty_index','Returning to the same authors','How often the same authors are returned to vs. citing many.'],
      ['block_quote_rate','Use of block quotes','How much is long indented quotation vs. the writer\'s own paraphrase.'],
      ['citation_density_cv','Bunching of citations','Whether citations spread evenly or clump in certain paragraphs.'],
      ['ibid_usage_rate','Use of ibid. and op. cit.','How often ibid. or op. cit. shorthand is used.'],
      ['citation_position_pref','Where citations sit in sentences','Whether citations are placed at the start, middle or end of a sentence.'],
      ['paraphrase_density','Paraphrases credited to sources','How often a source is restated in the writer\'s own words vs. quoting.'],
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
