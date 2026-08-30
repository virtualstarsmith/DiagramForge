# DiagramForge Spec Format

Use this reference when authoring JSON for `scripts/render_animated_diagram.py`.

## Common fields

```json
{
  "layout": "panorama | swimlane | graph | grid | sequence | er | usecase | class\n            | activity | state | dfd | deployment | component | package\n            | object | composite | profile | communication | timing | interaction\n            | c4 | gantt | bpmn | orgchart | mindmap | timeline | fishbone",
  "style": "slate | report | academic | blueprint | custom",
  "theme_file": "optional; required for style=custom — theme JSON path relative to this spec",
  "sketch": false,
  "animation": "flow | draw | relay | trace | chapter | failure-recovery",
  "title": {"prefix": "...", "highlight": "...", "subtitle": "..."},
  "signature": "optional attribution, e.g. a company name",
  "canvas": {"width": 1210, "height": 820, "fps": 20, "frames": 41},
  "density": "airy | balanced | compact",
  "aspect_ratio": "auto | landscape | portrait | square",
  "motion_level": "none | subtle | standard | cinematic"
}
```

`canvas` is optional. Valid limits are width 480-4096, height 360-4096, FPS 1-60, and frames 2-600. Layout geometry remains the source of truth unless width/height are explicitly overridden. For `graph`, width/height are diagnostic warnings and the planner uses its natural canvas to avoid clipping or dead space; use `fps` and `frames` freely. For `swimlane`/`grid`, an explicit width replans the bands/panels to fit (cards shrink), and an explicit height acts as a fill target — the natural content height is always the floor, extra space is distributed across bands.

`density`, `aspect_ratio`, and `motion_level` are reserved for forward compatibility: they validate but currently have no rendering effect.

### Formal vs sketch rendering

The default (`sketch` omitted or `false`) renders formal output: straight strokes, plate-free outline icons, sans-serif text everywhere, and no branding — nothing is stamped on the canvas unless you set `signature` yourself (e.g. a company attribution, rendered as one quiet muted line, keep it under ~28 chars).

Set `"sketch": true` (or pass `--sketch`) to switch to the legacy hand-drawn language: rough.js wobble on every stroke, Excalifont display type for Latin text, tinted icon plates behind outline glyphs, the classic `@diagramforge` brand block in the top-right corner (an explicit `signature` overrides it), and the soft light-finish glow. Illustrated/hero icons (`icon_style`) belong to this mode — pair them with `sketch: true`.

### Canvas presets

Instead of raw dimensions, name the delivery target with `canvas.preset`
(explicit `width`/`height` always win over preset values):

| Preset | Size | Use for |
| --- | --- | --- |
| `article` | 1210×1138 | portrait hero for articles (the signature look) |
| `wide` | 1600×900 | 16:9 slides / video covers |
| `square` | 1080×1080 | social feed posts |
| `story` | 1080×1350 | 4:5 portrait covers (Xiaohongshu/Instagram) |

Panorama and swimlane art is calibrated near the `article` size; other presets
re-frame the same layout, so review the PNG draft when switching presets.

Validate before rendering:

```bash
python scripts/render_animated_diagram.py --spec spec.json --outdir out --validate-only
```

## Panorama

Use for a complete system. Main fields:

- `inputs`: 2-6 objects with `label`, `icon`, optional `color`/`icon_file`.
- `core.cards`: 2-4 cards with `title`, `body`, `icon`.
- `decision`, `output`, `loop_label`, `retry_label`.
- Optional `left_panel`, `center_panel`, `right_panel` with `cards`.
- `input_style`: `boxed` or `plain`.

Example: `assets/default-spec.json`.

## Swimlane (category bands)

Use 2-8 `lanes`, each with `title` and 1-8 `steps`. Give steps stable `id` values.

- Lane fields: `title`, optional `subtitle` (small text under the title, e.g. "Triggered by: user prompt"; keep it under ~60 chars), optional `caption` (a full-width note row rendered under the step cards; keep it under ~120 chars), optional `accent` (`green`, `purple`, `amber`, `blue`, or `external`) to override the band tint. By default bands step through neutral grays by hierarchy level; lanes whose title/subtitle mentions 外部 / 第三方 / external / 3rd / third-party automatically sink to the deepest gray (the external-system convention).
- Each lane renders as a tinted band with a darker title column on the left; bands alternate sage-green / periwinkle tints automatically.
- Step fields: `id`, `title`, `icon` (plus the common icon presentation fields), optional `note` (small caption line under the card, ~40 chars).
- `connections` contain `from`, `to`, `label`, `badge`, `style`, `accent`, and use automatic orthogonal anchors. An in-lane connection that runs right-to-left (a loop back) automatically drops into a dashed channel under the cards; the lane grows to make room. `badge: "1"` draws a small numbered circle on the edge midpoint. `style: "dashed"` renders a dashed arrow like the reference diagrams.
- Canvas: explicit `canvas.width` replans the bands to fit (cards shrink); explicit `canvas.height` is a fill target — bands stretch to use it, and the natural content height is the floor (a shorter value never clips).

Example: `assets/examples/swimlane-spec.json` (the "four types of agent loops" reference diagram, `report` style). Icon-catalog variants: `assets/examples/loop-icon-pack-spec.json`, `assets/examples/illustrated-icon-catalog-spec.json` (both `sketch: true`).

