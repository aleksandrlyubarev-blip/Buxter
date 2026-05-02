"""Miranda RFV — Chassis (deliverable #1).

Reference Fusion 360 script for the 2U liquid-cooled network server
chassis. Hand-written (not AI-generated) and serves as ground truth for
regression-testing buxter's Fusion 360 backend.

Run in Fusion: Utilities → Add-Ins → Scripts → + → select this file → Run.

If BUXTER_STL / BUXTER_STEP / BUXTER_F3D are set in the environment,
the script also exports the result there. Otherwise it just leaves the
document open for inspection.
— spec: samples/miranda-rfv-2u/spec.md
— params: samples/miranda-rfv-2u/params.yaml
"""

import os
import traceback

import adsk.core
import adsk.fusion

# Fusion's API uses centimeters internally. We declare values in mm and
# convert at the boundary. UserParameters keep their string expressions
# (e.g. "482.6 mm"), so editing them in the GUI Just Works.

_PARAMS = [
    # name,             expression,                 units,  comment
    ("chassis_W",       "482.6 mm",                 "mm",   "Outer rack width incl. ears (19\")"),
    ("ear_proj",        "17.3 mm",                  "mm",   "Rack ear projection per side"),
    ("ear_t",           "2.0 mm",                   "mm",   "Rack ear plate thickness"),
    ("chassis_H",       "88.9 mm",                  "mm",   "2U = 2 * 44.45"),
    ("chassis_D",       "780 mm",                   "mm",   "Depth, fits 800 mm rack"),
    ("sheet_t",         "1.0 mm",                   "mm",   "Galvanized steel sheet"),
    ("inner_W",         "chassis_W - 2 * ear_proj", "mm",   "Body width = 448 mm"),
    ("hole_pitch",      "25 mm",                    "mm",   "Mounting grid pitch"),
    ("m3_clear",        "3.2 mm",                   "mm",   "M3 clearance hole"),
    ("boss_od",         "5.5 mm",                   "mm",   "Mounting boss OD"),
    ("boss_h",          "6.0 mm",                   "mm",   "Mounting boss height"),
    ("align_pin_d",     "4.0 mm",                   "mm",   "Alignment pin diameter (H7/h7)"),
    ("align_pin_h",     "5.0 mm",                   "mm",   "Alignment pin protrusion"),
    ("rfid_pad_W",      "40 mm",                    "mm",   "RFID pad width"),
    ("rfid_pad_D",      "25 mm",                    "mm",   "RFID pad depth"),
    ("rfid_pad_recess", "0.5 mm",                   "mm",   "RFID pad recess depth"),
    ("rfid_pad_y",      "60 mm",                    "mm",   "RFID pad offset from front edge"),
    ("bus_bar_W",       "60 mm",                    "mm",   "Rear bus-bar slot width"),
    ("bus_bar_H",       "20 mm",                    "mm",   "Rear bus-bar slot height"),
    ("bus_bar_z",       "30 mm",                    "mm",   "Bus-bar slot offset above base"),
    ("qdc_d",           "30 mm",                    "mm",   "Rear QDC hole diameter"),
    ("qdc_z",           "60 mm",                    "mm",   "QDC hole offset above base"),
    ("ear_hole_d",      "7.1 mm",                   "mm",   "Rack ear clearance hole (M6/0.28\")"),
]


def _ensure_params(design):
    user_params = design.userParameters
    for name, expr, units, comment in _PARAMS:
        existing = user_params.itemByName(name)
        if existing is None:
            user_params.add(
                name,
                adsk.core.ValueInput.createByString(expr),
                units,
                comment,
            )
        else:
            existing.expression = expr
            existing.comment = comment


def _val(design, name):
    """Return parameter value in cm (Fusion internal units)."""
    return design.userParameters.itemByName(name).value


