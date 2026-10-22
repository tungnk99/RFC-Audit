---
name: translate-rfc-sentence-to-rbs
description: A procedure for turning normative RFC sentences into requirement behavior specs (RBS) faithfully - deciding whether a sentence is testable, splitting sentences that carry several requirements, classifying into types A to D, extracting the quantity, threshold and reaction, and choosing variants. Use whenever an RFC sentence must be translated into RBS.
metadata:
  version: "1"
---

# Translate an RFC sentence into RBS

The RBS you write is compiled into the oracle that judges every test run. A faithful RBS of a narrow requirement is worth far more
than an ambitious RBS that says something the sentence does not.

## 1. Is it testable?

Mark `non_behavioral = true` when the sentence:
- defines terms or structures without demanding behaviour ("The length field contains...");
- gives rationale or advice to designers, or applies to specification authors rather than implementations;
- uses a lowercase "must" or "should" outside a normative context, or only restates another sentence;
- demands behaviour that no observation or static query can reach in this adapter (say so; do not force a type D).

## 2. One sentence, how many requirements?

Look for conjunctions of obligations: "X MUST NOT exceed L. An endpoint that receives ... MUST terminate with E" is a limit plus
a reaction, and the RBS for the receiving side carries both (`where` for the limit, `expect` for the reaction). Two independent
obligations on different actors or triggers are two RBS. A "MUST ... unless ..." carries an exception: encode it as
`accept_alternatives` when the RFC permits another reaction, or as a narrower `where`.

## 3. Classify

| Type | The sentence constrains | Signals |
|---|---|---|
| A | data the implementation SENDS | "MUST set", "MUST include", "the value MUST be" about outgoing fields |
| B | the reaction to RECEIVING invalid or unexpected data | "upon receipt of", "receiver MUST reject/abort/ignore/respond with" |
| C | ordering and state | "before", "after", "only once", "in state", "MUST NOT send X until" |
| D | internal behaviour invisible on the wire | "MUST erase", "MUST NOT reuse", "MUST verify" with no externally visible effect |

## 4. Extract the parts

- `actor`: who must behave (client, server, endpoint, resolver, receiver); taken from the sentence.
- `state`: the lowest precondition in which the trigger makes sense, from the adapter vocabulary.
- `trigger` and `where`: the event and the condition on one field, with the exact number. Compute expressions ("2^14 + 256" is
  16640). "MUST NOT exceed L" violates at `> L`; "at least L" violates at `< L`.
- `expect`: the required reaction in order (error, then close), with `within` when the RFC or adapter gives a time bound.
- `forbid`: what must not happen after the trigger (keep processing, send application data).
- Field and event names come from the adapter vocabulary; look up the RFC definition (`rfc__get_definition`) to be sure which
  structure the field belongs to.

## 5. Variants

Always include the value just on the violating side (`boundary`), the extreme of the field's domain (`max` or `min`), random samples
on the violating side (`random`, stratified when the range is wide), and random samples on the valid side (`valid_random`). The
oracle adds the control value at the limit, which must be accepted.

## 6. Check before returning

Read the sentence and your RBS side by side. Every element of the RBS must be traceable to the sentence or its context; nothing in
the sentence that constrains behaviour may be dropped silently. If the vocabulary lacks a needed name, say so instead of inventing one.

Protocol knowledge (field names, typical structures, which reactions the protocol defines) comes from the adapter's protocol skill
when one is offered.
