"""Miranda RFV — Cold plate (deliverable #4).

Reference Fusion 360 script for the split-type 88x88 mm copper cold
plate over an 80x80 mm ASIC. Hand-written ground truth. Components:
Bottom_Half (skived fin pattern), Top_Half (sealing plate with
inlet/outlet), U_Tube (OD 8 / ID 6 mm), 2x Barb_Fitting (OD 12 mm,
push-fit for flexible hose).

Run in Fusion: Utilities → Add-Ins → Scripts → + → select → Run.
— spec: samples/miranda-rfv-2u/spec.md
— params: samples/miranda-rfv-2u/params.yaml (cold_plate:)
"""

import os
import traceback

import adsk.core
import adsk.fusion

_PARAMS = [
    # name,             expression,  units,  comment
    ("cp_base_w",       "88 mm",     "mm",   "Cold plate width (X)"),
    ("cp_base_d",       "88 mm",     "mm",   "Cold plate depth (Y)"),
    ("cp_bot_t",        "8 mm",      "mm",   "Bottom half thickness"),
    ("cp_top_t",        "3 mm",      "mm",   "Top half thickness"),
    ("fin_thickness",   "0.3 mm",    "mm",   "Skived fin thickness"),
    ("fin_pitch",       "1.0 mm",    "mm",   "Skived fin pitch (center-to-center)"),
    ("fin_depth",       "6.0 mm",    "mm",   "Channel depth in bottom half"),
    ("fin_length",      "80 mm",     "mm",   "Fin length along Y (centered)"),
    ("fin_count",       "80",        "",     "Number of fin slots in pattern"),
    ("stack_hole_pitch","76 mm",     "mm",   "M3 stack-up screw pitch (square)"),
    ("stack_hole_d",    "3.2 mm",    "mm",   "M3 clearance hole"),
    ("inlet_pitch",     "30 mm",     "mm",   "Inlet/outlet pitch along Y"),
    ("inlet_d",         "8.4 mm",    "mm",   "Inlet/outlet through-hole diameter"),
    ("tube_od",         "8 mm",      "mm",   "U-tube outer diameter"),
    ("tube_id",         "6 mm",      "mm",   "U-tube inner diameter"),
    ("tube_leg_h",      "25 mm",     "mm",   "U-tube leg length above top half"),
    ("tube_bend_r",     "15 mm",     "mm",   "U-tube 180° bend radius"),
    ("tube_insert_h",   "3 mm",      "mm",   "U-tube insertion depth into top half"),
    ("barb_od",         "12 mm",     "mm",   "Hose barb outer diameter"),
    ("barb_len",        "10 mm",     "mm",   "Hose barb length"),
    ("oring_w",         "1.5 mm",    "mm",   "O-ring groove width"),
    ("oring_d",         "1.0 mm",    "mm",   "O-ring groove depth"),
    ("oring_offset",    "2 mm",      "mm",   "O-ring offset from outer edge"),
    ("rfid_pad_W",      "25 mm",     "mm",   "RFID pad width on top half"),
    ("rfid_pad_D",      "12 mm",     "mm",   "RFID pad depth on top half"),
    ("rfid_pad_recess", "0.4 mm",    "mm",   "RFID pad recess depth"),
]


def _ensure_params(design):
    user_params = design.userParameters
    for name, expr, units, comment in _PARAMS:
        existing = user_params.itemByName(name)
        if existing is None:
            user_params.add(name, adsk.core.ValueInput.createByString(expr), units, comment)
        else:
            existing.expression = expr
            existing.comment = comment


def _val(design, name):
    return design.userParameters.itemByName(name).value