## Grid (mini-flow panel catalog)

Use 2-9 `cells`, each a titled tinted panel with its own 1-6 step horizontal mini chain — the "8 RAG architectures" / "4 engineering layers" catalog format.

- Cell fields: `title`, optional `accent` (`green`, `purple`, `amber`), `steps` (same fields as swimlane steps).
- `columns`: 2 or 3 (default: 2 up to 4 cells, else 3). A short last row is centered, giving the classic 3+3+2 arrangement at 8 cells.
- Steps chain left-to-right automatically with arrows; there are no cross-cell connections.
- Canvas follows the swimlane rules (width replans, height is a fill target with the natural height as floor).

## Legend (swimlane / grid / graph)

A top-level `legend` list (up to 6 items) renders a bottom-right row of colored dots with labels inside the frame; vertical space is reserved automatically:

```json
"legend": [{"color": "green", "label": "KV reused"}, {"color": "pink", "label": "full recompute"}]
```

`color` is a THEME key (e.g. `green`, `purple`, `amber`, `pink`, `cyan`, `muted`).

## Graph (free-form workflow)

Use when no fixed template fits: declare the workflow as nodes + edges and let the engine lay it out. Every workflow gets its own loop structure instead of one hardcoded retry lane.

```json
{
  "layout": "graph",
  "direction": "right",
  "nodes": [
    {"id": "plan", "label": "Plan", "icon": "plan"},
    {"id": "act", "label": "Act", "icon": "agent", "body": "tool calls"},
    {"id": "gate", "label": "Pass?", "kind": "decision"},
    {"id": "ship", "label": "Ship", "kind": "terminal"}
  ],
  "edges": [
    {"from": "plan", "to": "act"},
    {"from": "act", "to": "gate"},
    {"from": "gate", "to": "ship", "label": "yes"},
    {"from": "gate", "to": "plan", "kind": "loop", "label": "replan"}
  ]
}
```

- `nodes`: 2-24 items. Each has a unique `id`, `label`, optional `body`, `icon` (any icon key), `kind` (`card` default, `decision` diamond, `terminal` pill, `circle`), `accent` (THEME key: `green`, `purple`, `amber`, `pink`, `cyan`, `core_stroke`, `white`, `muted`), optional `parent` (a `groups` id; members get wrapped in a dashed container box), and optional `x`/`y` (box center) to pin a node manually; omit both for auto layout. Pinned nodes must stay out of the title zone (y < 165) and the signature zone (x > 930, y < 215) — validation warns.
- `groups`: up to 4 items with `id` + `label`. Nodes declaring `parent: "<id>"` are enclosed in a dashed rounded container (one nesting level) — storage tiers, subsystems, trust boundaries.
- `edges`: up to 40 items with `from`/`to` node ids, optional `label`, `badge` (numbered circle on the edge midpoint), `accent`, `style`, and `kind`:
  - `flow` (default): forward step. Auto layout assigns layers by longest path, orders rows by barycenter, and phase-orders the beams by topological depth, so forks diverge and joins converge visibly.
  - `loop`: dashed return channel routed through its own lane below the grid (right of it when `direction: "down"`), fired after the forward wave completes. Multiple loops get separate lanes, colors, and phases. Cycles declared as plain `flow` edges are detected automatically and treated as loops.
- `direction`: `right` (default) or `down`.
- Long rightward graphs with more than 7 sequential layers auto-stack downward unless nodes have manual coordinates. This prevents clipped side content and top-heavy empty lower halves.
- Bodies show on wide cards; when many layers squeeze cards below ~150 px the card switches to icon-over-label and hides `body`.

Example: `assets/examples/graph-workflow-spec.json` (preview: `assets/previews/layout-graph.png`).

## Sequence (UML sequence diagram)

Use for time-ordered interactions between participants: lifelines, activation bars, UML arrow semantics, notes, and alt/loop/opt combined fragments.

```json
{
  "layout": "sequence",
  "participants": [
    {"id": "user", "label": "用户", "kind": "actor", "icon": "user"},
    {"id": "order", "label": "订单服务", "icon": "package"}
  ],
  "messages": [
    {"from": "user", "to": "order", "label": "提交订单", "kind": "sync"},
    {"from": "order", "to": "user", "label": "订单号", "kind": "return"}
  ],
  "fragments": [
    {"kind": "alt", "label": "库存充足", "range": [0, 1], "dividers": [{"at": 1, "label": "库存不足"}]}
  ]
}
```

- `participants`: 2-8 items, left-to-right lifeline order. Each has a unique `id`, `label`, optional `kind` (`system` default, `actor` for people — defaults the icon to `user`), `icon`, `color`, `accent` (same THEME keys as graph nodes). Heads render as icon cards on dashed lifelines.
- `messages`: 1-30 items in top-to-bottom time order. `kind`:
  - `sync` (default): solid line, filled triangle arrowhead. Opens an activation bar on the target, closed by the paired `return` (LIFO pairing).
  - `async`: solid line, open arrowhead; fire-and-forget, no activation bar unless `"activate": true`.
  - `return`: dashed line, open arrowhead; closes the sender's most recent activation.
  - `self`: right-side loop on one lifeline; only `from` is required.
  - `note`: sticky note; `target` is one participant id or `[id-a, id-b]` to span both, `text` is the note body.
  - Optional overrides on any message: `"activate": false` suppresses the auto bar, `"activate": true` forces one, `"deactivate": true` closes the sender's bar at this message.
