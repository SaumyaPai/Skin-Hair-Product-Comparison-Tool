# User test script (Phase 6, measure 5)

For 5 to 8 people, one at a time, about 15 minutes each. You only watch and write; don't help unless
they're completely stuck (and write down where).

## Before
1. Start the app on your laptop: `python -m scripts.run_app`
2. Have 2 to 4 real products of the same type ready (theirs or yours), or the barcodes.
3. Open `eval_inputs/user_test.csv` to fill in. Use P1, P2... never real names.

## Say this
> "This is a tool that compares skincare or haircare products by their ingredients. I'm testing the tool,
> not you. Please think out loud. It doesn't give medical advice."

## Tasks
1. **Comparison 1:** "Compare these products for a concern you have." (They choose the type, concern and products.)
2. **Comparison 2:** "Now add one product by taking a photo of its label."

Write `y` or `n` in `comparison_1_done` and `comparison_2_done`.

## The 5 questions (ask after both tasks, write the answers in the sheet)
1. **How clear was the result, from 1 (very confusing) to 5 (very clear)?** -> `q1_clear_1to5`
2. **How much would you trust it when choosing a product, from 1 to 5?** -> `q2_trust_1to5`
3. **Did you notice where the information comes from (the source links)?** yes/no -> `q3_noticed_sources_yes_no`
4. **Did any of it feel like medical advice?** yes/no -> `q4_felt_like_medical_advice_yes_no`
5. **What, if anything, confused you?** -> `q5_what_confused_you`

If they say something memorable, copy it word for word into `quote`.

## After everyone
`python -m scripts.eval.user_test` then `python -m scripts.eval.results`
