# Failure modes found while building Palace for Open Agent (21–26 Oct 2026)

What broke or misled us, how we found it, and what we did. "Open" means it isn't fixed in code.

## Meterless H-MEM

1. **A conformance vector can pass without the rule it tests.** In H-MEM's `ro-001` ("superseded penalty dominates"),
   the two records tie on every signal except the penalty. With the −0.20 penalty set to zero, our port still
   passed, because a stable sort kept the insertion order and the fresh record happened to be added first. Found
   by the perturbation check before merge. Fix: `tests/test_hmem_in_turn.py` adds the same case in reversed
   insertion order, which goes red without the penalty. Worth reporting upstream as an engine-spec-feedback issue.
2. **Supersession needs enrichment, not only ranking.** The spec's penalty applies only when `supersededBy` is set,
   and recall gives no such links. Palace links them in enrichment: a newer memory in the same domain and room, with
   update language ("Reversed…", "instead", "no longer") and overlapping terms, supersedes the older one. This is a
   heuristic. A reversal written without update language won't be linked. Open.

## Zetaris

3. **Database descriptions reject ordinary punctuation.** `CREATE LIGHTNING DATABASE … DESCRIBE BY "Juniper Street
   Tech Hub (fictional) …"` fails with "Description is invalid, it must be alphanumeric including the _ . - and ,
   characters". Fixed in `demo/zetaris/load_zetaris.py`.
4. **`SHOW CREATE TABLE` isn't supported** (a parser error). Use `DESCRIBE <table>` to see a table's schema.
5. **The test double isn't the engine.** The contract tests run on SQLite, and Zetaris speaks a Spark-like dialect.
   Every template is therefore also tested on our running Zetaris (`tests/test_zetaris_live.py`, 5/5). That
   includes the MM/DD/YYYY ticket dates, which are compared through `substr(...) || ...` on both engines.
6. **No bind parameters over REST.** The SQL endpoint takes a string. Template parameters are allow-listed values
   (letters, digits, spaces and `. : / ( ) -`, or ISO dates), and anything else returns an empty record set without
   a query being sent. With the allow-list removed, the injection tests fail.

## Meterless Nightshift and NVIDIA Nemotron

7. **Nemotron 3 Super 120B returns NVIDIA 404 for our account** through Nightshift's NVIDIA provider ("Function …
   Not found for account"). Llama-3.3-Nemotron-Super-49B returns 410 (end of life, 2026-08-26) but is still listed in
   `/v1/models`. Palace's `super` tier is pinned to Nemotron 3 Ultra 550B. Open (account-side).
8. **Lanes route away from what you'd expect.** With only NVIDIA configured, `meterless/fast` and `meterless/deep`
   both routed to Nemotron 3 Ultra (tier C), in 13–14 s, against 1.6 s for Ultra requested directly. Palace pins
   explicit model ids per tier, and reports the `model` each response says actually ran.
9. **A small `max_tokens` can return nothing.** Nemotron 3.5 Lightning answered 502 `empty_response` at
   `max_tokens=40`: the reasoning used up the budget. With 600 tokens it answered. The provider's cap is 1500.
10. **Reasoning leaks into the answer.** Through Nightshift, Nemotron replies sometimes start with the tail of the
    model's reasoning, ending in `</think>`. `strip_think()` removes a whole `<think>…</think>` block or a tail.
11. **`meterlessd.exe` won't start on a fresh Windows 10**: `VCRUNTIME140.dll` is missing (exit 0xC0000135).
    Installing Microsoft's `vc_redist.x64` fixes it (README, Known limitations).
12. **The status-bar request counter isn't evidence.** Nightshift's footer read `reqs 12` before and after a
    morning of Palace API calls, so we don't cite it. The per-answer compute receipt id
    (`meterless.receipt_id`) is the evidence Palace records.

## The answers

13. **Row ids cited as if they were sources.** Nemotron cited `[MTG-0805]`, a row inside a record set, instead of the
    record set `[zetaris:q-…]`. Fixed in the system prompt: cite record sets, never a row's own id. Later runs
    cited correctly.
14. **Flagging the stale note depends on the model.** Asked "Is the coordinator hire on?", Nemotron 3 Super (Token
    Factory) answered correctly from the active decision but didn't mention the stale Aug 1 note (MTG-0801).
    Nemotron 3 Ultra (Nightshift) flagged it in every run we made. Palace asks for it in the prompt but doesn't check
    it in code. Open.
15. **The keyword tier router is unchanged** (tier accuracy 0.731 on the 26-question eval). The planned Planner
    that replaces it was not built in the window, so 0.731 is still the "before".

## Our own tooling

16. **Live settings leaked into the offline tests.** With `METERLESS_BASE_URL` exported in the shell, two CLI tests
    switched to the Nightshift provider and failed. `tests/conftest.py` now clears provider settings for every
    test except the live Zetaris ones.
17. **The web panel shows the provider's host name.** That's right for a user, but a screen recording would publish
    our home network's host names. The demo video reaches Zetaris and Nightshift through SSH tunnels on 127.0.0.1.

## Found while recording the demo

18. **Zetaris login tokens expire after 15 minutes**, and an expired token gets `400 {"msg": "Bad Request"}`, not
    401. A long-running `palace serve` signed in once, and 20 minutes later every query failed. Palace said "Zetaris
    refused the query" and gave no numbers, which was correct but useless. Found while recording the demo. Fix:
    a client made by `login()` renews its token a minute before its `exp` claim, and once more if a query is still
    refused. A client made from an API token can't renew, and the error says so. Tested on the double
    (`expire_token()`) and on our running Zetaris.

## Found while making the Zetaris Demo Challenge re-cut (27 Oct)

19. **`INSERT` into a FILESTORE table needs a directory path.** On a table whose `PATH` is a single CSV file, `INSERT
    INTO … VALUES` fails with `ParentNotDirectoryException`. Recreating the table with `PATH` set to a directory that
    holds the CSV makes `INSERT` work: Zetaris writes new `part-*` files beside it. The original single-file table
    stays read-only, which is what Palace needs anyway.
20. **A date column needs a typed literal.** `INSERT … VALUES ('S029', '2026-10-24', …)` fails with
    `CANNOT_SAFELY_CAST`. `DATE '2026-10-24'` works.
21. **Dropping a table takes Zetaris's own syntax.** `DROP TABLE` and `DROP VIEW` fail, and the REST `DELETE` on a
    file-store table answers 405. `DROP LIGHTNING DATABASE TABLE <db>.<table>` works. We found it in the parser's
    grammar, not the docs.
22. **The console's History tab is per script.** Queries Palace sends over REST don't appear there, which made it look
    as if Palace had run nothing. `GET /api/proxy/sql-editor/sqls/history` lists every query, with its SQL, status
    and run time.
