/* feature-data.js: the 97 active Original features (Tiers 1-16 plus the
   baseline-comparison pair) as plain-English cards for the live suite.
   Codes, tier membership, order and names match original/constants.py
   (tests/test_original_suite_static.py pins this). Tier 17 (behavioural)
   and Tier 18 (uniformity) are disabled in the product and are not listed.

   Taken from the navy design's js/feature-data.js with its invented
   baseline and submission values removed: this file carries names and
   descriptions only. Every number a page shows comes from the API.
   One display name differs from the design: Tier 7 is renamed "Natural
   Unevenness" (the pages' own plain label for it), because the design's
   name for that tier used verdict wording. Descriptions and tier blurbs are
   written in neutral third person ("the writer's", "this paper's"), not the
   design's second person: a teacher reads them about a student.

   window.OriginalFeatures = {
     tiers:  [ {key,pill,name,status,c,blurb,word,group,features:[{code,name,desc,tier,tierName,c}]} ],
     flat:   [ ...all 97 feature objects in tier order ],
     byCode: { code: featureObj },   (no prototype, so any code is only a key)
     total:  97,
   } */
(function () {
  const TIERS = [
    { key:'tier1', pill:'Tier 1', name:'Surface Stylometrics', status:'active', c:'#4d90c8',
      blurb:'word & sentence choices so automatic a writer does not notice making them', features:[
      ['type_token_ratio','Type–Token Ratio','How many different words the writer uses compared with the total word count.'],
      ['hapax_legomena_rate','Hapax Legomena Rate','Share of words that appear exactly once: wide vocabularies use many one-offs.'],
      ['mean_sentence_length','Mean Sentence Length','Average words per sentence: short and punchy, or long and winding.'],
      ['sentence_length_variance','Sentence Length Variance','How much the writer\'s sentence lengths bounce around compared with staying even.'],
      ['function_word_ratio','Function Word Ratio','Share of glue words (the, of, and, but), used without thinking about it.'],
      ['passive_voice_ratio','Passive Voice Ratio','How often the writer uses "the ball was thrown" instead of "she threw the ball."'],
      ['modal_verb_ratio','Modal Verb Ratio','How often should, might, could and must appear: signalling how sure the writer is.'],
      ['stop_word_ratio','Stop Word Ratio','Share of common connector words (a, is, at) that carry little meaning alone.'],
      ['avg_word_length','Average Word Length','How long the writer\'s words tend to be: "utilize" writes differently than "use."'],
    ]},
    { key:'tier2', pill:'Tier 2', name:'Discourse Analysis', status:'active', c:'#9a7ad0',
      blurb:'how the writer connects one idea to the next', features:[
      ['discourse_marker_density','Discourse Marker Density','How often linking phrases like however, therefore and in addition appear.'],
      ['additive_ratio','Additive Ratio','Connecting ideas by adding on (and, also, furthermore) vs. contrasting.'],
      ['adversative_ratio','Adversative Ratio','How often the writer pushes back with but, however or on the other hand.'],
      ['causal_ratio','Causal Ratio','How often cause and effect is explained: because, therefore, as a result.'],
      ['temporal_ratio','Temporal Ratio','How often events are sequenced in time: then, meanwhile, afterward.'],
      ['thematic_progression_score','Thematic Progression','How smoothly each sentence builds on the one before vs. jumping around.'],
      ['pronoun_reference_density','Pronoun Reference Density','How often it, this and they refer back instead of repeating the noun.'],
      ['lexical_chain_density','Lexical Chain Density','How tightly word choices link back to earlier related words.'],
      ['paragraph_topic_position','Paragraph Topic Position','Where the main point is planted: up front, in the middle, or at the end.'],
      ['avg_paragraph_length','Average Paragraph Length','How many sentences are packed into a paragraph before a new one starts.'],
      ['sentence_opener_variety','Sentence Opener Variety','How much sentence openings are mixed up compared with starting them alike.'],
      ['cohesion_device_ratio','Cohesion Device Ratio','Overall connective tissue holding the writing together.'],
      ['transition_density','Transition Density','How often transition words appear between sentences specifically.'],
    ]},
    { key:'tier3', pill:'Tier 3', name:'Rhetorical Register', status:'active', c:'#5aab7a',
      blurb:'the voice taken with a reader: certain, formal, persuasive', features:[
      ['epistemic_certainty_ratio','Epistemic Certainty','How confidently things are stated: "this is true" vs. "this may be true."'],
      ['hedging_density','Hedging Density','How often claims are softened with perhaps, it seems or somewhat.'],
      ['assertion_density','Assertion Density','How often flat, confident statements of fact are made.'],
      ['source_integration_style','Source Integration Style','How a quote is woven in: dropped in bluntly, or built around smoothly.'],
      ['counter_argument_ratio','Counter-Argument Ratio','How often an opposing view is raised before it is answered.'],
      ['claim_density','Claim Density','How many distinct arguable points are packed in.'],
      ['question_ratio','Question Ratio','How often a question is asked instead of just stating something.'],
      ['imperative_density','Imperative Density','How often direct commands appear: "consider this," "note that."'],
      ['first_person_ratio','First-Person Ratio','How often I or we is used compared with staying impersonal.'],
      ['appeal_to_authority_density','Appeal to Authority Density','How often a claim is backed with an expert: "as Aquinas argued."'],
      ['conclusion_strategy_score','Conclusion Strategy','How the writing wraps up: summarising, restating the thesis, ending on a quote.'],
      ['theological_register_score','Theological Register','How much specialised theological vocabulary appears.'],
    ]},
    { key:'tier4', pill:'Tier 4', name:'Char & Punctuation', status:'active', c:'#c88a3a',
      blurb:'tiny punctuation & letter habits below conscious control', features:[
      ['char_trigram_entropy','Character Trigram Entropy','How predictable the three-letter-chunk patterns are: nearly unconscious.'],
      ['punctuation_diversity','Punctuation Diversity','How many different punctuation marks are actually used.'],
      ['comma_rate','Comma Rate','How often a comma appears per stretch of words.'],
      ['semicolon_colon_rate','Semicolon/Colon Rate','How often semicolons and colons appear: some writers never touch them.'],
      ['parenthetical_rate','Parenthetical Rate','How often a side note is tucked in (like this) using parentheses.'],
      ['dash_rate','Dash Rate','How often dashes (like this) interrupt or extend a sentence.'],
      ['quote_rate','Quote Rate','How often quotation marks appear, for citing or emphasis.'],
    ]},
    { key:'tier5', pill:'Tier 5', name:'POS & Syntax', status:'active', c:'#4db0c8',
      blurb:'the grammatical skeleton under the sentences', features:[
      ['pos_bigram_entropy','POS Bigram Entropy','How predictable the two-word grammar patterns are.'],
      ['pos_trigram_entropy','POS Trigram Entropy','Same idea, one layer deeper: three-word grammar patterns.'],
      ['noun_verb_ratio','Noun-to-Verb Ratio','Whether the writing leans on naming things (nouns) or describing action (verbs).'],
      ['adjective_rate','Adjective Rate','How often nouns are decorated with descriptive words.'],
      ['adverb_rate','Adverb Rate','How often verbs are modified with words like quickly or clearly.'],
      ['subordination_ratio','Subordination Ratio','How often dependent clauses are built compared with simple standalone sentences.'],
      ['clause_depth_mean','Average Clause Depth','How deeply nested the sentences get.'],
    ]},
    { key:'tier6', pill:'Tier 6', name:'Idiosyncratic Patterns', status:'active', c:'#c85a9a',
      blurb:'personal quirks below the level of any taught rule', features:[
      ['contraction_rate','Contraction Rate','How often don\'t is written instead of do not.'],
      ['sentence_initial_conjunction_rate','Sentence-Initial Conjunction Rate','How often a sentence starts with And, But or So.'],
      ['that_which_ratio','"That" vs. "Which" Ratio','The preference between these two when introducing a clause.'],
      ['citation_style_consistency','Citation Style Consistency','How consistently citations are formatted the same way each time.'],
      ['list_marker_preference','List Marker Preference','Whether numbers, letters or bullets are used when listing.'],
      ['abbreviation_tendency','Abbreviation Tendency','How often words are shortened (e.g., etc.) compared with written out.'],
    ]},
    { key:'tier7', pill:'Tier 7', name:'Natural Unevenness', status:'active', c:'#4d6fc8',
      blurb:'how evenly words, repetitions and transitions spread through the writing', features:[
      ['burstiness','Burstiness','How much sentence length and complexity vary, burst to burst.'],
      ['perplexity_proxy','Perplexity Proxy','How predictable the word choices are from one word to the next.'],
      ['repetition_gap_entropy','Repetition Gap Entropy','How evenly spaced the word repetitions are across the paper.'],
      ['transition_predictability','Transition Predictability','Whether idea-to-idea transitions follow a formulaic pattern.'],
      ['vocabulary_introduction_rate','Vocabulary Introduction Rate','How quickly new words are introduced compared with recycling the same ones.'],
      ['filler_hedge_cluster_rate','Filler/Hedge Clustering','Whether hedge words bunch together rather than spreading naturally.'],
    ]},
    { key:'tier8', pill:'Tier 8', name:'Prosodic Rhythm', status:'active', c:'#7aab2a',
      blurb:'the musical rhythm of the sentences read aloud', features:[
      ['stress_entropy_unigram','Stress Entropy (single syllables)','How varied the stressed/unstressed pattern is, syllable by syllable.'],
      ['stress_entropy_bigram','Stress Entropy (syllable pairs)','Same idea for pairs of syllables: a bigger rhythmic pattern.'],
      ['clausulae_consistency','Clausulae Consistency','How consistent the rhythm is at the end of the sentences.'],
      ['breath_group_variance','Breath-Group Variance','How much the length of natural breath pauses varies through the paper.'],
    ]},
    { key:'tier9', pill:'Tier 9', name:'Cognitive Sequencing', status:'active', c:'#a06a3a',
      blurb:'the shape of how an argument is built, point by point', features:[
      ['structural_centrist_penalty','Structural Centrist Penalty','How closely the essay follows an even point, counterpoint, conclusion pattern.'],
      ['argument_sequence_likelihood','Argument Sequence Likelihood','Compares the order points are introduced and resolved against the baseline.'],
    ]},
    { key:'tier10', pill:'Tier 10', name:'Semantic Gravity', status:'active', c:'#4a9b9b',
      blurb:'whether ideas stay focused or wander', features:[
      ['semantic_field_dispersion','Semantic Field Dispersion','How spread out or tightly clustered the core concepts are.'],
      ['semantic_centroid_proximity','Semantic Centroid Proximity','How close this paper\'s topic sits to the writer\'s usual centre of gravity.'],
    ]},
    { key:'tier11', pill:'Tier 11', name:'Error Ecology', status:'active', c:'#c85a5a',
      blurb:'the mistakes made, and whether they match the usual ones', features:[
      ['error_kl_divergence','Error Profile Divergence','Compares this paper\'s slip pattern to the writer\'s typical error pattern.'],
      ['stumble_rate_consistency','Stumble-Rate Consistency','Whether the overall error rate matches what\'s typical for the writer.'],
      ['punctuation_error_ratio','Punctuation Error Ratio','Whether punctuation mistakes happen at the usual rate.'],
    ]},
    { key:'tier12', pill:'Tier 12', name:'Tension Arc', status:'active', c:'#c8802a',
      blurb:'the emotional/dramatic shape of the essay start to finish', features:[
      ['catastrophe_index','Catastrophe Index','How spiky the essay\'s tension is from start to finish.'],
    ]},
    { key:'tier13', pill:'Tier 13', name:'Prosodic Depth', status:'active', c:'#5aab7a',
      blurb:'a deeper layer of sentence music & whether structure resolves', features:[
      ['clausula_type_consistency','Clausula Type Consistency','How consistently the sentences land on the same rhythmic ending.'],
      ['breath_group_regularity','Breath-Group Regularity','How evenly paced the breath pauses are.'],
      ['vowel_sonority_ratio','Vowel Sonority Ratio','The balance of open, resonant vowels vs. closed, clipped ones.'],
      ['arc_resolution_score','Arc Resolution Score','Whether the essay\'s tension actually resolves by the end, or just stops.'],
      ['metric_flatness_score','Metric Flatness Score','How uniform the rhythm is from paragraph to paragraph.'],
      ['clausula_shape_preference','Clausula Shape Preference','The preferred way for a sentence\'s rhythm to fall at the end.'],
    ]},
    { key:'tier14', pill:'Tier 14', name:'Error Topology', status:'active', c:'#c8955a',
      blurb:'where and how the mistakes show up, not just how many', features:[
      ['error_topology_consistency','Error Topology Consistency','Whether mistakes like comma splices show up in the same places each time.'],
      ['article_omission_rate','Article Omission Rate','How often a, an or the is left out where it would normally go.'],
      ['pronoun_ambiguity_rate','Pronoun Ambiguity Rate','How often it or this is unclear about what it refers to.'],
      ['comma_splice_rate','Comma Splice Rate','How often two full sentences are joined with just a comma.'],
    ]},
    { key:'tier15', pill:'Tier 15', name:'Lexical Architecture', status:'active', c:'#8a7ad0',
      blurb:'the shape of the vocabulary: where words come from & how arranged', features:[
      ['semantic_field_concentration','Semantic Field Concentration','How tightly clustered in meaning the most-used nouns are.'],
      ['polysyndeton_ratio','Polysyndeton Ratio','Whether items are strung with repeated "and"s instead of commas.'],
      ['chiasmus_rate','Chiasmus Rate','How often a mirrored A-B-B-A structure is used for effect.'],
      ['latinate_ratio','Latinate Ratio','How many words come from Latin roots (utilize) vs. plain (use).'],
      ['nominalization_density','Nominalization Density','How often actions are turned into nouns: "we discussed" → "a discussion."'],
    ]},
    { key:'tier16', pill:'Tier 16', name:'Citation Fingerprint', status:'active', c:'#4d90c8',
      blurb:'personal habits in how sources are used and cited', features:[
      ['signal_verb_entropy','Signal Verb Entropy','How varied the signal verbs are (argues, claims, notes) vs. always one.'],
      ['signal_verb_assertiveness','Signal Verb Assertiveness','How forcefully the signal verbs frame a claim: "asserts" vs. "suggests."'],
      ['source_loyalty_index','Source Loyalty Index','How often the same authors are returned to vs. citing many.'],
      ['block_quote_rate','Block-Quote Rate','How much is long indented quotation vs. the writer\'s own paraphrase.'],
      ['citation_density_cv','Citation Density Consistency','Whether citations spread evenly or clump in certain paragraphs.'],
      ['ibid_usage_rate','"Ibid." Usage Rate','How often ibid. or op. cit. shorthand is used.'],
      ['citation_position_pref','Citation Position Preference','Whether citations are placed at the start, middle or end of a sentence.'],
      ['paraphrase_density','Paraphrase Density','How often a source is restated in the writer\'s own words vs. quoting.'],
    ]},
    { key:'tiercomp', pill:'Comparison', name:'Comparison', status:'active', c:'#8a8a8a',
      blurb:'computed only against the baseline, not stored on their own', features:[
      ['char_trigram_profile_divergence','Character Trigram Divergence','How far this paper\'s letter-pattern habits drift from the baseline.'],
      ['function_word_profile_divergence','Function Word Divergence','How far the glue-word habits drift from the baseline.'],
    ]},
  ];

  const flat = [], byCode = Object.create(null);
  TIERS.forEach(tier => {
    tier.features = tier.features.map(([code, name, desc]) => {
      const obj = { code, name, desc, tier: tier.key, tierName: tier.name, c: tier.c };
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