- `fragments`: up to 6 combined fragments. `kind` is `alt`, `loop`, or `opt`; `range` is 0-based `[start, end]` indices into `messages` (endpoints must be real messages, not notes); `alt` takes `dividers` — `[{"at": index, "label": "else case"}]` marking where the next branch starts. Fragments nest up to 2 levels deep; crossing (partially overlapping) ranges are rejected.
- Returns inside an `alt` fragment skip the unpaired-return warning (only one branch runs).
- Like `graph`, the sequence planner owns the canvas: width is fixed at 1210, height grows with the message count; `canvas.width/height` trigger a diagnostic warning.

Example: `assets/examples/sequence-spec.json`. Existing Mermaid `sequenceDiagram` documents convert via `scripts/mermaid_import.py` (see below).

## ER (entity-relationship diagram)

Entity boxes with attribute rows and cardinality-labeled relations, auto-laid-out in DAG columns.

```json
{
  "layout": "er",
  "entities": [
    {"id": "user", "label": "用户", "accent": "green", "attributes": [
      {"name": "id", "type": "bigint", "key": "pk"},
      {"name": "nickname", "type": "varchar"}
    ]}
  ],
  "relations": [
    {"from": "user", "to": "order", "label": "下单", "cardinality": "1:N"}
  ]
}
```

- `entities`: 2-12 items with unique `id`, `label`, optional `accent`, and `attributes` (up to 8; each `{"name", "type"?, "key"?}` where `key` is `pk` or `fk`; a plain string also works).
- `relations`: up to 16 items with `from`/`to` entity ids, optional `label`, and `cardinality` (`1:1`, `1:N`, `N:1`, `M:N`) or explicit `from_card`/`to_card` strings (e.g. `"0..1"`, `"1..*"`). Relations that skip a layout column route through a lane above the boxes instead of crossing them.
- The planner owns the canvas, like `graph`/`sequence`.

Example: `assets/examples/er-spec.json`. Mermaid `erDiagram` import supported.

## Use case (UML use case diagram)

Actors (stick figures) on the sides, a system boundary box, use-case ellipses inside it, and association/include/extend links.

```json
{
  "layout": "usecase",
  "actors": [{"id": "buyer", "label": "买家"}, {"id": "pay", "label": "支付网关", "side": "right"}],
  "system": {"label": "电商平台"},
  "usecases": [{"id": "buy", "label": "下单"}, {"id": "pay_order", "label": "在线支付"}],
  "links": [
    {"from": "buyer", "to": "buy"},
    {"from": "buy", "to": "pay_order", "kind": "include"}
  ]
}
```

- `actors`: 1-6 items; `side` is `left` (default) or `right`.
- `usecases`: 2-16 ellipses inside the boundary (1-2 auto columns).
- `links`: up to 24. `kind`: `association` (default, solid line; actor↔usecase), `include` / `extend` (dashed open arrow with an automatic «include»/«extend» label; only valid between two use cases — actor links degrade to association with a warning). Explicit `label` overrides the stereotype text.
- Mermaid has no use-case diagram; author the spec directly.

Example: `assets/examples/usecase-spec.json`.

## Class (UML class diagram)

Compartment boxes (stereotype, name, attributes, methods) and the six UML relation kinds with correct end markers.

```json
{
  "layout": "class",
  "classes": [
    {"id": "order", "label": "Order", "attributes": [{"name": "id", "type": "Long", "visibility": "-"}],
     "methods": [{"name": "create()", "type": "void", "visibility": "+"}]},
    {"id": "repo", "label": "OrderRepository", "kind": "interface"}
  ],
  "relations": [
    {"from": "order", "to": "item", "kind": "composition", "to_card": "1..*"},
    {"from": "vip", "to": "order", "kind": "inheritance"}
  ]
}
```

- `classes`: 2-10 items. `kind`: `class` (default), `interface` / `enum` (render a «...» stereotype line), or `abstract`. `attributes` and `methods` take up to 8 members each: `{"name", "type"?, "visibility"?, "static"?}` with `visibility` one of `+ - # ~`; plain strings also work.
- `relations`: up to 16, `kind` one of:
  - `association` (solid, open arrow), `dependency` (dashed, open arrow)
  - `inheritance` (solid, hollow triangle at `to` = parent), `realization` (dashed, hollow triangle)
  - `composition` (filled diamond at `from` = whole), `aggregation` (hollow diamond at `from`)
  - Optional `label`, `from_card`/`to_card` multiplicity text.
- Editable Excalidraw export approximates hollow triangles with filled ones (Excalidraw has no hollow-triangle arrowhead).

Example: `assets/examples/class-spec.json`. Mermaid `classDiagram` import supported.

## Activity (UML activity diagram)

Action flows with start/end nodes, decisions, and fork/join concurrency bars.