def _new_component(root, name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    occ.component.name = name
    return occ


def _move(occ, dx_cm=0.0, dy_cm=0.0, dz_cm=0.0):
    transform = occ.transform2
    vec = adsk.core.Vector3D.create(dx_cm, dy_cm, dz_cm)
    transform.translation = vec
    occ.transform2 = transform


def _rect_extrude(comp, plane, p0, p1, distance_expr, name):
    sketch = comp.sketches.add(plane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
    prof = sketch.profiles.item(0)
    inp = comp.features.extrudeFeatures.createInput(
        prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString(distance_expr))
    feat = comp.features.extrudeFeatures.add(inp)
    feat.bodies.item(0).name = name
    return feat


def _build_base(design, root):
    occ = _new_component(root, "Base")
    comp = occ.component
    inner_W = _val(design, "inner_W")
    D = _val(design, "chassis_D")

    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-inner_W / 2.0, 0, 0),
        adsk.core.Point3D.create(inner_W / 2.0, D, 0),
    )
    prof = sketch.profiles.item(0)
    inp = comp.features.extrudeFeatures.createInput(
        prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("sheet_t"))
    feat = comp.features.extrudeFeatures.add(inp)
    feat.bodies.item(0).name = "Base"

    _add_rfid_pad(design, comp, feat.bodies.item(0))
    _add_mounting_bosses(design, comp)
    _add_alignment_pins(design, comp)
    return comp


def _add_rfid_pad(design, comp, body):
    inner_W = _val(design, "inner_W")
    sheet_t = _val(design, "sheet_t")
    pad_W = _val(design, "rfid_pad_W")
    pad_D = _val(design, "rfid_pad_D")
    pad_y = _val(design, "rfid_pad_y")

    plane_input = comp.constructionPlanes.createInput()
    offset = adsk.core.ValueInput.createByString("sheet_t")
    plane_input.setByOffset(comp.xYConstructionPlane, offset)
    plane = comp.constructionPlanes.add(plane_input)

    sketch = comp.sketches.add(plane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-pad_W / 2.0, pad_y - pad_D / 2.0, 0),
        adsk.core.Point3D.create(pad_W / 2.0, pad_y + pad_D / 2.0, 0),
    )
    prof = sketch.profiles.item(0)
    inp = comp.features.extrudeFeatures.createInput(
        prof, adsk.fusion.FeatureOperations.CutFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("-rfid_pad_recess"))
    inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(inp)


def _add_mounting_bosses(design, comp):
    inner_W = _val(design, "inner_W")
    D = _val(design, "chassis_D")
    sheet_t = _val(design, "sheet_t")
    boss_od = _val(design, "boss_od")
    boss_h = _val(design, "boss_h")
    m3 = _val(design, "m3_clear")

    cols = 6
    rows = 2
    margin_x = 40.0 / 10.0  # 40 mm in cm
    margin_y = 60.0 / 10.0  # 60 mm in cm
    span_x = inner_W - 2 * margin_x
    span_y = D - 2 * margin_y
    step_x = span_x / (cols - 1)
    step_y = span_y / (rows - 1)

    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(comp.xYConstructionPlane, adsk.core.ValueInput.createByString("sheet_t"))
    plane = comp.constructionPlanes.add(plane_input)

    sketch = comp.sketches.add(plane)
    circles = sketch.sketchCurves.sketchCircles
    holes_sketch = comp.sketches.add(plane)
    inner_circles = holes_sketch.sketchCurves.sketchCircles

    for i in range(cols):
        x = -inner_W / 2.0 + margin_x + i * step_x
        for j in range(rows):
            y = margin_y + j * step_y
            circles.addByCenterRadius(adsk.core.Point3D.create(x, y, 0), boss_od / 2.0)
            inner_circles.addByCenterRadius(adsk.core.Point3D.create(x, y, 0), m3 / 2.0)

    # Boss extrusion
    boss_profs = adsk.core.ObjectCollection.create()
    for prof in sketch.profiles:
        boss_profs.add(prof)
    inp = comp.features.extrudeFeatures.createInput(
        boss_profs, adsk.fusion.FeatureOperations.JoinFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("boss_h"))
    comp.features.extrudeFeatures.add(inp)

    # M3 clearance through boss + base
    hole_profs = adsk.core.ObjectCollection.create()
    for prof in holes_sketch.profiles:
        hole_profs.add(prof)
    inp = comp.features.extrudeFeatures.createInput(
        hole_profs, adsk.fusion.FeatureOperations.CutFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("-(boss_h + sheet_t + 1 mm)"))
    comp.features.extrudeFeatures.add(inp)


