#pragma once

// Core layer combine (CLC): a thin shell of fine walls is printed at the object layer height with the
// outer wall filament, the core inside it (coarse walls and infill) in combined thick layers with the
// inner wall and infill filaments. See tools/core_layer_combine/PLAN.md for the design.

#include "Flow.hpp"

#include <functional>
#include <string>

namespace Slic3r {

class ExtrusionEntity;
class ExtrusionEntityCollection;
class LayerRegion;
class ObjectBase;
class Print;
class PrintObject;
class PrintRegionConfig;
struct StringObjectException;

// Version of the core layer combine fork, shown in the window title and the G-code header (NF-06, F-45).
constexpr const char *CLC_VERSION = "1.0";

// inset_idx of core infill and core gap fill. Core walls carry their wall index shifted by the shell wall
// count instead, so everything at or above shell_wall_loops belongs to the core.
constexpr int CLC_CORE_FILL_TAG = 1 << 24;

// Core layer combine is switched on for this region.
bool clc_enabled(const PrintRegionConfig &config);
// The entity belongs to the combined core and is printed with the core filaments.
bool clc_is_core(const ExtrusionEntity &entity, const PrintRegionConfig &config);
bool clc_any_core(const ExtrusionEntityCollection &extrusions, const PrintRegionConfig &config);
bool clc_all_core(const ExtrusionEntityCollection &extrusions, const PrintRegionConfig &config);
// Mark a combined core fill (all nested entities).
void clc_tag_core_fill(ExtrusionEntity &entity);

// Flow of the region for a role, but with the nozzle of the given 1 based filament. Thin parts of a CLC
// region are printed with the shell filament, so their widths refer to its nozzle (F-05).
Flow clc_flow(const LayerRegion &layerm, FlowRole role, int filament_id, double height, bool bridge = false, bool thick_bridge = false);

// Serial step after the per layer shell walls: plans the groups, generates the core walls of every
// combined piece in the top layer of its group and sets the fill areas of all layers.
void clc_combine_core(PrintObject &object);
// Step of prepare_infill(): gives the core fill surfaces their combined thickness.
void clc_apply_core_fills(PrintObject &object);

// Checks V-01 to V-12 of the requirements. Returns an error (empty string if none) and reports warnings.
using ClcWarn = std::function<void(std::string message, std::string opt_key, const ObjectBase *object)>;
StringObjectException clc_validate(const Print &print, const ClcWarn &warn);

} // namespace Slic3r
