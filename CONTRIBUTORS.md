# Contributors

Canon was built at the **National AI Hackathon '26** against Problem Statement PS-12, by
three people working three lanes in parallel. It is now in continued development.

Credit below is written per lane rather than per commit count, because the commit count
misreports two of the three contributions — see *A note on the commit graph*.

---

## The team

### Muhammad Ihsan Khan — architecture, backend, deployment
[@IhsanKhann](https://github.com/IhsanKhann) · 36 commits on `main`

The deterministic backbone and the rule that organises the whole system: *the layer that
can be wrong may only propose, and the layer that decides cannot call a model.* The
pack/engine split, the authority order, the three-lane gate, the evidence ledger, the
precedent memory, the five laws and the tests that enforce them, the adapters, the scorer
and the evaluation harness. Lane notes: [`docs/LANE_IHSAN_BACKEND.md`](docs/LANE_IHSAN_BACKEND.md).

### Tahreem Afridi — product design, testing, research
[@tahreem05](https://github.com/tahreem05) · 5 commits on `main`

The product itself as the analyst meets it. The Rossum-style review drawer and review
queue — which is where the hard case lives, because the interesting lane is the middle one
— the user portal, and full light/dark/system theming. Ran the testing pass that found
the pipeline stepper error and the mock-banner layout fault, and did the research that
turned PS-12 into a field vocabulary the packs could be authored against. One of the two
named people who hand-confirmed all 30 rows of the golden set, which is the only reason
any accuracy figure in the README is allowed to be reported at all.
Lane notes: [`docs/LANE_TAHREEM_FRONTEND.md`](docs/LANE_TAHREEM_FRONTEND.md).

### Ali — deployment and backend
[@investpro599-a11y](https://github.com/investpro599-a11y) · 15 commits on `alibranch`

The path from a working repository to a reachable URL, which is the half of a hackathon
that decides whether anyone sees it. Vercel build and deploy configuration, the serverless
API wrapper, co-locating backend code so the lambdas are self-contained, and the
`.vercelignore` work that got the upload under the timeout. Also the real-time side:
per-step progress over SSE and the live batch pipeline, plus a zero-cloud fail-safe
extraction path using `pdf-parse` and `xlsx` so the demo could not be taken down by a
missing cloud credential. Worked the backend alongside Ihsan throughout.
Lane notes: [`docs/LANE_ALI_INFRA.md`](docs/LANE_ALI_INFRA.md).

---

## A note on the commit graph

GitHub's contributor list counts only the **default branch**. Ali's 15 commits live on
`alibranch`, which was never merged into `main` — the two branches had diverged on
directory layout by the end of the sprint, and merging during a timed event was the wrong
risk to take. The consequence is that **GitHub shows this project as having two
contributors when it had three**, and shows Ali as having none when he has fifteen.

That is a reporting artefact, not a record of who did the work. `alibranch` is kept, not
deleted, so the work stays attributable:

```bash
git log origin/main..origin/alibranch --author=investpro599
```

The same caution applies to the other two figures. 36 against 5 is a count of commits, not
of contribution: a research pass, a testing pass and a design decision each land as one
commit or none, while a backend refactor lands as six.

---

## Copyright and licensing

Canon is licensed under the [Business Source License 1.1](LICENSE). Under that licence the
source is public and readable, non-production and evaluation use is free, and commercial
production use requires a licence from the Licensor; the whole work converts to Apache-2.0
on 2030-10-20.

Each contributor retains copyright in their own contributions. Relicensing the combined work,
or granting a commercial licence over it, therefore requires the agreement of all three
contributors named above.

Contributions after the hackathon are accepted on the understanding that they are licensed
under the same terms. If you contribute and would rather not be listed here, say so and you
will be removed.