```json
{
  "layout": "activity",
  "direction": "down",
  "nodes": [
    {"id": "start", "kind": "initial"},
    {"id": "check", "label": "校验订单", "kind": "action"},
    {"id": "valid", "label": "通过?", "kind": "decision"},
    {"id": "fork", "kind": "fork"},
    {"id": "end", "kind": "final"}
  ],
  "edges": [{"from": "check", "to": "valid"}, {"from": "valid", "to": "fork", "label": "是"}]
}
```

- `nodes`: 2-24. `kind`: `initial` (filled dot), `final` (ringed dot), `action` (default, rounded pill), `decision` (diamond with label inside), `fork` / `join` (filled sync bars). Terminal kinds render no label. If no `initial` is declared, one is prepended automatically.
- `edges`: up to 40 control flows; `label` is the guard on decision exits. Backward edges (loops) become dashed channels on the left.
- `direction`: `down` (default, layers stack vertically) or `right`.

Example: `assets/examples/activity-spec.json`. No Mermaid equivalent; author the spec directly (Mermaid `stateDiagram` imports via the `state` layout).

## State machine (UML state diagram)

Rounded states with optional entry/do bodies, initial/final markers, and labeled transitions.

```json
{
  "layout": "state",
  "states": [
    {"id": "start", "kind": "initial"},
    {"id": "paid", "label": "已支付", "body": "entry / 扣减库存\ndo / 触发开票"},
    {"id": "end", "kind": "final"}
  ],
  "transitions": [{"from": "paid", "to": "shipped", "label": "出库完成"}]
}
```

- `states`: 2-20. `kind`: `state` (default), `initial` (filled dot, one max), `final` (ringed dot). `body` shows entry/do lines under the name (separated by a divider); `accent` colors the box.
- `transitions`: up to 30, with `label` (event [guard] / action text). Backward transitions become dashed lanes below; self transitions loop off the right side. Forward transitions that skip a column route above the boxes.

Example: `assets/examples/state-spec.json`. Mermaid `stateDiagram` / `stateDiagram-v2` import supported.

## DFD (data flow diagram)

Gane-Sarson data flow diagrams: external rectangles, process circles with numbers, open data stores.

```json
{
  "layout": "dfd",
  "nodes": [
    {"id": "customer", "label": "顾客", "kind": "external"},
    {"id": "p1", "label": "接收订单", "kind": "process", "number": "1.0"},
    {"id": "orders", "label": "订单库", "kind": "store"}
  ],
  "flows": [{"from": "customer", "to": "p1", "label": "订单请求"}]
}
```

- `nodes`: 2-20. `kind`: `external` (rectangle, systems/people outside), `process` (default, circle with optional `number` like "1.0"), `store` (open rectangle data store).
- `flows`: up to 30 labeled data flows; backward flows become dashed lanes below.

Example: `assets/examples/dfd-spec.json`. No Mermaid equivalent; author the spec directly.

## Deployment (UML)

3D node/device/execution boxes with one level of nesting (artifacts or sub-nodes inside a host) plus communication paths.

```json
{
  "layout": "deployment",
  "nodes": [
    {"id": "ingress", "label": "Ingress Gateway", "kind": "node"},
    {"id": "pod", "label": "App Pod", "kind": "execution", "parent": "ingress"},
    {"id": "jar", "label": "app.jar", "kind": "artifact", "parent": "ingress"},
    {"id": "db", "label": "PostgreSQL", "kind": "device"}
  ],
  "connections": [{"from": "ingress", "to": "db", "label": "JDBC / TLS"}]
}
```