def _add_alignment_pins(design, comp):
    inner_W = _val(design, "inner_W")
    D = _val(design, "chassis_D")
    pin_d = _val(design, "align_pin_d")
    margin = 50.0 / 10.0  # 50 mm in cm

    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(comp.xYConstructionPlane, adsk.core.ValueInput.createByString("sheet_t"))
    plane = comp.constructionPlanes.add(plane_input)
    sketch = comp.sketches.add(plane)
    circles = sketch.sketchCurves.sketchCircles

    corners = [
        (-inner_W / 2.0 + margin, margin),
        (inner_W / 2.0 - margin, margin),
        (-inner_W / 2.0 + margin, D - margin),
        (inner_W / 2.0 - margin, D - margin),
    ]
    for cx, cy in corners:
        circles.addByCenterRadius(adsk.core.Point3D.create(cx, cy, 0), pin_d / 2.0)

    profs = adsk.core.ObjectCollection.create()
    for prof in sketch.profiles:
        profs.add(prof)
    inp = comp.features.extrudeFeatures.createInput(
        profs, adsk.fusion.FeatureOperations.JoinFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("align_pin_h"))
    comp.features.extrudeFeatures.add(inp)


def _build_side(design, root, side):
    occ = _new_component(root, "Side_" + side)
    comp = occ.component
    D = _val(design, "chassis_D")
    H = _val(design, "chassis_H")
    inner_W = _val(design, "inner_W")
    sheet_t = _val(design, "sheet_t")

    sketch = comp.sketches.add(comp.yZConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(0, 0, 0),
        adsk.core.Point3D.create(D, H, 0),
    )
    prof = sketch.profiles.item(0)
    inp = comp.features.extrudeFeatures.createInput(
        prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("sheet_t"))
    feat = comp.features.extrudeFeatures.add(inp)
    feat.bodies.item(0).name = "Side_" + side

    if side == "L":
        _move(occ, dx_cm=-inner_W / 2.0)
    else:
        _move(occ, dx_cm=inner_W / 2.0 - sheet_t)
    return comp


def _build_rear(design, root):
    occ = _new_component(root, "Rear")
    comp = occ.component
    inner_W = _val(design, "inner_W")
    H = _val(design, "chassis_H")
    D = _val(design, "chassis_D")
    sheet_t = _val(design, "sheet_t")

    sketch = comp.sketches.add(comp.xZConstructionPlane)
    rect = sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-inner_W / 2.0, 0, 0),
        adsk.core.Point3D.create(inner_W / 2.0, H, 0),
    )
    bus_W = _val(design, "bus_bar_W")
    bus_H = _val(design, "bus_bar_H")
    bus_z = _val(design, "bus_bar_z")
    qdc = _val(design, "qdc_d")
    qdc_z = _val(design, "qdc_z")

    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-bus_W / 2.0, bus_z, 0),
        adsk.core.Point3D.create(bus_W / 2.0, bus_z + bus_H, 0),
    )
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(0, qdc_z, 0), qdc / 2.0
    )

    # Rear panel = outer rectangle minus the two cutouts
    profs = adsk.core.ObjectCollection.create()
    for prof in sketch.profiles:
        # The biggest profile (outer minus inner cutouts) is what we want.
        # In Fusion the profile that includes the outer loop and excludes
        # cutouts has the largest area; pick it.
        profs.add(prof)
    # We rely on Fusion auto-merging: extruding all profiles together gives
    # the panel with holes when using a single NewBody operation only if we
    # pass exactly the panel-with-holes profile. Safer: extrude the outer
    # rectangle, then cut the slot and the circle.

    # Simpler approach: redo with two sketches.
    sketch.deleteMe()

    outer = comp.sketches.add(comp.xZConstructionPlane)
    outer.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-inner_W / 2.0, 0, 0),
        adsk.core.Point3D.create(inner_W / 2.0, H, 0),
    )
    inp = comp.features.extrudeFeatures.createInput(
        outer.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("sheet_t"))
    feat = comp.features.extrudeFeatures.add(inp)
    body = feat.bodies.item(0)
    body.name = "Rear"

    cuts = comp.sketches.add(comp.xZConstructionPlane)
    cuts.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-bus_W / 2.0, bus_z, 0),
        adsk.core.Point3D.create(bus_W / 2.0, bus_z + bus_H, 0),
    )
    cuts.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(0, qdc_z, 0), qdc / 2.0
    )
    cut_profs = adsk.core.ObjectCollection.create()
    for prof in cuts.profiles:
        cut_profs.add(prof)
    cut_inp = comp.features.extrudeFeatures.createInput(
        cut_profs, adsk.fusion.FeatureOperations.CutFeatureOperation
    )
    cut_inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("sheet_t + 1 mm"))
    cut_inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(cut_inp)

    _move(occ, dy_cm=D - sheet_t)
    return comp


