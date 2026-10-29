#include "CoreLayerCombine.hpp"

#include "ClipperUtils.hpp"
#include "ExPolygon.hpp"
#include "ExtrusionEntity.hpp"
#include "ExtrusionEntityCollection.hpp"
#include "Layer.hpp"
#include "PerimeterGenerator.hpp"
#include "Print.hpp"
#include "PrintConfig.hpp"
#include "Surface.hpp"
#include "SurfaceCollection.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <mutex>
#include <vector>

#include <boost/format.hpp>
#include <boost/log/trivial.hpp>
#include <tbb/blocked_range.h>
#include <tbb/parallel_for.h>

#include "I18N.hpp"

#define L(s) Slic3r::I18N::translate(s)

namespace Slic3r {

bool clc_enabled(const PrintRegionConfig &config)
{
    return config.core_layer_combine.value && config.shell_wall_loops.value >= 1;
}

bool clc_is_core(const ExtrusionEntity &entity, const PrintRegionConfig &config)
{
    return entity.inset_idx >= config.shell_wall_loops.value;
}

bool clc_any_core(const ExtrusionEntityCollection &extrusions, const PrintRegionConfig &config)
{
    if (clc_is_core(extrusions, config))
        return true;
    return std::any_of(extrusions.entities.begin(), extrusions.entities.end(), [&config](const ExtrusionEntity *ee) {
        const auto *collection = dynamic_cast<const ExtrusionEntityCollection *>(ee);
        return collection != nullptr ? clc_any_core(*collection, config) : clc_is_core(*ee, config);
    });
}

bool clc_all_core(const ExtrusionEntityCollection &extrusions, const PrintRegionConfig &config)
{
    if (clc_is_core(extrusions, config))
        return true;
    return !extrusions.entities.empty() &&
        std::all_of(extrusions.entities.begin(), extrusions.entities.end(), [&config](const ExtrusionEntity *ee) {
            const auto *collection = dynamic_cast<const ExtrusionEntityCollection *>(ee);
            return collection != nullptr ? clc_all_core(*collection, config) : clc_is_core(*ee, config);
        });
}

void clc_tag_core_fill(ExtrusionEntity &entity)
{
    entity.inset_idx = CLC_CORE_FILL_TAG;
    if (auto *collection = dynamic_cast<ExtrusionEntityCollection *>(&entity))
        for (ExtrusionEntity *ee : collection->entities)
            clc_tag_core_fill(*ee);
}

Flow clc_flow(const LayerRegion &layerm, FlowRole role, int filament_id, double height, bool bridge, bool thick_bridge)
{
    const PrintObject       &object       = *layerm.layer()->object();
    const PrintConfig       &print_config = object.print()->config();
    const PrintRegionConfig &config       = layerm.region().config();
    const float nozzle = float(nozzle_diameter_for_filament(print_config, filament_id, object.print()->is_BBL_printer()));

    ConfigOptionFloatOrPercent width;
    if (layerm.layer()->id() == 0 && print_config.initial_layer_line_width.value > 0)
        width = print_config.initial_layer_line_width;
    else if (role == frExternalPerimeter)
        width = config.outer_wall_line_width;
    else if (role == frPerimeter)
        width = config.inner_wall_line_width;
    else if (role == frInfill)
        width = config.sparse_infill_line_width;
    else if (role == frSolidInfill)
        width = config.internal_solid_infill_line_width;
    else
        width = config.top_surface_line_width;
    if (width.value == 0)
        width = object.config().line_width;

    if (bridge) {
        // Same as LayerRegion::bridging_flow(), with the given nozzle.
        const double bridge_width = config.bridge_line_width.get_abs_value(nozzle);
        if (thick_bridge) {
            float thread = bridge_width > 0. ? float(bridge_width) : nozzle;
            if (config.bridge_flow.value > 0.)
                thread *= float(std::sqrt(config.bridge_flow.value));
            return Flow::bridging_flow(thread, nozzle);
        }
        Flow base = Flow::new_from_config_width(role, width, nozzle, float(height));
        if (bridge_width > 0.)
            base = Flow(float(bridge_width), base.height(), nozzle);
        return base.with_flow_ratio(config.bridge_flow.value);
    }
    return Flow::new_from_config_width(role, width, nozzle, float(height));
}

namespace {

double area_mm2(const ExPolygons &expolygons)
{
    double area = 0.;
    for (const ExPolygon &expolygon : expolygons)
        area += expolygon.area();
    return area * SCALING_FACTOR * SCALING_FACTOR;
}

// A part of the core printed as one thick extrusion: present in layers [bottom, top], printed in top.
struct Piece
{
    ExPolygons area;
    size_t     bottom;
    size_t     top;
};

struct Planner
{
    // Combinable core per layer, empty for layers that must stay thin.
    std::vector<ExPolygons> combinable;
    std::vector<bool>       eligible;
    double                  min_area;          // scaled^2
    float                   opening;           // scaled
    double                  toolchange_penalty; // mm^2 of core pass area per tool change
    bool                    avoid_extra_toolchanges;

