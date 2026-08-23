# Production runtime probe contract

The foundation-owned publisher writes the currently rendered production state to
the app-private path `files/icp-runtime-probes.json`. It must write atomically after
layout and again after every state or scroll change. Capture deletes any previous
file before cold start, so copied or stale payloads cannot satisfy the gate.

The JSON root contains exactly these fields:

```json
{
  "schema": "icp.runtime-probes.v1",
  "visual_state_id": "<frozen visual state id>",
  "root_tag": "<production renderer root tag>",
  "coordinate_space": {"unit": "dp", "origin": "viewport"},
  "viewport_bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
  "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 24},
  "system_bars": {
    "status": {"visible": false, "bounds": null},
    "navigation": {
      "visible": true,
      "bounds": {"left": 0, "top": 776, "width": 360, "height": 24}
    }
  },
  "scroll_metrics": [],
  "components": [],
  "probes": []
}
```

Each `components` item is one frozen component instance occurrence:

```json
{
  "instance_id": "<component instance id>",
  "occurrence_id": "<unique live semantics tag>",
  "parent_instance_id": null,
  "slot": "root",
  "order": 0,
  "bounds": {"left": 0, "top": 0, "width": 360, "height": 800}
}
```

`parent_instance_id`, `slot`, and `order` must equal the frozen component tree.
Every occurrence tag must be attached to the corresponding production UI node.
For lazy content the driver scrolls the real container until each occurrence has
been observed; offscreen content need not be mounted in the first hierarchy dump.

`scroll_metrics` is retained as a payload slot but is not completion evidence;
publish `[]`. ICP derives the scroll axes and required descendants from the frozen
layout contract, performs real device swipes until the hierarchy stops changing,
observes every required occurrence, and restores the initial hierarchy. App-owned
viewport/content extents and offsets cannot satisfy or shorten that scan.

Each `probes` item contains a unique `probe_tag` plus the live-node fields needed
to anchor it, such as `bounds` and `color`. Bounds use the same viewport-space dp
rectangle shape and colors use the frozen normalized representation. Do not use
app-published `font_size` or `line_height` as evidence. ICP reads each frozen
typography `dimen` directly from the current clean-build APK and requires the
mapped production source to consume that exact `R.dimen` resource.

Only elements frozen with the `live_node` evidence channel publish a probe. An
`asset_internal` element must not create an audit-only UI node: its frozen owner
provides the live bounds, the exported asset is verified byte-for-byte, and the
real screenshot remains the visual observation. On Android, each live tag is an
exact accessibility/resource-id token; never concatenate multiple identities into
one `testTag` string. One live accessibility node may own only one obligation probe;
putting several probe tokens in one `content-desc` is invalid even when every token
is individually unique.

The app payload is not the authority for opaque color or window chrome. After the
hierarchy anchors a color probe's bounds, ICP requires that color to occur in the
real captured pixels and records the observed pixel coordinate plus RGBA value.
The payload's color value cannot make this check pass or fail. For every production capture the driver also reads the
current Android display size and `dumpsys window insets`; app-published
`safe_insets` and `system_bars` must equal that device observation.

Do not publish verdicts such as `no_clip`, `operable`, `no_overlap`,
`content_reachable`, or `system_bars_correct`. The ICP driver and layout verifier
derive those results from the measurements, live UI hierarchy, real screenshots,
device configuration, and scroll path.
