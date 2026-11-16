# Prompt sheet: scholarly-ai-mirror-2026-11-16

Paste each prompt into a fresh chat in the named tool, exactly as written. For each one:

1. Create the folder `validation/scholarly/ai_mirror/raw/` if it does not exist yet.
2. Save the complete first reply as plain text to the path shown under its prompt (`raw/<author_id>.txt`).
3. Run `.venv/bin/python -m validation.scholarly.ai_mirror intake --author <author_id> --model "<model>" --date YYYY-MM-DD --route app` (`--route subagent` for the subagent route).
4. Only if intake reports under 1,300 cleaned words, send this follow-up once, in the same chat:

```
Please continue the article from where it stopped, in the same style, for about 600 more words.
```

   Save that second reply on its own to `raw/<author_id>.cont.txt` (never added to the first file), then run the same intake command again with `--continued`.

## 1. claude

```
Write an original scholarly journal article of about 1,600 words titled "The Role That Persecutions Against Christians Play in Creating Early Christian Identity", suitable for publication in SingiLogos. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5022809732.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5022809732.cont.txt`

## 2. chatgpt

```
Write an original scholarly journal article of about 1,600 words titled "Catechesis in Italy between the Two Vatican Councils – 1870–1962", suitable for publication in The Person and the Challenges The Journal of Theology Education Canon Law and So. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5057591164.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5057591164.cont.txt`

## 3. gemini

```
Write an original scholarly journal article of about 1,600 words titled "Roman glass bowls from Intercisa", suitable for publication in Repository of the Academy's Library (Library of the Hungarian Academy of Science. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5047115320.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5047115320.cont.txt`

## 4. claude

```
Write an original scholarly journal article of about 1,600 words titled "On social justice: Comparing Paul with Plato, Aristotle and the Stoics", suitable for publication in HTS Teologiese Studies / Theological Studies. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5076341968.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5076341968.cont.txt`

## 5. chatgpt

```
Write an original scholarly journal article of about 1,600 words titled "John Wesley and Methodist Responses to Slavery in America", suitable for publication in Holiness. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5056187576.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5056187576.cont.txt`

## 6. gemini

```
Write an original scholarly journal article of about 1,600 words titled "The sale of Joseph in Genesis 37 and contemporary human trafficking", suitable for publication in Stellenbosch Theological Journal. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5107831469.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5107831469.cont.txt`

## 7. claude

```
Write an original scholarly journal article of about 1,600 words titled "Isaiah 1:2−3 and Isaiah 6: Isaiah ‘a prophet like Moses’ (Dt 18:18)", suitable for publication in HTS Teologiese Studies / Theological Studies. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5021243195.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5021243195.cont.txt`

## 8. chatgpt

```
Write an original scholarly journal article of about 1,600 words titled "A Late Bronze Age ‘Hoard’ and Metal Stray Finds from Tiszalök-Rázompuszta (Szabolcs-Szatmár-Bereg County, Hungary)", suitable for publication in Dissertationes Archaeologicae. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5067191187.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5067191187.cont.txt`

## 9. gemini

```
Write an original scholarly journal article of about 1,600 words titled "Intercultural Interpretation of Scripture: Evaluating the Approach of Jean-Claude Loba-Mkole for Interpreting the Bible in Africa", suitable for publication in Scriptura. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5081037453.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5081037453.cont.txt`

## 10. claude

```
Write an original scholarly journal article of about 1,600 words titled "A Commentary on Kant’s Introduction of the Concept of Transcendental Deduction", suitable for publication in Acta Universitatis Lodziensis Folia Iuridica. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5071222703.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5071222703.cont.txt`

## 11. chatgpt

```
Write an original scholarly journal article of about 1,600 words titled "LEFT DISLOCATION IN ARABIC: THE COMPLEXITY OF FORM AND MEANING", suitable for publication in Stellenbosch Papers in Linguistics Plus. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5025732228.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5025732228.cont.txt`

## 12. gemini

```
Write an original scholarly journal article of about 1,600 words titled "Light Symbolism in Gentile da Fabriano’s Vatican Annunciation", suitable for publication in Eikon / Imago. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5030272032.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5030272032.cont.txt`

## 13. claude

```
Write an original scholarly journal article of about 1,600 words titled "Enhancing Sentiment Analysis and Error Prediction in Lawyer Questioning Through Legal NLP Models: A Mixed-Methods Study in Australian Courtrooms", suitable for publication in UNSWorks (University of New South Wales, Sydney, Australia). Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5073091672.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5073091672.cont.txt`

## 14. chatgpt

```
Write an original scholarly journal article of about 1,600 words titled "The Deuteronomic roots of postexilic prophetic eschatology in Malachi", suitable for publication in In die Skriflig/In Luce Verbi. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5046447025.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5046447025.cont.txt`

## 15. gemini

```
Write an original scholarly journal article of about 1,600 words titled "THE MYTH OF THESEUS IN PLATO’S PHAEDO", suitable for publication in Akroterion. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5088905867.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5088905867.cont.txt`

## 16. claude

```
Write an original scholarly journal article of about 1,600 words titled "Without a voice, with a violated body: Re-reading Judges 19 to challenge gender violence in sacred texts", suitable for publication in Missionalia. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5084995476.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5084995476.cont.txt`

## 17. chatgpt

```
Write an original scholarly journal article of about 1,600 words titled "ancient catechumenate", suitable for publication in Stellenbosch Theological Journal. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5051780975.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5051780975.cont.txt`

## 18. gemini

```
Write an original scholarly journal article of about 1,600 words titled "An irresistible beauty in 1 Peter", suitable for publication in Verbum et Ecclesia. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5007243992.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5007243992.cont.txt`

## 19. claude

```
Write an original scholarly journal article of about 1,600 words titled "Ritual Worship of the Narasiṁhamantra as Depicted in the "Sātvatasaṁhitā"", suitable for publication in Cracow Indological Studies. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5057064147.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5057064147.cont.txt`

## 20. chatgpt

```
Write an original scholarly journal article of about 1,600 words titled "Rhetorical Syncrisis in the Johannine Presentation of Jesus and Peter", suitable for publication in The Biblical Annals. Write continuous academic prose in paragraphs. Do not use headings, bullet points, numbered lists, tables, footnotes or a reference list.
```

Save to: `validation/scholarly/ai_mirror/raw/A5038442133.txt`

Continuation, only if intake asks for it: `validation/scholarly/ai_mirror/raw/A5038442133.cont.txt`
