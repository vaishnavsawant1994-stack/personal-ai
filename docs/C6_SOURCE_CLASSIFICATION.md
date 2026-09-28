# C6 source classification

This is not a stage freeze. Stage 8 still recorded C6 as deferred at `b17c505`. Stage 9 and Stage 10 freezes were not moved.

## Rule

The stored Knowledge class must be at least as restrictive as the source minimum. This is not a new boolean.

Rank, low to high: `public < owner < trusted-devices < private < secret < never_store`.

`sensitive` and `restricted` are the same rank as `private`. `public` is only a request. Knowledge stores `owner`, `trusted-devices`, or `private`. `secret` and `never_store` cannot be weakened into Knowledge.

A request that is more restrictive than the source is allowed. A request that is weaker is rejected and nothing is written.

## Where the minimum comes from

A connector read carries `source_classification` on the read result or its provenance. The connector ingest path copies that value into Knowledge as `source_minimum`. The caller's `access_class` does not set the minimum. Caller metadata does not set it either.

`google-` and `connector:` sources with no classification are `private`. An owner upload with no connector source has no external floor.

## Who may change it

The caller cannot lower a recorded floor. Knowledge update cannot remove it, replace it with a weaker floor, or relabel an owner document as a connector source. A later version of the same document cannot be stored below the floor already recorded. The owner upload API cannot invent a connector source; that source exists only after a connector read.

## How Knowledge validates it

Before a write, Knowledge compares the requested class with the floor. The connector bridge does this from the read and refuses before `ingest`. The store does it again from `source_minimum` or, when that is absent, from the connector-prefix floor. A downgrade raises, and the document is not written. The bridge surfaces that as `PermissionError`. The store surfaces it as `KnowledgeError`.

## Provenance

A connector ingest records `source_minimum_classification` and `effective_access_class` on the document. Those fields are written by Knowledge from the floor it enforced, not from an unverified caller label.
