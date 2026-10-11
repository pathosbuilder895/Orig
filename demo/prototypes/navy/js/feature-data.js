/* feature-data.js: the 97 active Original features (Tiers 1-16 plus the
   baseline-comparison pair) as plain-English cards for the navy demo.
   Codes, tier membership and tier names match original/constants.py and
   demo/prototypes/feature-registry.generated.js (tests pin this). Tier 17
   (behavioural) and Tier 18 (uniformity) are disabled in the product and are
   not shown. Every baseline/submission value below is FICTIONAL.

   window.OriginalFeatures = {
     tiers:      [ {key,pill,name,status,c,blurb,features:[{code,name,desc,base,sub,flagged,tier}]} ],
     flat:       [ ...all 97 feature objects in tier order ],
     byCode:     { code: featureObj },
     tierAvg(key): mean baseline amplitude for a tier,
     FLAGS:      Set of flagged codes,
   } */
(function () {
  const TIERS = [
    { key:'tier1', pill:'Tier 1', name:'Surface Stylometrics', status:'active', c:'#4d90c8',
      blurb:'word & sentence choices so automatic you don\'t notice making them', features:[
      ['type_token_ratio','Type–Token Ratio','How many different words you use vs. your total word count.'],
      ['hapax_legomena_rate','Hapax Legomena Rate','Share of words that appear exactly once: wide vocabularies use many one-offs.'],
      ['mean_sentence_length','Mean Sentence Length','Average words per sentence: short and punchy, or long and winding.'],
      ['sentence_length_variance','Sentence Length Variance','How much your sentence lengths bounce around vs. staying even.'],
      ['function_word_ratio','Function Word Ratio','Share of glue words (the, of, and, but), used without thinking about it.'],
      ['passive_voice_ratio','Passive Voice Ratio','How often you write "the ball was thrown" vs. "she threw the ball."'],
      ['modal_verb_ratio','Modal Verb Ratio','How often you use should, might, could, must: signalling how sure you are.'],
      ['stop_word_ratio','Stop Word Ratio','Share of common connector words (a, is, at) that carry little meaning alone.'],
      ['avg_word_length','Average Word Length','How long your words tend to be: "utilize" writes differently than "use."'],
    ]},
    { key:'tier2', pill:'Tier 2', name:'Discourse Analysis', status:'active', c:'#9a7ad0',
      blurb:'how you connect one idea to the next', features:[
      ['discourse_marker_density','Discourse Marker Density','How often you use linking phrases like however, therefore, in addition.'],
      ['additive_ratio','Additive Ratio','Connecting ideas by adding on (and, also, furthermore) vs. contrasting.'],
      ['adversative_ratio','Adversative Ratio','How often you push back with but, however, on the other hand.'],
      ['causal_ratio','Causal Ratio','How often you explain cause and effect: because, therefore, as a result.'],
      ['temporal_ratio','Temporal Ratio','How often you sequence in time: then, meanwhile, afterward.'],
      ['thematic_progression_score','Thematic Progression','How smoothly each sentence builds on the one before vs. jumping around.'],
      ['pronoun_reference_density','Pronoun Reference Density','How often you use it, this, they to refer back instead of repeating the noun.'],
      ['lexical_chain_density','Lexical Chain Density','How tightly word choices link back to earlier related words.'],
      ['paragraph_topic_position','Paragraph Topic Position','Where you plant your main point: up front, middle, or the end.'],
      ['avg_paragraph_length','Average Paragraph Length','How many sentences you pack into a paragraph before a new one.'],
      ['sentence_opener_variety','Sentence Opener Variety','How much you mix up how sentences start vs. starting them alike.'],
      ['cohesion_device_ratio','Cohesion Device Ratio','Overall connective tissue holding your writing together.'],
      ['transition_density','Transition Density','How often transition words appear between sentences specifically.'],
    ]},
    { key:'tier3', pill:'Tier 3', name:'Rhetorical Register', status:'active', c:'#5aab7a',
      blurb:'the voice you take with a reader: certain, formal, persuasive', features:[
      ['epistemic_certainty_ratio','Epistemic Certainty','How confidently you state things: "this is true" vs. "this may be true."'],
      ['hedging_density','Hedging Density','How often you soften claims with perhaps, it seems, somewhat.'],
      ['assertion_density','Assertion Density','How often you make flat, confident statements of fact.'],
      ['source_integration_style','Source Integration Style','How you weave a quote in: dropped in bluntly, or built around smoothly.'],
      ['counter_argument_ratio','Counter-Argument Ratio','How often you raise an opposing view before responding to it.'],
      ['claim_density','Claim Density','How many distinct arguable points you pack in.'],
      ['question_ratio','Question Ratio','How often you ask a question instead of just stating something.'],
      ['imperative_density','Imperative Density','How often you give direct commands: "consider this," "note that."'],
      ['first_person_ratio','First-Person Ratio','How often you write I or we vs. staying impersonal.'],
      ['appeal_to_authority_density','Appeal to Authority Density','How often you back a claim with an expert: "as Aquinas argued."'],
      ['conclusion_strategy_score','Conclusion Strategy','How you wrap up: summarising, restating thesis, ending on a quote.'],
      ['theological_register_score','Theological Register','How much specialised theological vocabulary you use.'],
    ]},
    { key:'tier4', pill:'Tier 4', name:'Char & Punctuation', status:'active', c:'#c88a3a',
      blurb:'tiny punctuation & letter habits below conscious control', features:[
      ['char_trigram_entropy','Character Trigram Entropy','How predictable your three-letter-chunk patterns are: nearly unconscious.'],
      ['punctuation_diversity','Punctuation Diversity','How many different punctuation marks you actually use.'],
      ['comma_rate','Comma Rate','How often you reach for a comma per stretch of words.'],
      ['semicolon_colon_rate','Semicolon/Colon Rate','How often you use semicolons and colons: some writers never touch them.'],
      ['parenthetical_rate','Parenthetical Rate','How often you tuck in a side note (like this) using parentheses.'],
      ['dash_rate','Dash Rate','How often you use dashes (like this) to interrupt or extend a sentence.'],
      ['quote_rate','Quote Rate','How often you use quotation marks, for citing or emphasis.'],
    ]},
    { key:'tier5', pill:'Tier 5', name:'POS & Syntax', status:'active', c:'#4db0c8',
      blurb:'the grammatical skeleton under your sentences', features:[
      ['pos_bigram_entropy','POS Bigram Entropy','How predictable your two-word grammar patterns are.'],
      ['pos_trigram_entropy','POS Trigram Entropy','Same idea, one layer deeper: three-word grammar patterns.'],
      ['noun_verb_ratio','Noun-to-Verb Ratio','Whether you lean on naming things (nouns) or describing action (verbs).'],
      ['adjective_rate','Adjective Rate','How often you decorate nouns with descriptive words.'],
      ['adverb_rate','Adverb Rate','How often you modify verbs with words like quickly or clearly.'],
      ['subordination_ratio','Subordination Ratio','How often you build dependent clauses vs. simple standalone sentences.'],
      ['clause_depth_mean','Average Clause Depth','How deeply nested your sentences get.'],
    ]},
    { key:'tier6', pill:'Tier 6', name:'Idiosyncratic Patterns', status:'active', c:'#c85a9a',
      blurb:'personal quirks below the level of any taught rule', features:[
      ['contraction_rate','Contraction Rate','How often you write don\'t instead of do not.'],
      ['sentence_initial_conjunction_rate','Sentence-Initial Conjunction Rate','How often you start a sentence with And, But, or So.'],
      ['that_which_ratio','"That" vs. "Which" Ratio','Your preference between these two when introducing a clause.'],
      ['citation_style_consistency','Citation Style Consistency','How consistently you format citations the same way each time.'],
      ['list_marker_preference','List Marker Preference','Whether you reach for numbers, letters, or bullets when listing.'],
      ['abbreviation_tendency','Abbreviation Tendency','How often you shorten words (e.g., etc.) vs. writing them out.'],
    ]},
    { key:'tier7', pill:'Tier 7', name:'Voice Authenticity', status:'active', c:'#4d6fc8',
      blurb:'how evenly words, repetitions and transitions spread through the writing', features:[
      ['burstiness','Burstiness','How much your sentence length and complexity vary, burst to burst.'],
      ['perplexity_proxy','Perplexity Proxy','How predictable your word choices are from one word to the next.'],
      ['repetition_gap_entropy','Repetition Gap Entropy','How evenly spaced your word repetitions are across the paper.'],
      ['transition_predictability','Transition Predictability','Whether your idea-to-idea transitions follow a formulaic pattern.'],
      ['vocabulary_introduction_rate','Vocabulary Introduction Rate','How quickly you introduce new words vs. recycling the same ones.'],
      ['filler_hedge_cluster_rate','Filler/Hedge Clustering','Whether hedge words bunch together rather than spreading naturally.'],
    ]},
    { key:'tier8', pill:'Tier 8', name:'Prosodic Rhythm', status:'active', c:'#7aab2a',
      blurb:'the musical rhythm of your sentences read aloud', features:[
      ['stress_entropy_unigram','Stress Entropy (single syllables)','How varied your stressed/unstressed pattern is, syllable by syllable.'],
      ['stress_entropy_bigram','Stress Entropy (syllable pairs)','Same idea for pairs of syllables: a bigger rhythmic pattern.'],
      ['clausulae_consistency','Clausulae Consistency','How consistent the rhythm is at the end of your sentences.'],
      ['breath_group_variance','Breath-Group Variance','How much the length of natural breath pauses varies through the paper.'],
    ]},
    { key:'tier9', pill:'Tier 9', name:'Cognitive Sequencing', status:'active', c:'#a06a3a',
      blurb:'the shape of how you build an argument, point by point', features:[
      ['structural_centrist_penalty','Structural Centrist Penalty','How closely the essay follows an even point, counterpoint, conclusion pattern.'],
      ['argument_sequence_likelihood','Argument Sequence Likelihood','Compares the order you introduce/resolve points against your baseline.'],
    ]},
    { key:'tier10', pill:'Tier 10', name:'Semantic Gravity', status:'active', c:'#4a9b9b',
      blurb:'whether ideas stay focused or wander', features:[
      ['semantic_field_dispersion','Semantic Field Dispersion','How spread out or tightly clustered your core concepts are.'],
      ['semantic_centroid_proximity','Semantic Centroid Proximity','How close this paper\'s topic sits to your usual centre of gravity.'],
    ]},
    { key:'tier11', pill:'Tier 11', name:'Error Ecology', status:'active', c:'#c85a5a',
      blurb:'the mistakes you make, and whether they match your usual ones', features:[
      ['error_kl_divergence','Error Profile Divergence','Compares this paper\'s slip pattern to your typical error pattern.'],
      ['stumble_rate_consistency','Stumble-Rate Consistency','Whether your overall error rate matches what\'s typical for you.'],
      ['punctuation_error_ratio','Punctuation Error Ratio','Whether your punctuation mistakes happen at your usual rate.'],
    ]},
    { key:'tier12', pill:'Tier 12', name:'Tension Arc', status:'active', c:'#c8802a',
      blurb:'the emotional/dramatic shape of the essay start to finish', features:[
      ['catastrophe_index','Catastrophe Index','How spiky the essay\'s tension is from start to finish.'],
    ]},
    { key:'tier13', pill:'Tier 13', name:'Prosodic Depth', status:'active', c:'#5aab7a',
      blurb:'a deeper layer of sentence music & whether structure resolves', features:[
      ['clausula_type_consistency','Clausula Type Consistency','How consistently you land on the same rhythmic sentence ending.'],
      ['breath_group_regularity','Breath-Group Regularity','How evenly paced your breath pauses are.'],
      ['vowel_sonority_ratio','Vowel Sonority Ratio','The balance of open, resonant vowels vs. closed, clipped ones.'],
      ['arc_resolution_score','Arc Resolution Score','Whether the essay\'s tension actually resolves by the end, or just stops.'],
      ['metric_flatness_score','Metric Flatness Score','How uniform your rhythm is from paragraph to paragraph.'],
      ['clausula_shape_preference','Clausula Shape Preference','Your preference for how a sentence\'s rhythm falls at the end.'],
    ]},
    { key:'tier14', pill:'Tier 14', name:'Error Topology', status:'active', c:'#c8955a',
      blurb:'where and how your mistakes show up, not just how many', features:[
      ['error_topology_consistency','Error Topology Consistency','Whether mistakes like comma splices show up in the same places each time.'],
      ['article_omission_rate','Article Omission Rate','How often you leave out a, an, or the where they\'d normally go.'],
      ['pronoun_ambiguity_rate','Pronoun Ambiguity Rate','How often it/this are unclear about what they refer to.'],
      ['comma_splice_rate','Comma Splice Rate','How often you join two full sentences with just a comma.'],
    ]},
    { key:'tier15', pill:'Tier 15', name:'Lexical Architecture', status:'active', c:'#8a7ad0',
      blurb:'the shape of your vocabulary: where words come from & how arranged', features:[
      ['semantic_field_concentration','Semantic Field Concentration','How tightly clustered in meaning your most-used nouns are.'],
      ['polysyndeton_ratio','Polysyndeton Ratio','Whether you string items with repeated "and"s instead of commas.'],
      ['chiasmus_rate','Chiasmus Rate','How often you use a mirrored A-B-B-A structure for effect.'],
      ['latinate_ratio','Latinate Ratio','How many words come from Latin roots (utilize) vs. plain (use).'],
      ['nominalization_density','Nominalization Density','How often you turn actions into nouns: "we discussed" → "a discussion."'],
    ]},
    { key:'tier16', pill:'Tier 16', name:'Citation Fingerprint', status:'active', c:'#4d90c8',
      blurb:'personal habits in how you use and cite sources', features:[
      ['signal_verb_entropy','Signal Verb Entropy','How varied your signal verbs are (argues, claims, notes) vs. always one.'],
      ['signal_verb_assertiveness','Signal Verb Assertiveness','How forcefully your signal verbs frame a claim: "asserts" vs. "suggests."'],
      ['source_loyalty_index','Source Loyalty Index','How often you return to the same authors vs. citing many.'],
      ['block_quote_rate','Block-Quote Rate','How much is long indented quotation vs. your own paraphrase.'],
      ['citation_density_cv','Citation Density Consistency','Whether citations spread evenly or clump in certain paragraphs.'],
      ['ibid_usage_rate','"Ibid." Usage Rate','How often you use ibid. or op. cit. shorthand.'],
      ['citation_position_pref','Citation Position Preference','Whether you place citations at the start, middle, or end of a sentence.'],
      ['paraphrase_density','Paraphrase Density','How often you restate a source in your own words vs. quoting.'],
    ]},
    { key:'tiercomp', pill:'Comparison', name:'Comparison', status:'active', c:'#8a8a8a',
      blurb:'computed only against your baseline, not stored on their own', features:[
      ['char_trigram_profile_divergence','Character Trigram Divergence','How far this paper\'s letter-pattern habits drift from your baseline.'],
      ['function_word_profile_divergence','Function Word Divergence','How far your glue-word habits drift from your baseline.'],
    ]},
  ];

  // Curated flags for this (deviating) submission.
  const FLAGS = new Set([
    'sentence_opener_variety','cohesion_device_ratio','transition_density','discourse_marker_density',
    'hedging_density','question_ratio','first_person_ratio','char_trigram_entropy','dash_rate','adverb_rate',
    'contraction_rate','citation_style_consistency','burstiness','transition_predictability',
    'catastrophe_index','metric_flatness_score','arc_resolution_score','comma_splice_rate',
    'char_trigram_profile_divergence',
  ]);

  // Fictional amplitudes for Tiers 1-3, hand-set for this demonstration.
  // base = baseline |ψᵢ|, sub = submission |ξᵢ|. Codes must stay in tier order.
  const REAL = {
    type_token_ratio:[0.668,0.714], hapax_legomena_rate:[0.530,0.548], mean_sentence_length:[0.762,0.701],
    sentence_length_variance:[0.581,0.502], function_word_ratio:[0.461,0.438], passive_voice_ratio:[0.182,0.382],
    modal_verb_ratio:[0.284,0.000], stop_word_ratio:[0.438,0.422], avg_word_length:[0.502,0.638],
    discourse_marker_density:[0.646,0.000], additive_ratio:[0.143,0.112], adversative_ratio:[0.571,0.384],
    causal_ratio:[0.286,0.211], temporal_ratio:[0.000,0.000], thematic_progression_score:[0.512,0.430],
    pronoun_reference_density:[0.622,0.489], lexical_chain_density:[0.448,0.612], paragraph_topic_position:[0.833,1.000],
    avg_paragraph_length:[0.688,0.500], sentence_opener_variety:[0.822,0.000], cohesion_device_ratio:[0.732,0.000],
    transition_density:[0.522,0.000],
    epistemic_certainty_ratio:[0.667,0.924], hedging_density:[0.693,0.102], assertion_density:[0.828,1.000],
    source_integration_style:[0.250,0.400], counter_argument_ratio:[0.182,0.095], claim_density:[0.322,0.612],
    question_ratio:[0.182,0.000], imperative_density:[0.044,0.022], first_person_ratio:[0.714,0.000],
    appeal_to_authority_density:[0.388,0.924], conclusion_strategy_score:[0.250,0.500], theological_register_score:[0.622,0.882],
  };

  function hashCode(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}return h>>>0;}
  const clamp01 = v => Math.max(0, Math.min(1, v));

  const flat = [], byCode = {};
  TIERS.forEach(tier => {
    tier.features = tier.features.map(([code, name, desc]) => {
      let base, sub, flagged = FLAGS.has(code);
      if (REAL[code]) {                       // measured Tier 1–3 values
        base = REAL[code][0]; sub = REAL[code][1];
      } else {                                // deterministic synthesis
        const h = hashCode(code);
        base = +(0.36 + (h % 1000) / 1000 * 0.42).toFixed(3);
        if (flagged) {
          const down = base > 0.5, mag = 0.30 + ((h >> 8) % 100) / 100 * 0.22;
          sub = +clamp01(base + (down ? -mag : mag)).toFixed(3);
        } else {
          sub = +clamp01(base + ((((h >> 4) % 100) / 100 - 0.5) * 0.14)).toFixed(3);
        }
      }
      const obj = { code, name, desc, base, sub, flagged, tier: tier.key, tierName: tier.name, c: tier.c };
      flat.push(obj); byCode[code] = obj;
      return obj;
    });
  });

  function tierAvg(key) {
    const t = TIERS.find(x => x.key === key); if (!t) return 0;
    return t.features.reduce((a, f) => a + f.base, 0) / t.features.length;
  }

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
    tiers: TIERS, flat, byCode, FLAGS, tierAvg,
    total: flat.length,
    flaggedCount: flat.filter(f => f.flagged).length,
  };
})();