def _build_ear(design, root, side):
    occ = _new_component(root, "Rack_Ear_" + side)
    comp = occ.component
    proj = _val(design, "ear_proj")
    H = _val(design, "chassis_H")
    inner_W = _val(design, "inner_W")
    ear_t = _val(design, "ear_t")
    hole = _val(design, "ear_hole_d")

    # Ear lies on XZ plane (parallel to rear panel face), thickness toward +Y.
    sketch = comp.sketches.add(comp.xZConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(0, 0, 0),
        adsk.core.Point3D.create(proj, H, 0),
    )
    # EIA-310 ear holes: two per ear, 6.35 and 22.225 mm from each U boundary.
    # For a 2U ear we put holes at z = 6.35 and z = 88.9 - 6.35 (mm).
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(proj / 2.0, 6.35 / 10.0, 0), hole / 2.0
    )
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(proj / 2.0, (88.9 - 6.35) / 10.0, 0), hole / 2.0
    )

    # Pick the profile that is the rectangle minus the two holes.
    # It's the one with the largest area among profiles that are not the
    # hole-circle interiors.
    target_profile = None
    largest_area = 0.0
    for prof in sketch.profiles:
        try:
            area = prof.areaProperties().area
        except Exception:
            continue
        if area > largest_area:
            largest_area = area
            target_profile = prof
    if target_profile is None:
        target_profile = sketch.profiles.item(0)

    inp = comp.features.extrudeFeatures.createInput(
        target_profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("ear_t"))
    feat = comp.features.extrudeFeatures.add(inp)
    feat.bodies.item(0).name = "Rack_Ear_" + side

    if side == "L":
        _move(occ, dx_cm=-(inner_W / 2.0 + proj))
    else:
        _move(occ, dx_cm=inner_W / 2.0)
    return comp


def _export(design):
    em = design.exportManager
    root = design.rootComponent
    stl = os.environ.get("BUXTER_STL")
    step = os.environ.get("BUXTER_STEP")
    f3d = os.environ.get("BUXTER_F3D")
    if stl:
        em.execute(em.createSTLExportOptions(root, stl))
    if step:
        em.execute(em.createSTEPExportOptions(step, root))
    if f3d:
        em.execute(em.createFusionArchiveExportOptions(f3d, root))


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        design.unitsManager.defaultLengthUnits = "mm"
        design.rootComponent.name = "Miranda_RFV_Chassis"

        _ensure_params(design)

        root = design.rootComponent
        _build_base(design, root)
        _build_side(design, root, "L")
        _build_side(design, root, "R")
        _build_rear(design, root)
        _build_ear(design, root, "L")
        _build_ear(design, root, "R")

        _export(design)
    except Exception:
        if ui is not None:
            ui.messageBox("Miranda RFV chassis script failed:\n" + traceback.format_exc())
        raise
