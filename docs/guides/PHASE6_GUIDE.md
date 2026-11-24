# Phase 6: measuring how well the tool works

## For the submission: one command
```powershell
cd D:\Claude_comparison_project1\skincare-compare
.\.venv\Scripts\Activate.ps1
python -m scripts.final_check
```
About 10 minutes. It runs every automatic test (all 12 product types, every concern, barcode, name, paste
and photo, ties, close calls, cautions, AI failures, banned words, the disclaimer), checks the live
connections, measures photo reading on your shampoo and conditioner photos, barcode coverage on the
barcodes you've used, and consistency and made-up claims against a plain AI chatbot. It ends with
**RESULT: PASS** or **RESULT: FAIL** and writes `eval_results\RESULTS.md` for your write-up.
`python -m scripts.final_check --quick` does only the tests and connection checks (about 2 minutes).

User testing is marked "not done (out of scope for this submission)" in the sheet. Everything below is
for running a measure on its own, or with more data later.

Five measures, one results sheet. Everything you fill in goes in `eval_inputs\`, every result in
`eval_results\`. Updates never touch either folder.

Open PowerShell in the project folder first:
```powershell
cd D:\Claude_comparison_project1\skincare-compare
.\.venv\Scripts\Activate.ps1
```

## 0. Set up (once)
```powershell
python -m scripts.eval.setup
```
This makes `eval_inputs\` with starter files.

## 1. Reading label photos (30 photos)
For each product, put the label photo in `eval_inputs\photos\` and type the real ingredient list from the
pack into a `.txt` file with the same name (`serum1.jpg` + `serum1.txt`). Then:
```powershell
python -m scripts.eval.extraction
python -m scripts.eval.extraction --offline     # optional: the without-AI reader on its own
```
You get: % of ingredients read exactly right, small slips, missed ones, and **invented** ones (not on the pack).

## 2. Barcode coverage (5 or more per product type)
`eval_inputs\coverage.csv` already has the barcodes you've used before. Add more in the empty rows (product
type, barcode, name), then:
```powershell
python -m scripts.eval.coverage
```
You get: how many barcodes come with an ingredient list in Open Beauty Facts, per type.

## 3. Consistency: our tool vs a plain chatbot (10 comparisons x 3 runs)
`eval_inputs\comparisons.json` has 10 starter comparisons. Keep them or swap in real products. Then:
```powershell
python -m scripts.eval.consistency --limit 1    # quick try first
python -m scripts.eval.consistency
```
Each comparison runs 3 times in the tool, and 3 times as a plain question to the same AI. It takes about
5 to 10 minutes because it waits between AI calls to stay inside the free limits.

## 4. Made-up claims (uses the answers from step 3)
```powershell
python -m scripts.eval.hallucination
```
This counts ingredients mentioned that the products don't contain, plus words like good, best, cure or treat,
for both sides. It also adds any invented photo ingredients from step 1. Skim
`eval_results\consistency_raw.json` too, because a person spots things a word check can't.
**Phase 6 rule:** anything found on our tool's side must be fixed. Send it to me.

## 5. User test (5 to 8 people)
Follow `USER_TEST_SCRIPT.md`, fill `eval_inputs\user_test.csv`, then:
```powershell
python -m scripts.eval.user_test
```

## The results sheet
```powershell
python -m scripts.eval.results
notepad eval_results\RESULTS.md
```
Run it any time. It shows every measure done so far and lists what's still to do. Phase 6 is complete when
"Still to do" says nothing.

## Privacy
Only label photos and ingredient lists go to the AI services, the same as in the app. Use P1, P2... for
people in the user test, never their names.