def _new_component(root, name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    occ.component.name = name
    return occ


def _move(occ, dx_cm=0.0, dy_cm=0.0, dz_cm=0.0):
    transform = occ.transform2
    transform.translation = adsk.core.Vector3D.create(dx_cm, dy_cm, dz_cm)
    occ.transform2 = transform


def _largest_profile(sketch):
    best = None
    best_area = 0.0
    for prof in sketch.profiles:
        try:
            a = prof.areaProperties().area
        except Exception:
            continue
        if a > best_area:
            best_area = a
            best = prof
    return best or sketch.profiles.item(0)


def _build_bottom_half(design, root):
    occ = _new_component(root, "Bottom_Half")
    comp = occ.component
    W = _val(design, "cp_base_w")
    D = _val(design, "cp_base_d")
    T = _val(design, "cp_bot_t")
    pitch = _val(design, "stack_hole_pitch")
    hole_d = _val(design, "stack_hole_d")

    # Outer plate.
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-W / 2.0, -D / 2.0, 0),
        adsk.core.Point3D.create(W / 2.0, D / 2.0, 0),
    )
    inp = comp.features.extrudeFeatures.createInput(
        sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("cp_bot_t"))
    feat = comp.features.extrudeFeatures.add(inp)
    body = feat.bodies.item(0)
    body.name = "Bottom_Half"

    # 4 stack-up holes through the plate.
    holes_sketch = comp.sketches.add(comp.xYConstructionPlane)
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            holes_sketch.sketchCurves.sketchCircles.addByCenterRadius(
                adsk.core.Point3D.create(sx * pitch / 2.0, sy * pitch / 2.0, 0),
                hole_d / 2.0,
            )
    profs = adsk.core.ObjectCollection.create()
    for prof in holes_sketch.profiles:
        profs.add(prof)
    cut_inp = comp.features.extrudeFeatures.createInput(
        profs, adsk.fusion.FeatureOperations.CutFeatureOperation
    )
    cut_inp.setDistanceExtent(
        False, adsk.core.ValueInput.createByString("cp_bot_t + 1 mm")
    )
    cut_inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(cut_inp)

    _add_skived_fins(design, comp, body)
    _add_oring_groove(design, comp, body)
    return comp


def _add_skived_fins(design, comp, body):
    fin_t = _val(design, "fin_thickness")
    fin_pitch = _val(design, "fin_pitch")
    fin_depth = _val(design, "fin_depth")
    fin_length = _val(design, "fin_length")
    fin_count = int(design.userParameters.itemByName("fin_count").value)
    bot_t = _val(design, "cp_bot_t")

    # Construction plane on the +Z face of the bottom half.
    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(
        comp.xYConstructionPlane,
        adsk.core.ValueInput.createByString("cp_bot_t"),
    )
    plane = comp.constructionPlanes.add(plane_input)

    # One fin slot at the leftmost X position.
    span = (fin_count - 1) * fin_pitch
    x0 = -span / 2.0
    slot_w = fin_pitch - fin_t

    sketch = comp.sketches.add(plane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(x0 - slot_w / 2.0, -fin_length / 2.0, 0),
        adsk.core.Point3D.create(x0 + slot_w / 2.0, fin_length / 2.0, 0),
    )
    cut_inp = comp.features.extrudeFeatures.createInput(
        sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation,
    )
    cut_inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("-fin_depth"))
    cut_inp.participantBodies = [body]
    cut_feat = comp.features.extrudeFeatures.add(cut_inp)

    # Pattern the slot along +X (fin_count-1 additional copies).
    pattern_input = comp.features.rectangularPatternFeatures.createInput(
        _collection([cut_feat]),
        comp.xConstructionAxis,
        adsk.core.ValueInput.createByString("fin_count"),
        adsk.core.ValueInput.createByString("fin_pitch"),
        adsk.fusion.PatternDistanceType.SpacingPatternDistanceType,
    )
    comp.features.rectangularPatternFeatures.add(pattern_input)


def _add_oring_groove(design, comp, body):
    W = _val(design, "cp_base_w")
    D = _val(design, "cp_base_d")
    bot_t = _val(design, "cp_bot_t")
    o_w = _val(design, "oring_w")
    o_d = _val(design, "oring_d")
    o_off = _val(design, "oring_offset")

    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(
        comp.xYConstructionPlane,
        adsk.core.ValueInput.createByString("cp_bot_t"),
    )
    plane = comp.constructionPlanes.add(plane_input)
    sketch = comp.sketches.add(plane)

    outer_x = W / 2.0 - o_off
    outer_y = D / 2.0 - o_off
    inner_x = outer_x - o_w
    inner_y = outer_y - o_w
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-outer_x, -outer_y, 0),
        adsk.core.Point3D.create(outer_x, outer_y, 0),
    )
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-inner_x, -inner_y, 0),
        adsk.core.Point3D.create(inner_x, inner_y, 0),
    )

    # Groove profile = outer rectangle minus inner rectangle.
    groove_prof = None
    smallest_band = None
    for prof in sketch.profiles:
        try:
            a = prof.areaProperties().area
        except Exception:
            continue
        # The frame profile area = outer - inner; pick by area window.
        outer_area = (2 * outer_x) * (2 * outer_y)
        inner_area = (2 * inner_x) * (2 * inner_y)
        frame_area = outer_area - inner_area
        if abs(a - frame_area) < frame_area * 0.05:
            groove_prof = prof
            break
    if groove_prof is None:
        groove_prof = _largest_profile(sketch)

    cut_inp = comp.features.extrudeFeatures.createInput(
        groove_prof, adsk.fusion.FeatureOperations.CutFeatureOperation
    )
    cut_inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("-oring_d"))
    cut_inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(cut_inp)


