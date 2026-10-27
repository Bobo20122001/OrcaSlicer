# Bottom bridge fill algorithms — High Level Design

## Purpose and scope

Bottom bridge fill covers downward-facing surface areas that are not fully
supported by the layer below. OrcaSlicer represents these areas as
`stBottomBridge` surfaces and prints them with bridge-specific flow and other
bridge parameters. This design gives those surfaces an algorithm choice of
their own, so a specialized path generator such as wave fill can be added
without making it an ordinary sparse- or surface-infill pattern.

This concerns generation of fill paths for bottom bridge surfaces. It does not
change how bridge areas are detected, how overhanging perimeter segments are
tagged, or how support material is generated. In particular, `stBottomBridge`
is a surface classification, not a universal representation of every
overhang.

## Existing fill pipeline

Surface classification happens before fill-path generation. The slicing
pipeline classifies each region's areas as surfaces such as `stInternal`,
`stTop`, `stBottom`, and `stBottomBridge`. Bridge processing may also assign a
bridge angle to a surface.

`Layer::make_fills()` in `src/libslic3r/Fill/Fill.cpp` calls `group_fills()` to
derive fill parameters for these surfaces. For `stBottomBridge`, the current
code selects monotonic lines when the configured top-surface pattern is
Monotonic or Monotonic line, and rectilinear lines otherwise. The
`bottom_surface_pattern` setting does not select the bridge pattern. The
grouping step also assigns bridge role, flow, speed, and angle parameters.

The grouped parameters are passed to `Fill::new_from_type()`, which constructs
a concrete fill generator. That generator produces polylines; the fill
pipeline converts them to extrusion entities and stores them in the layer
region's fill collection for G-code generation.

## Bottom bridge algorithm selection

Bottom bridge algorithms are selected independently from general infill
patterns. A bridge-specific algorithm setting selects the strategy only for
`stBottomBridge`; other surface types continue to use their existing fill
settings and dispatch. The default strategy preserves the current
Monotonic/Rectilinear selection.

`group_fills()` is the point where surface type and configuration become
effective fill parameters. It records the selected bridge algorithm alongside
the existing role, flow, bridge angle, spacing, and speed data. The strategy
identity is part of the grouping key, so surfaces with different algorithms
cannot be coalesced and accidentally filled by the same strategy. During
`Layer::make_fills()`, dispatch to the bridge strategy only for
`stBottomBridge`; all other surfaces, including `stInternalBridge`, keep the
existing `Fill::new_from_type()` path.

A bridge generator receives the resolved bridge surface geometry and the data
needed to produce printable paths, including its bridge angle, line spacing,
flow, extrusion role, density, and region context. Algorithms that need to
reason about lateral anchoring, such as wave fill, must also receive the
relevant lower-layer geometry or precomputed anchor geometry. Generators
produce path geometry; the shared fill path converts it to extrusion entities
and applies the resolved role and flow. Generators operate on a complete
surface or polygon at a time; they do not intercept individual G-code moves.

The resolved bridge angle takes precedence over the general fill angle. If it
is undefined, the existing fill-direction fallback applies. The strategy must
not apply model alignment or angle overrides a second time. Bridge flow and
density are resolved by the existing fill setup and passed through rather than
recomputed by an algorithm.

The default strategy delegates to the existing bridge fill behavior. An
alternative strategy owns the selected bridge surface's fill area, so the
standard bridge filler does not emit a second set of paths over it. The result
uses the existing extrusion-entity representation and G-code role handling.

## Boundaries and constraints

- The algorithm selector applies to `stBottomBridge` only unless a future
  design explicitly includes other bridge surface types, such as
  `stInternalBridge`.
- Strategy identity and any strategy-specific parameters participate in fill
  grouping, so distinct algorithm choices are never merged into one fill job.
- Surface classification, bridge-angle detection, and bridge-fill path
  generation are separate responsibilities. A new fill algorithm consumes
  classified bridge geometry; it does not replace the classifier.
- The standard algorithm remains the default and retains existing behavior,
  including its current pattern selection and bridge settings.
- Generated paths must not overlap paths emitted by the standard bridge
  filler. Each selected surface is filled by exactly one strategy.
- Support generation runs separately from fill generation. Avoiding support
  beneath areas handled by a new bridge algorithm requires explicit support
  coupling and is outside this design.
- Bridge paths continue to use bridge-aware flow, role, cooling, and speed
  handling. A new strategy must provide the geometry and path properties
  required by those existing consumers.

## Verification

The default strategy should produce the same bridge paths as the current
Monotonic/Rectilinear selection for representative bridge surfaces. An
alternative strategy should affect only the selected `stBottomBridge` area;
other surfaces and their fill patterns should remain unchanged. Tests should
also verify bridge role and flow metadata, bridge-angle use, complete area
ownership without duplicate fill, and behavior when a strategy cannot produce
paths. Grouping tests should cover surfaces with matching and differing
strategies, and confirm that `stInternalBridge` stays on the existing path.