    // Cascade of one group [s, e] (F-12): the largest windows first, windows ending in the top layer before
    // lower ones. Returns the pieces and the cost of the group (F-22).
    double cascade(size_t s, size_t e, std::vector<Piece> *pieces) const
    {
        const size_t n = e - s + 1;
        std::vector<ExPolygons> assigned(n);
        std::vector<Piece>      out;
        for (size_t m = n; m >= 2; --m) {
            for (size_t top = e; top + 1 >= s + m; --top) {
                if (top != e && avoid_extra_toolchanges)
                    break;
                const size_t bottom = top + 1 - m;
                ExPolygons area = diff_ex(combinable[bottom], assigned[bottom - s]);
                for (size_t j = bottom + 1; j <= top && !area.empty(); ++j)
                    area = intersection_ex(area, diff_ex(combinable[j], assigned[j - s]));
                if (!area.empty() && opening > 0)
                    area = opening_ex(area, opening);
                area.erase(std::remove_if(area.begin(), area.end(), [this](const ExPolygon &ex) { return ex.area() < min_area; }), area.end());
                if (area.empty())
                    continue;
                for (size_t j = bottom; j <= top; ++j) {
                    append(assigned[j - s], area);
                    assigned[j - s] = union_ex(assigned[j - s]);
                }
                out.push_back({ std::move(area), bottom, top });
                if (top == 0)
                    break;
            }
            if (m == 2)
                break;
        }
        double cost = 0.;
        std::vector<size_t> tops;
        for (const Piece &piece : out) {
            cost += area_mm2(piece.area);
            if (std::find(tops.begin(), tops.end(), piece.top) == tops.end())
                tops.push_back(piece.top);
        }
        for (size_t j = s; j <= e; ++j)
            cost += area_mm2(diff_ex(combinable[j], assigned[j - s]));
        cost += toolchange_penalty * 2. * double(tops.size());
        if (pieces != nullptr)
            *pieces = std::move(out);
        return cost;
    }
};

void mark_core_walls(ExtrusionEntity &entity, int shift)
{
    if (auto *collection = dynamic_cast<ExtrusionEntityCollection *>(&entity)) {
        collection->inset_idx = std::max(collection->inset_idx, 0) + shift;
        for (ExtrusionEntity *ee : collection->entities)
            mark_core_walls(*ee, shift);
        return;
    }
    entity.inset_idx = std::max(entity.inset_idx, 0) + shift;
    auto demote = [](ExtrusionPaths &paths) {
        for (ExtrusionPath &path : paths)
            if (path.role() == erExternalPerimeter)
                path.set_extrusion_role(erPerimeter);
    };
    if (auto *loop = dynamic_cast<ExtrusionLoop *>(&entity))
        demote(loop->paths);
    else if (auto *multipath = dynamic_cast<ExtrusionMultiPath *>(&entity))
        demote(multipath->paths);
    else if (auto *path = dynamic_cast<ExtrusionPath *>(&entity); path != nullptr && path->role() == erExternalPerimeter)
        path->set_extrusion_role(erPerimeter);
}

// Core walls and core fill area of one piece, generated at the combined height (F-14, F-40).
void generate_piece(PrintObject &object, const LayerRegion &layerm, const ExPolygons &area, double height,
                    ExtrusionEntityCollection &loops, ExtrusionEntityCollection &gap_fill, ExPolygons &fill, ExPolygons &fill_no_overlap)
{
    const PrintRegionConfig &config = layerm.region().config();
    PrintRegionConfig core_config   = config;
    core_config.wall_loops.value                   = config.core_wall_loops.value;
    core_config.only_one_wall_top.value            = false;
    core_config.only_one_wall_first_layer.value    = false;
    core_config.detect_overhang_wall.value         = false;
    core_config.extra_perimeters_on_overhangs.value = false;
    core_config.alternate_extra_wall.value         = false;
    core_config.fuzzy_skin.value                   = FuzzySkinType::None;
    core_config.seam_slope_type.value              = SeamScarfType::None;

    SurfaceCollection slices;
    slices.append(area, stInternal);
    // The piece is covered from above by construction, so nothing of it is a top surface.
    const ExPolygons  upper = offset_ex(area, float(scale_(1.)));
    SurfaceCollection upper_same_region;
    upper_same_region.append(upper, stInternal);

    const LayerRegionPtrs     compatible { const_cast<LayerRegion *>(&layerm) };
    const Flow                perimeter_flow = layerm.flow(frPerimeter, height);
    SurfaceCollection         fill_surfaces;
    PerimeterGenerator g(&slices, &compatible, height, layerm.layer()->slice_z, perimeter_flow, &core_config, &object.config(),
                         &object.print()->config(), false, 0., &loops, &gap_fill, &fill_surfaces, &fill_no_overlap);
    g.upper_slices             = &upper;
    g.upper_slices_same_region = &upper_same_region;
    g.layer_id                 = int(layerm.layer()->id());
    g.ext_perimeter_flow       = perimeter_flow;
    g.overhang_flow            = perimeter_flow;
    g.solid_infill_flow        = layerm.flow(frSolidInfill, height);
    if (object.config().wall_generator.value == PerimeterGeneratorType::Arachne)
        g.process_arachne();
    else
        g.process_classic();

    const int shift = config.shell_wall_loops.value;
    for (ExtrusionEntity *ee : loops.entities)
        mark_core_walls(*ee, shift);
    for (ExtrusionEntity *ee : gap_fill.entities)
        clc_tag_core_fill(*ee);
    fill = to_expolygons(fill_surfaces.surfaces);
}

} // namespace

void clc_combine_core(PrintObject &object)
{
    LayerPtrs   &layers = object.layers();
    const Print &print  = *object.print();
    const size_t n      = layers.size();
    if (n < 2)
        return;

    for (size_t region_id = 0; region_id < object.num_printing_regions(); ++region_id) {
        const PrintRegion       &region = object.printing_region(region_id);
        const PrintRegionConfig &config = region.config();
        if (!clc_enabled(config))
            continue;
        for (Layer *layer : layers)
            if (LayerRegion *layerm = layer->get_region(int(region_id)); layerm != nullptr)
                layerm->core_fills.clear();

        const double base_height = object.config().layer_height.value;
        const double core_nozzle = nozzle_diameter_for_filament(print.config(), config.inner_wall_filament_id.value, print.is_BBL_printer());
        const double core_height = config.core_layer_height.get_abs_value(core_nozzle);
        const size_t k_max       = size_t(std::clamp(int(std::floor(core_height / base_height + EPSILON)), 1, 8));
        if (k_max < 2)
            continue; // V-03 is reported by validation.

        const coord_t core_width = coord_t(scale_(region.flow(object, frPerimeter, base_height, false).width()));
        const size_t  top_n      = size_t(std::max(config.top_shell_layers.value,
                                                   int(std::ceil(config.top_shell_thickness.value / base_height - EPSILON))));
        const size_t  bottom_n   = size_t(std::max(config.bottom_shell_layers.value,
                                                   int(std::ceil(config.bottom_shell_thickness.value / base_height - EPSILON))));

        Planner planner;
        planner.combinable.assign(n, ExPolygons());
        planner.eligible.assign(n, false);
        planner.min_area                = std::max(double(object.printing_region(region_id).config().minimum_sparse_infill_area.value) /
                                                       (SCALING_FACTOR * SCALING_FACTOR),
                                                   double(3 * core_width) * double(3 * core_width));
        planner.opening                 = float(core_width) * 0.5f;
        planner.toolchange_penalty      = config.core_toolchange_penalty.value;
        planner.avoid_extra_toolchanges = config.core_avoid_extra_toolchanges.value;

        std::vector<ExPolygons> core_area(n);
        for (size_t i = 0; i < n; ++i) {
            const Layer *layer  = layers[i];
            LayerRegion *layerm = layers[i]->get_region(int(region_id));
            if (layerm == nullptr || layerm->slices.empty())
                continue;
            core_area[i] = layerm->fill_no_overlap_expolygons;
            // F-16: never the first layer or a raft layer; variable layer heights are rejected by validation (V-06).
            if (layer->id() == 0 || std::abs(layer->height - base_height) > EPSILON || i < bottom_n || i + top_n >= n)
                continue;
            // F-15: keep top and bottom shell zones, bridges and overhangs thin. A point is combinable only if
            // the object covers it in the next top_n layers and supports it in the previous bottom_n layers.
            ExPolygons area = core_area[i];
            for (size_t j = 1; j <= top_n && !area.empty(); ++j)
                area = intersection_ex(area, layers[i + j]->lslices);
            for (size_t j = 1; j <= bottom_n && !area.empty(); ++j)
                area = intersection_ex(area, layers[i - j]->lslices);
            if (!area.empty())
                area = opening_ex(area, planner.opening);
            planner.combinable[i] = std::move(area);
            planner.eligible[i]   = !planner.combinable[i].empty();
        }

        // F-22: dynamic programming over the layers, groups of 1..k_max layers.
        std::vector<double> best(n + 1, std::numeric_limits<double>::max());
        std::vector<size_t> size(n + 1, 1);
        best[0] = 0.;
        for (size_t e = 0; e < n; ++e) {
            for (size_t m = 1; m <= k_max && m <= e + 1; ++m) {
                const size_t s = e + 1 - m;
                if (best[s] == std::numeric_limits<double>::max())
                    continue;
                double cost;
                if (m == 1)
                    cost = area_mm2(planner.combinable[e]);
                else {
                    bool ok = true;
                    for (size_t j = s; j <= e && ok; ++j)
                        ok = planner.eligible[j];
                    if (!ok)
                        break;
                    cost = planner.cascade(s, e, nullptr);
                }
                if (best[s] + cost < best[e + 1]) {
                    best[e + 1] = best[s] + cost;
                    size[e + 1] = m;
                }
            }
        }

        std::vector<Piece> pieces;
        for (size_t e = n; e > 0;) {
            const size_t m = size[e];
            if (m >= 2) {
                std::vector<Piece> group;
                planner.cascade(e - m, e - 1, &group);
                append(pieces, std::move(group));
            }
            e -= m;
        }

        // Grow the pieces into the shell by core_shell_overlap (F-06), but never beyond the core of their layers.
        const float overlap = float(core_width * config.core_shell_overlap.value * 0.01);
        std::vector<ExPolygons> excluded(n);
        for (Piece &piece : pieces) {
            if (overlap > 0) {
                ExPolygons limit = offset_ex(core_area[piece.bottom], overlap);
                for (size_t j = piece.bottom + 1; j <= piece.top; ++j)
                    limit = intersection_ex(limit, offset_ex(core_area[j], overlap));
                piece.area = intersection_ex(offset_ex(piece.area, overlap), limit);
            }
            for (size_t j = piece.bottom; j <= piece.top; ++j)
                append(excluded[j], piece.area);
        }

        // The fill areas stay complete until prepare_infill() has classified the surfaces, as with combine_infill():
        // removing the combined core from the lower layers here would make ensure_vertical_shell_thickness turn
        // the core above it solid. clc_apply_core_fills() voids it later, recorded as fills of zero thickness.
        for (size_t i = 0; i < n; ++i)
            if (LayerRegion *layerm = layers[i]->get_region(int(region_id)); layerm != nullptr && !excluded[i].empty())
                layerm->core_fills.push_back({ union_ex(excluded[i]), 0., 0 });
        std::mutex mutex;
        tbb::parallel_for(tbb::blocked_range<size_t>(0, pieces.size()), [&](const tbb::blocked_range<size_t> &range) {
            for (size_t p = range.begin(); p < range.end(); ++p) {
                const Piece &piece  = pieces[p];
                double       height = 0.;
                for (size_t j = piece.bottom; j <= piece.top; ++j)
                    height += layers[j]->height;
                LayerRegion              *layerm = layers[piece.top]->get_region(int(region_id));
                ExtrusionEntityCollection loops, gap_fill;
                ExPolygons                piece_fill, piece_no_overlap;
                generate_piece(object, *layerm, piece.area, height, loops, gap_fill, piece_fill, piece_no_overlap);
                LayerRegion::CoreFill core_fill { std::move(piece_fill), height, (unsigned short) (piece.top - piece.bottom + 1) };
                // One layer can hold more than one piece, so the shared lists are written under a lock.
                std::lock_guard<std::mutex> lock(mutex);
                layerm->perimeters.append(std::move(loops.entities));
                layerm->thin_fills.append(std::move(gap_fill.entities));
                layerm->core_fills.emplace_back(std::move(core_fill));
            }
        });
        BOOST_LOG_TRIVIAL(info) << "Core layer combine: region " << region_id << ", " << pieces.size() << " combined pieces, k_max " << k_max;
    }
}

void clc_apply_core_fills(PrintObject &object)
{
    for (Layer *layer : object.layers())
        for (LayerRegion *layerm : layer->regions()) {
            if (layerm->core_fills.empty() || !clc_enabled(layerm->region().config()))
                continue;
            Surfaces out;
            for (Surface &surface : layerm->fill_surfaces.surfaces) {
                if (!(surface.surface_type == stInternal || surface.surface_type == stInternalSolid)) {
                    out.emplace_back(std::move(surface));
                    continue;
                }
                ExPolygons rest { surface.expolygon };
                // Core fills of the pieces printed in this layer first, then the voids: the rest of every piece that
                // spans this layer, which is the core walls in the top layer and everything in the layers below.
                for (const bool fills : { true, false })
                    for (const LayerRegion::CoreFill &core_fill : layerm->core_fills) {
                        if ((core_fill.layers > 0) != fills)
                            continue;
                        ExPolygons inside = intersection_ex(rest, core_fill.area);
                        if (inside.empty())
                            continue;
                        rest = diff_ex(rest, core_fill.area);
                        for (ExPolygon &expolygon : inside) {
                            Surface combined(surface, std::move(expolygon));
                            if (fills) {
                                combined.thickness        = core_fill.thickness;
                                combined.thickness_layers = core_fill.layers;
                            } else
                                combined.surface_type = stInternalVoid;
                            out.emplace_back(std::move(combined));
                        }
                    }
                for (ExPolygon &expolygon : rest)
                    out.emplace_back(surface, std::move(expolygon));
            }
            layerm->fill_surfaces.surfaces = std::move(out);
        }
}

StringObjectException clc_validate(const Print &print, const ClcWarn &warn)
{
    const PrintConfig &pc = print.config();
    for (const PrintObject *object : print.objects()) {
        for (size_t region_id = 0; region_id < object->num_printing_regions(); ++region_id) {
            const PrintRegionConfig &config = object->printing_region(region_id).config();
            if (!config.core_layer_combine.value)
                continue;
            auto error = [object](std::string message, std::string opt_key) {
                return StringObjectException { std::move(message), object->model_object(), std::move(opt_key) };
            };
            const std::string name = object->model_object()->name;
            if (config.shell_wall_loops.value < 1) // V-05
                return error(L("Core layer combine needs at least one shell wall."), "shell_wall_loops");
            // V-06
            if (pc.spiral_mode.value)
                return error(L("Core layer combine cannot be used with spiral vase mode."), "core_layer_combine");
            if (pc.print_sequence.value == PrintSequence::ByObject && print.objects().size() > 1)
                return error(L("Core layer combine cannot be used with printing by object."), "core_layer_combine");
            const double base_height = object->config().layer_height.value;
            for (const Layer *layer : object->layers())
                if (layer->id() > 0 && std::abs(layer->height - base_height) > EPSILON)
                    return error(L("Core layer combine needs a constant layer height. Remove the variable layer height or the height range modifiers of this object."),
                                 "core_layer_combine");

            const int    core_extruder = config.inner_wall_filament_id.value - 1;
            const double core_nozzle   = nozzle_diameter_for_filament(pc, config.inner_wall_filament_id.value, print.is_BBL_printer());
            const double core_height   = config.core_layer_height.get_abs_value(core_nozzle);
            const int    k             = int(std::floor(core_height / base_height + EPSILON));
            if (k < 2) // V-03
                return error(L("The core layer height must be at least twice the layer height."), "core_layer_height");
            const double max_height = pc.max_layer_height.get_at(core_extruder);
            if (max_height > 0. && core_height > max_height + EPSILON) // V-01
                return error((boost::format(L("The core layer height %1% mm is larger than the maximum layer height %2% mm of the core extruder.")) %
                              core_height % max_height).str(), "core_layer_height");
            if (pc.enable_prime_tower.value == false && config.inner_wall_filament_id.value != config.outer_wall_filament_id.value) // F-51
                return error(L("Core layer combine with two tools needs the prime tower, so that the core tool is cleaned after each tool change."),
                             "enable_prime_tower");

            if (core_height > 0.75 * core_nozzle + EPSILON) // V-02
                warn((boost::format(L("%1%: the core layer height is more than 75%% of the core nozzle diameter.")) % name).str(), "core_layer_height", object->model_object());
            if (std::abs(core_height - k * base_height) > EPSILON) // V-04
                warn((boost::format(L("%1%: the core layer height is not a multiple of the layer height, core layers are %2% mm high.")) % name % (k * base_height)).str(),
                     "core_layer_height", object->model_object());
            const std::string core_type  = pc.filament_type.get_at(core_extruder);
            const std::string shell_type = pc.filament_type.get_at(config.outer_wall_filament_id.value - 1);
            if (core_type != shell_type) // V-07
                warn((boost::format(L("%1%: core and shell use different filament types (%2% and %3%), check that they bond.")) % name % core_type % shell_type).str(),
                     "inner_wall_filament_id", object->model_object());
            if (config.inner_wall_line_width.get_abs_value(core_nozzle) + EPSILON < core_nozzle) // V-08
                warn((boost::format(L("%1%: the core line width is smaller than the core nozzle diameter.")) % name).str(), "inner_wall_line_width", object->model_object());
            if (config.infill_combination.value) // V-09
                warn((boost::format(L("%1%: infill combination is replaced by core layer combine.")) % name).str(), "infill_combination", object->model_object());
            const double height = unscale<double>(object->height());
            for (int filament : { config.inner_wall_filament_id.value, config.outer_wall_filament_id.value }) {
                const double lift_below = pc.retract_lift_below.get_at(filament - 1);
                if (lift_below > 0. && lift_below < height) { // V-12
                    warn((boost::format(L("%1%: Z hop of filament %2% stops at %3% mm, below the object height.")) % name % filament % lift_below).str(),
                         "retract_lift_below", object->model_object());
                    break;
                }
            }
        }
    }
    return {};
}

} // namespace Slic3r