def _build_top_half(design, root):
    occ = _new_component(root, "Top_Half")
    comp = occ.component
    W = _val(design, "cp_base_w")
    D = _val(design, "cp_base_d")
    bot_t = _val(design, "cp_bot_t")
    top_t = _val(design, "cp_top_t")
    pitch = _val(design, "stack_hole_pitch")
    hole_d = _val(design, "stack_hole_d")
    inlet_pitch = _val(design, "inlet_pitch")
    inlet_d = _val(design, "inlet_d")

    # Plate sits on +Z of bottom half: Z range [bot_t, bot_t + top_t].
    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(
        comp.xYConstructionPlane,
        adsk.core.ValueInput.createByString("cp_bot_t"),
    )
    plane = comp.constructionPlanes.add(plane_input)

    sketch = comp.sketches.add(plane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-W / 2.0, -D / 2.0, 0),
        adsk.core.Point3D.create(W / 2.0, D / 2.0, 0),
    )
    inp = comp.features.extrudeFeatures.createInput(
        sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("cp_top_t"))
    feat = comp.features.extrudeFeatures.add(inp)
    body = feat.bodies.item(0)
    body.name = "Top_Half"

    # Cuts: 4 stack holes, 2 inlet/outlet holes.
    cuts_sketch = comp.sketches.add(plane)
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            cuts_sketch.sketchCurves.sketchCircles.addByCenterRadius(
                adsk.core.Point3D.create(sx * pitch / 2.0, sy * pitch / 2.0, 0),
                hole_d / 2.0,
            )
    cuts_sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(0, +inlet_pitch / 2.0, 0), inlet_d / 2.0
    )
    cuts_sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(0, -inlet_pitch / 2.0, 0), inlet_d / 2.0
    )
    profs = adsk.core.ObjectCollection.create()
    for prof in cuts_sketch.profiles:
        profs.add(prof)
    cut_inp = comp.features.extrudeFeatures.createInput(
        profs, adsk.fusion.FeatureOperations.CutFeatureOperation
    )
    cut_inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("cp_top_t + 1 mm"))
    cut_inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(cut_inp)

    _add_top_rfid(design, comp, body)
    return comp


def _add_top_rfid(design, comp, body):
    bot_t = _val(design, "cp_bot_t")
    top_t = _val(design, "cp_top_t")
    pad_W = _val(design, "rfid_pad_W")
    pad_D = _val(design, "rfid_pad_D")
    recess = _val(design, "rfid_pad_recess")

    # Construction plane on top face of Top_Half (Z = bot_t + top_t).
    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(
        comp.xYConstructionPlane,
        adsk.core.ValueInput.createByString("cp_bot_t + cp_top_t"),
    )
    plane = comp.constructionPlanes.add(plane_input)
    sketch = comp.sketches.add(plane)
    # Off-center pad to clear the U-tube footprint along Y.
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-pad_W / 2.0, -25.0 / 10.0 - pad_D / 2.0, 0),
        adsk.core.Point3D.create(pad_W / 2.0, -25.0 / 10.0 + pad_D / 2.0, 0),
    )
    cut_inp = comp.features.extrudeFeatures.createInput(
        sketch.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation
    )
    cut_inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-recess))
    cut_inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(cut_inp)


