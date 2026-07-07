## Generated API client

`npm run gen:client` runs `openapi-typescript` against the running backend's
`/openapi.json` and writes `schema.d.ts` here.

Per WS-8 R0's entry gate, this should only be trusted once WS-7 step 2 lands
pydantic `response_model`s on the remaining dict-body endpoints — until then,
some endpoints will generate as loosely-typed (`any`/`unknown`) rather than
their real shape. Re-run after WS-7 step 2 merges and diff the output.