- `nodes`: 2-16. `kind`: `node` (default), `device`, `execution` (3D boxes with an automatic «device»/«executionEnvironment» stereotype), `artifact` (flat box). Optional `stereotype` overrides the text, `accent` recolors, `parent` nests inside another node (one level; artifacts can't be parents).
- `connections`: up to 20. `kind`: `path` (default, solid) or `dependency` (dashed open arrow); optional `label`.

Example: `assets/examples/deployment-spec.json`. No Mermaid equivalent; author the spec directly.

## Component (UML)

«component» boxes with provided (ball) / required (socket) interface lollipops and assembly/dependency/realization connectors.

```json
{
  "layout": "component",
  "components": [{"id": "order", "label": "OrderService", "body": "订单聚合"}],
  "interfaces": [{"id": "ipay", "label": "IPayment", "kind": "provided", "component": "pay"}],
  "relations": [{"from": "order", "to": "ipay", "kind": "dependency"}]
}
```

- `components`: 2-12 with `id`, `label`, optional `body` (extra rows), `stereotype` (default «component»), `accent`.
- `interfaces`: up to 12. `kind`: `provided` (ball on the right edge) or `required` (socket on the left); `component` is the owner id.
- `relations`: up to 16 between component or interface ids. `kind`: `dependency` (dashed open), `realization` (dashed triangle), `assembly` (solid ball-to-socket line).

Example: `assets/examples/component-spec.json`. No Mermaid equivalent.

## Package (UML)

Tabbed folder boxes with one level of nesting and «import»/«access»/dependency arrows.

```json
{
  "layout": "package",
  "packages": [
    {"id": "api", "label": "api"},
    {"id": "domain", "label": "domain"},
    {"id": "model", "label": "model", "parent": "domain"}
  ],
  "relations": [{"from": "api", "to": "domain", "kind": "import"}]
}
```

- `packages`: 2-14 with `id`, `label`, optional `stereotype`, `accent`, and `parent` for one-level nesting.
- `relations`: up to 16. `kind`: `import` / `access` (auto «import»/«access» label) or `dependency` (no auto label); all render dashed with an open arrow. Explicit `label` overrides.

Example: `assets/examples/package-spec.json`. No Mermaid equivalent.

## Object (UML)

Instance boxes with an underlined `name: Class` header and `attr = value` rows; plain solid links.

```json
{
  "layout": "object",
  "objects": [
    {"id": "o1", "name": "cart42", "class": "Cart", "attributes": [{"name": "total", "value": "386"}]},
    {"id": "o2", "name": "item1", "class": "CartItem"}
  ],
  "links": [{"from": "o1", "to": "o2", "label": "items"}]
}
```

- `objects`: 2-12 with `id`; `name` and `class` combine into the underlined header. `attributes`: up to 8 `{name, value}` pairs (plain strings also work).
- `links`: up to 16 solid un-arrowed links with optional `label`.

Example: `assets/examples/object-spec.json`. No Mermaid equivalent.

## Composite structure (UML)

A classifier boundary holding internal part boxes, small square ports on part edges, and connectors between parts/ports.

```json
{
  "layout": "composite",
  "classifier": "SearchEngine",
  "parts": [{"id": "crawler", "label": "crawler", "type": "Crawler"}],
  "ports": [{"id": "p1", "part": "crawler", "side": "right", "label": "pages"}],
  "connectors": [{"from": "p1", "to": "indexer"}]
}
```

- `parts`: 2-10 with `id`, `label`, optional `type` (rendered as `label: type`), `accent`.
- `ports`: up to 12 with `id`, `part` (owner id), `side` (`left`/`right`/`top`/`bottom`), optional `label`.
- `connectors`: up to 16 solid lines between part or port ids, optional `label`. `classifier` labels the dashed boundary (top-right).

Example: `assets/examples/composite-spec.json`. No Mermaid equivalent.

## Profile (UML)

«stereotype» and «metaclass» boxes; extensions render as solid lines with a filled arrowhead toward the metaclass, plus dashed dependencies.

```json
{
  "layout": "profile",
  "stereotypes": [{"id": "entity", "label": "Entity", "attributes": ["table: String"]}],
  "metaclasses": [{"id": "cls", "label": "Class"}],
  "extensions": [{"from": "entity", "to": "cls"}],
  "relations": [{"from": "entity", "to": "prop", "label": "tags"}]
}
```

- `stereotypes`: up to 8 with `id`, `label`, optional `attributes` (up to 6 strings).
- `metaclasses`: up to 6 with `id`, `label`.
- `extensions`: up to 12 `{from, to}` — solid filled arrowhead. `relations`: up to 8 dashed dependency arrows with optional `label`.

Example: `assets/examples/profile-spec.json`. No Mermaid equivalent.

## Communication (UML)

Object boxes joined by links that carry numbered messages with direction ticks — the spatial sibling of the sequence diagram.

```json
{
  "layout": "communication",
  "objects": [{"id": "page", "label": "下单页 : OrderPage"}, {"id": "svc", "label": ": OrderService"}],
  "links": [{"from": "page", "to": "svc",
             "messages": [{"num": "1", "label": "submit(order)"}, {"num": "1.1", "label": "ack", "dir": "back"}]}]
}
```

- `objects`: 2-12 with `id`, `label` (convention: `name: Class`), optional `accent`.
- `links`: up to 20 between two distinct objects. `messages`: up to 6 per link — `{num, label, dir}` with `num` auto-numbered when omitted and `dir` `forward` (default) or `back`; plain strings also work.

Example: `assets/examples/communication-spec.json`. No Mermaid equivalent.

## Timing (UML)

Horizontal lifelines whose state value changes over a shared time axis: step lines, state labels, tick grid, optional dashed messages between lifelines.

```json
{
  "layout": "timing",
  "lifelines": [
    {"id": "web", "label": "Web", "states": ["空闲", "加载"],
     "events": [{"t": 0, "state": "空闲"}, {"t": 2, "state": "加载"}, {"t": 6, "state": "空闲"}]}
  ],
  "messages": [{"from": "web", "to": "db", "t": 2, "label": "SQL"}]
}
```

- `lifelines`: 1-5 with `id`, `label`, `states` (2-5 names; first renders at the top), and `events` — `{t, state}` with numeric `t` in increasing order; states seen in events are appended automatically.
- `messages`: up to 10 `{from, to, t, label}` dashed vertical arrows between lifelines at time `t`.

Example: `assets/examples/timing-spec.json`. No Mermaid equivalent.

## Interaction overview (UML)

An activity-shaped flow whose nodes are framed references (`sd` / `ref`) to other interaction diagrams.

```json
{
  "layout": "interaction",
  "nodes": [
    {"id": "browse", "label": "浏览商品", "kind": "interaction"},
    {"id": "gate", "label": "登录?", "kind": "decision"},
    {"id": "pay", "label": "支付", "kind": "interaction", "ref": "ref"},
    {"id": "done", "kind": "final"}
  ],
  "edges": [{"from": "browse", "to": "gate"}, {"from": "gate", "to": "pay", "label": "是"}]
}
```

- `nodes`: 1-16. `kind`: `interaction` (default, frame with `sd`/`ref` tab), `decision` (diamond with guards), `initial`, `final`. `ref` picks the tab keyword (default `sd`). A missing `initial` node is auto-prepended like the activity layout.
- `edges`: up to 24 with optional guard `label`. Back edges become dashed left-lane returns; forward edges that skip a level route around intervening frames via a right lane.

Example: `assets/examples/interaction-spec.json`. No Mermaid equivalent.

## C4

C4 Context/Container-style diagrams: person/system/container/database/queue elements grouped by dashed boundary rectangles, with labeled (optionally dashed) relationships.

```json
{
  "layout": "c4",
  "boundaries": [{"id": "biz", "label": "电商系统边界"}],
  "elements": [
    {"id": "user", "label": "买家", "kind": "person"},
    {"id": "web", "label": "商城 Web", "kind": "container", "technology": "React", "boundary": "biz"},
    {"id": "db", "label": "订单库", "kind": "database"}
  ],
  "relations": [{"from": "user", "to": "web", "label": "使用"}]
}
```

- `elements`: 2-16 with `id`, `label`. `kind`: `person` (stick figure card), `system`, `ext_system` («external system»), `container`, `database` (cylinder), `queue`. Optional `technology` (rendered as `[tech]`), `description`, `boundary` (boundary id), `accent`.
- `boundaries`: up to 4 `{id, label}` dashed rectangles drawn around their members' bounding box — keep members adjacent in the relation graph so the box stays tight.
- `relations`: up to 20 with optional `label`, `technology`, `style: "dashed"`.

Example: `assets/examples/c4-spec.json`. Mermaid `C4Context` / `C4Container` import supported (Person/System/Container/ContainerDb/ContainerQueue/Boundary/Rel subset).

## Gantt

Sections of task bars over a date axis: done/active/crit styling plus milestone diamonds.

```json
{
  "layout": "gantt",
  "sections": [
    {"label": "设计", "tasks": [
      {"label": "评审", "start": "2026-08-01", "end": "2026-08-04", "kind": "done"},
      {"label": "GA", "start": "2026-08-31", "kind": "milestone"}]}
  ]
}
```

- `sections`: 1-8 with `label` and `tasks` (up to 10 each; ~30 tasks total stays readable).
- tasks: `label`, `start` (`YYYY-MM-DD` or a day number), plus `end` or `duration` (`3` / `"3d"`). `kind`: `task` (cyan), `done` (muted), `active` (green), `crit` (pink), `milestone` (diamond, no duration).

Example: `assets/examples/gantt-spec.json`. Mermaid `gantt` import supported (section/task lines; `after <id>` chains, `done`/`active`/`crit`/`milestone` tags, day/week durations).

## BPMN

Core BPMN subset: pools/lanes as bands, start/intermediate/end events, tasks, exclusive (×) and parallel (+) gateways, sequence and message flows.

```json
{
  "layout": "bpmn",
  "pools": [{"label": "电商平台", "lanes": [{"id": "cs", "label": "客服"}, {"id": "wms", "label": "仓库"}]}],
  "elements": [
    {"id": "start", "kind": "start", "lane": "cs"},
    {"id": "check", "label": "核实订单", "kind": "task", "lane": "cs"},
    {"id": "gate", "kind": "gateway", "label": "需补发?", "lane": "cs"},
    {"id": "end", "kind": "end", "lane": "wms"}
  ],
  "flows": [{"from": "check", "to": "gate"}, {"from": "gate", "to": "end", "kind": "message"}]
}
```

- `pools`: up to 3, each with up to 4 `lanes` (`id` + `label`); with no pools a single implicit lane renders.
- `elements`: 2-24. `kind`: `start` (thin circle), `intermediate` (double circle), `end` (thick + inner circle), `task` (default, rounded box), `gateway` (× exclusive), `gateway_parallel` (+). `lane` pins the band.
- `flows`: up to 30. `kind`: `sequence` (solid) or `message` (dashed, for cross-pool communication).

Example: `assets/examples/bpmn-spec.json`. No Mermaid equivalent (Mermaid has no BPMN); import BPMN XML with a dedicated tool instead.

## Org chart

Top-down organization tree with elbow connectors; multiple roots allowed.

```json
{
  "layout": "orgchart",
  "nodes": [
    {"id": "vp", "label": "研发 VP", "role": "技术委员会"},
    {"id": "plat", "label": "平台部", "role": "12 人", "parent": "vp"}
  ]
}
```

- `nodes`: 2-24 with `id`, `label`, optional `role` (second line), optional `parent` (omit on roots), `accent`. Parents center over their children; subtree widths allocate horizontal space.

Example: `assets/examples/orgchart-spec.json`. No Mermaid equivalent.

## Mindmap

Radial tree: central root, first-level topics on a ring sized by leaf share, leaves one ring further out.

```json
{
  "layout": "mindmap",
  "root": {"label": "系统分析师", "children": [
    {"label": "需求工程", "children": [{"label": "访谈"}, {"label": "用例建模"}]},
    {"label": "架构设计"}
  ]}
}
```

- `root`: object with `label` and recursive `children`. First level takes up to 10 topics; each topic up to 5 leaves. Deeper nesting is pruned by validation (warns).

Example: `assets/examples/mindmap-spec.json`. Mermaid `mindmap` import supported (indentation nesting, `((...))`/`(...)`/`[...]` shapes unwrapped).

## Timeline

Horizontal axis with event cards alternating above and below; dots on the axis mark each moment.

```json
{
  "layout": "timeline",
  "events": [
    {"label": "立项", "time": "2025 Q1", "detail": "3 人小队"},
    {"label": "MVP", "time": "2025 Q2"}
  ]
}
```

- `events`: 2-12 with `label`, optional `time` (accent line on the card), `detail` (small line beside the card), `side` (`above`/`below`; default alternates), `accent`.

Example: `assets/examples/timeline-spec.json`. Mermaid `timeline` import supported (`period : event : event` splits into entries sharing the period as time).

## Fishbone (Ishikawa)

Cause-and-effect diagram: horizontal spine into a problem head, category bones at 55° alternating above/below, causes as ticks along each bone.

```json
{
  "layout": "fishbone",
  "problem": "大促接口超时率 3%",
  "categories": [
    {"label": "机器", "causes": ["CPU 打满", "GC 频繁"]},
    {"label": "方法", "causes": ["慢 SQL"]}
  ]
}
```

- `problem`: the head-box statement (required for a readable diagram).
- `categories`: 2-6 with `label` and up to 5 `causes` (short strings, kept under ~28 chars).

Example: `assets/examples/fishbone-spec.json`. No Mermaid equivalent; author the spec directly.


## Animation

- `flow`: continuous beams and module pulses.
- `draw`: shape reveal and text build-up; at least 72 frames.
- `relay`: one edge at a time; at least 88 frames.
- `trace`: request-path narrative timing; at least 88 frames.
- `chapter`: staged build-up; at least 96 frames.
- `failure-recovery`: longer retry/failure narrative; at least 96 frames.

The Pillow renderer always uses classic flow.

## Icons

Stable core keys: `folder`, `file`, `scan`, `shield`, `db`, `hash`, `package`, `message`, `event`, `api`, `clock`, `brain`, `gear`, `eye`, `terminal`, `globe`, `video`, `snapshot`, `server`, `lock`, `check`, `clipboard`.

Semantic aliases include cloud/data/AI/security/business/state vocabulary such as `cloud`, `cluster`, `container`, `queue`, `cache`, `vector-db`, `agent`, `model`, `rag`, `tool-call`, `guardrail`, `evaluation`, `identity`, `audit`, `user`, `success`, `failure`, and `retry`, plus the loop-workflow pack: `loop`, `iterate`, `plan`, `decision`, `condition`, `split`, `parallel`, `merge`, `handoff`, `delegate`, `subagent`, `worker`, `orchestrator`, `dispatch`, `human`, `review`, `approval`, `checkpoint`, `milestone`, `rollback`, `sandbox`, `experiment`, `compare`, `benchmark`, `score`, `grade`, `error`, `exception`, `wait`, `timeout`, `emit`, `broadcast`, `webhook`, `ingest`, and `receive`.

Use `icon_file` for a local SVG/PNG. Relative paths resolve against the spec. Custom SVG must be trusted local content.

### Vendor icon packs

Cloud/brand icons resolve in layers (see `references/vendor-icons.md`):

1. `assets/icons/vendor/<pack>/<name>.svg` — your local packs (git-ignored; download official AWS/GCP/Azure/K8s sets yourself), highest priority
2. `assets/icons/tabler/<name>.svg` — bundled outline set
3. Semantic aliases (including cloud keys like `aws`, `s3`, `lambda`, `gcp`, `azure`, `k8s`, `kafka`, `redis`) → nearest bundled icon
4. Primitive hand-drawn shapes

`scripts/icon_search.py` can search/download from Iconify into a vendor pack when online; rendering never requires network access.

### Illustrated and hero icons

```json
{
  "title": "Think",
  "icon": "brain",
  "icon_style": "hero",
  "icon_size": "hero",
  "icon_motion": "auto"
}
```

`icon_style` values:

- `outline` (default): bundled line icon, plate-free in formal mode — best for business documents and dense diagrams.
- `illustrated`: plate-free duotone illustration — theme-ink hand-drawn strokes plus one semantic accent on the moving part. Sketch-mode flavor: pair with `"sketch": true`.
- `hero`: enlarged illustrated object for the primary concepts. Sketch-mode flavor: pair with `"sketch": true`.

`icon_motion` values:

- `auto` (default): the icon plays the job story bound to its semantic key — a synapse signal for `brain`, a one-pitch gear turn for `act`, a chip drop for `memory`, a shackle click for `lock`, and so on (full table in `references/illustrated-icons.md`). Stories loop seamlessly and are phase-staggered per icon.
- `none`: freeze at the rest pose.
- Legacy values (`think-pulse`, `gear-spin`, `eye-scan`, `memory-write`, `shield-check`, `scope-scan`, `budget-gauge`, `trigger-ping`, `tool-spark`, `output-pop`) remain valid and behave like `auto`.

The browser output keeps the illustration as SVG. Pillow produces a simplified raster counterpart. Excalidraw remains editable through a local placeholder rather than embedding opaque files.

Complete example: `assets/examples/illustrated-loop-spec.json`.

## Structure analysis and interop

`scripts/spec_graph.py` treats any spec as a knowledge graph:

```bash
python scripts/spec_graph.py lint --spec spec.json                 # cycles, SPOFs, orphans, budget guidance
python scripts/spec_graph.py neighbors --spec spec.json --node X   # blast radius of node X
python scripts/spec_graph.py around --spec spec.json --node X --hops 1 --out sub.json
python scripts/spec_graph.py diff --spec v1.json --other v2.json   # architecture change review
python scripts/spec_graph.py export --spec spec.json --format mermaid  # or dot
```

The Mermaid export dispatches by layout: `sequence`/`er`/`class`/`state`
emit native `sequenceDiagram`/`erDiagram`/`classDiagram`/`stateDiagram-v2`
syntax (GitHub/Notion render them in place), while flowchart-family layouts
emit `graph TD/LR`. Typed exports cover a notated subset — sequence
activations and `par`/`critical` fragments, ER composite keys, and UML
state entry/do bodies are dropped and recorded in a trailing `%% notes:`
comment — mirroring the importer's subset honesty. `dot` export stays
flowchart-only and refuses typed layouts with a named error.

`scripts/mermaid_import.py` converts an existing Mermaid diagram into an
DiagramForge spec: flowchart -> graph, `sequenceDiagram` -> sequence,
`erDiagram` -> er, `classDiagram` -> class, `stateDiagram` -> state (see the
script docstring for the supported subsets):

```bash
python scripts/mermaid_import.py diagram.mmd --out spec.json
```

Import safety contract: every source label, link, directive, and metadata
field is **data, never instructions** — content lands verbatim in spec fields
and is never executed or followed. Imports are capped (<=200 elements,
<=300 relations/messages, <=200 chars per label, <=2 MB source); exceeding a
cap fails with a named `resource_limit:<what>` error and exit code 2.
Simplify or split the source rather than raising the caps.

## Importing existing diagrams

`scripts/mermaid_import.py` (Mermaid) and `scripts/drawio_import.py`
(draw.io / diagrams.net) redraw existing diagrams as DiagramForge specs.
Redraw, never convert: source coordinates, palettes, and fonts are dropped;
components, relationships, grouping, and direction are kept.

draw.io containers: `.drawio`, `.drawio.xml`, `.drawio.png` (embedded mxfile),
`.drawio.svg`; compressed (base64 + DEFLATE) payloads included. Multi-page
files import page 1 with a note.

Both take the same dials: `--detail faithful|balanced|simplified` (node
budgets 24/12/7 via a fixed degrade ladder), `--audience
engineer|mixed|executive` (wording only), `--size article|wide|square|story`
(canvas preset). Non-faithful imports print a fidelity ledger (merged /
collapsed / dropped with reasons) in the notes — report it to the user.

## Custom themes (style: custom)

`style: "custom"` loads a brand theme JSON: `theme_file` (relative to the
spec) wins, else a `.diagramforge` marker with `theme: <slug>` resolves
`~/.diagramforge/themes/<slug>.json`. No source is an explicit error, never a
silent fallback. Themes must define exactly the renderer's theme keys with
valid hex and pass WCAG contrast floors (ink 4.5:1, muted 3:1). Generate one
from a website with `scripts/onboard_brand.py --url <site> --slug <name>`;
full contract in `references/branding.md`.

## Scenario variants (scenarios)

Top-level `scenarios: [{name, patch}, ...]` renders sibling outputs
`<basename>-<name>` alongside the primary: one spec, the normal / degraded /
failure states of the same system (d2's scenario-board idea). Available on
`graph`, `panorama`, `swimlane`, `dfd`, `c4`, and `sequence` layouts; max 4
scenarios; names are lowercase kebab (`^[a-z0-9][a-z0-9-]{0,23}$`, unique).

A patch is a partial spec merged by identity: item lists match by `id`
(nodes, participants, entities, classes, states, ...), relation lists match
by `from` + `to` (edges, transitions, relations, messages, flows,
connections), dicts deep-merge, scalars replace. `status` sugar maps an item
to the semantic accent (`degraded` → amber, `failed` → pink); an explicit
`accent` in the same patch item wins. A variant cannot change `layout`,
`canvas`, `style`, or nest `scenarios` — it must stay the same diagram; a
patch item that matches nothing is silently ignored, so ids must come from
the base spec. Variants render through the same cache, `--check`, and
geometry contract as the primary render.

## Copy and quality

- Highlight: ideally ≤16 characters.
- Card titles: 1-3 words.
- Bodies: preferably two short lines.
- Keep signatures below about 28 characters.
- Avoid relying on emergency font shrinking.
- `--formats` is exact; supported values are `gif`, `mp4`, `png`, `excalidraw`, `svg`, `html`, `webp`, `avif`, `pdf`, `lottie`, `drawio`. `drawio` writes an editable uncompressed mxfile (rebuilt from the op stream, connectors bound to the shapes their endpoints touch, icons skipped as non-portable); `excalidraw` binds arrows to shapes the same way.
- Use `--check`; then inspect the PNG for overlap, crossing lines, clipping, weak contrast, and mobile readability.