def _build_u_tube(design, root):
    occ = _new_component(root, "U_Tube")
    comp = occ.component
    inlet_pitch = _val(design, "inlet_pitch")
    leg_h = _val(design, "tube_leg_h")
    bend_r = _val(design, "tube_bend_r")
    insert_h = _val(design, "tube_insert_h")
    od = _val(design, "tube_od")
    id_ = _val(design, "tube_id")
    bot_t = _val(design, "cp_bot_t")
    top_t = _val(design, "cp_top_t")

    # The U-tube path lives on the YZ plane.
    # Inlet/outlet centers at ±inlet_pitch/2 along Y on Z = bot_t + top_t
    # (top face of Top_Half). The tube descends "insert_h" into the
    # Top_Half (+inlet hole) and rises leg_h above it before the bend.
    z0 = bot_t + top_t  # top face of top half
    z_top = z0 + leg_h    # top of vertical legs (start of bend)
    y_left = -inlet_pitch / 2.0
    y_right = +inlet_pitch / 2.0

    # Inlet pitch must accommodate the bend radius geometrically.
    # bend_r < inlet_pitch/2 ensures the arc fits.
    sketch = comp.sketches.add(comp.yZConstructionPlane)
    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs

    p_in_left  = adsk.core.Point3D.create(y_left,  z0 - insert_h, 0)
    p_top_left = adsk.core.Point3D.create(y_left,  z_top, 0)
    p_top_right= adsk.core.Point3D.create(y_right, z_top, 0)
    p_in_right = adsk.core.Point3D.create(y_right, z0 - insert_h, 0)

    leg_left  = lines.addByTwoPoints(p_in_left,  p_top_left)
    leg_right = lines.addByTwoPoints(p_top_right, p_in_right)
    bend = arcs.addByThreePoints(
        p_top_left,
        adsk.core.Point3D.create(0, z_top + bend_r, 0),
        p_top_right,
    )

    # Path = the three connected curves.
    curves = adsk.core.ObjectCollection.create()
    curves.add(leg_left)
    curves.add(bend)
    curves.add(leg_right)
    path = adsk.fusion.Path.create(
        leg_left, adsk.fusion.ChainedCurveOptions.connectedChainedCurves
    )

    # Solid pipe OD.
    pipe_in = comp.features.pipeFeatures.createInput(
        path, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    pipe_in.sectionSize = adsk.core.ValueInput.createByString("tube_od")
    pipe_in.sectionType = adsk.fusion.PipeSectionTypes.CircularPipeSectionType
    pipe = comp.features.pipeFeatures.add(pipe_in)
    pipe.bodies.item(0).name = "U_Tube_Solid"
    outer_body = pipe.bodies.item(0)

    # Bore.
    bore_in = comp.features.pipeFeatures.createInput(
        path, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    bore_in.sectionSize = adsk.core.ValueInput.createByString("tube_id")
    bore_in.sectionType = adsk.fusion.PipeSectionTypes.CircularPipeSectionType
    bore = comp.features.pipeFeatures.add(bore_in)
    bore_body = bore.bodies.item(0)

    # Combine: outer - bore.
    combine_in = comp.features.combineFeatures.createInput(outer_body, _collection([bore_body]))
    combine_in.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    combine_in.isKeepToolBodies = False
    comp.features.combineFeatures.add(combine_in)
    outer_body.name = "U_Tube"
    return comp


def _build_barb(design, root, name, y_offset_cm):
    occ = _new_component(root, name)
    comp = occ.component
    od = _val(design, "barb_od")
    bid = _val(design, "tube_id")
    length = _val(design, "barb_len")
    bot_t = _val(design, "cp_bot_t")
    top_t = _val(design, "cp_top_t")
    leg_h = _val(design, "tube_leg_h")

    # Barb is a hollow cylinder centered on the tube end.
    # Tube end Z = bot_t + top_t + leg_h - barb_len (so barb extends
    # from the bend down toward the magistral hose direction).
    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(
        comp.xYConstructionPlane,
        adsk.core.ValueInput.createByString("cp_bot_t + cp_top_t + tube_leg_h - barb_len"),
    )
    plane = comp.constructionPlanes.add(plane_input)
    sketch = comp.sketches.add(plane)
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(y_offset_cm, 0, 0), od / 2.0
    )
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(y_offset_cm, 0, 0), bid / 2.0
    )

    # Outer ring profile: outer minus inner.
    target = None
    smallest = None
    for prof in sketch.profiles:
        try:
            a = prof.areaProperties().area
        except Exception:
            continue
        ring_area = 3.14159 * (od * od - bid * bid) / 4.0
        if abs(a - ring_area) < ring_area * 0.05:
            target = prof
            break
    if target is None:
        target = _largest_profile(sketch)

    inp = comp.features.extrudeFeatures.createInput(
        target, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("barb_len"))
    feat = comp.features.extrudeFeatures.add(inp)
    feat.bodies.item(0).name = name

    # Note: the barb sketch sits on XY plane; we reused it on the offset plane
    # so the second axis here is X-world rather than Y-world. The original
    # request places barbs along Y at ±inlet_pitch/2; we used the YZ axis
    # for the U-tube. To align, we rotate via component transform.
    # Simpler: leave barbs centered on X=0 and translate per port via Y.
    # The y_offset_cm parameter selects which leg we sit on.
    return comp


def _collection(items):
    coll = adsk.core.ObjectCollection.create()
    for it in items:
        coll.add(it)
    return coll


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
        design.rootComponent.name = "Miranda_RFV_Cold_Plate"

        _ensure_params(design)

        root = design.rootComponent
        _build_bottom_half(design, root)
        _build_top_half(design, root)
        _build_u_tube(design, root)

        # Two barb fittings, one on each leg.
        inlet_pitch = _val(design, "inlet_pitch")
        _build_barb(design, root, "Barb_Fitting_A", -inlet_pitch / 2.0)
        _build_barb(design, root, "Barb_Fitting_B", +inlet_pitch / 2.0)

        _export(design)
    except Exception:
        if ui is not None:
            ui.messageBox("Miranda RFV cold plate script failed:\n" + traceback.format_exc())
        raise
