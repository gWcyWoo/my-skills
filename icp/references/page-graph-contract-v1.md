# ICP page graph contract v1

Treat the interaction graph and implementation DAG as different artifacts.

The interaction graph contains directed user-navigation edges parsed from
`→「唯一页面标题」` references. Other bracketed UI text is not a page reference.
Normalize titles, reject duplicate or missing titles,
self references, and cycles before claim, and derive opaque internal page keys only
after the graph closes. Never require a document author to supply an internal key
or number. The graph may contain `navigate-only` pages that require no
implementation node.

The implementation DAG contains only actual work:

1. shared-component create/extend nodes;
2. modified leaf pages;
3. modified parent pages and navigation integration;
4. flow-level verification performed by the main ICP agent.

A parent page depends on each modified child it directly reaches. Every page
consumer depends on each shared component node it needs. Reused components and
`navigate-only` pages create evidence but no worker node. Emit one deterministic
topological order; reject missing dependencies, self dependencies, cycles, or an
order that places a dependency after its consumer.

Assign every node explicit project-relative `allowed_paths`. Paths owned by
different nodes must not overlap. Treat a trailing `/` as a directory prefix and
every other value as one exact file. Shared/navigation files have one serial owner.
Reject ancestor/descendant directory overlap before claim. A `create-local`
component has no separate worker node, so each of its declared paths must already
be owned by its single consumer page.
