"""Miranda RFV — Central liquid-cooling manifold (deliverable #3).

Reference Fusion 360 script. Hand-written ground truth for the buxter
Fusion 360 backend. AISI 304 stainless body with 4 blind-mate QDC ports
on the side faces, 2 rear-facing magistral inlets, 2 separate mounting
brackets (removable), top-side RFID pad, and base-side alignment-pin
blind holes.

Run in Fusion: Utilities → Add-Ins → Scripts → + → select → Run.
— spec: samples/miranda-rfv-2u/spec.md
— params: samples/miranda-rfv-2u/params.yaml (manifold:)
"""

import os
import traceback

import adsk.core
import adsk.fusion

_PARAMS = [
    # name,              expression,                units,  comment
    ("body_w",            "30 mm",                  "mm",   "Manifold body width (X)"),
    ("body_d",            "200 mm",                 "mm",   "Manifold body depth (Y)"),
    ("body_h",            "30 mm",                  "mm",   "Manifold body height (Z)"),
    ("centerline_y",      "350 mm",                 "mm",   "Y position of manifold center from chassis front"),
    ("bottom_clearance",  "10 mm",                  "mm",   "Clearance above base (clears mounting bosses)"),
    ("qdc_boss_d",        "16 mm",                  "mm",   "QDC boss outer diameter"),
    ("qdc_boss_l",        "12 mm",                  "mm",   "QDC boss length out from side face"),
    ("qdc_thread_clr",    "11 mm",                  "mm",   "G1/4 thread clearance bore"),
    ("qdc_pitch_y",       "80 mm",                  "mm",   "Y distance between supply and return ports"),
    ("qdc_supply_z",      "22 mm",                  "mm",   "Supply (upper) ports Z within body"),
    ("qdc_return_z",      "8 mm",                   "mm",   "Return (lower) ports Z within body"),
    ("rear_inlet_d",      "12 mm",                  "mm",   "Rear magistral inlet/outlet bore"),
    ("rear_boss_l",       "12 mm",                  "mm",   "Rear magistral boss length"),
    ("rear_boss_d",       "18 mm",                  "mm",   "Rear magistral boss outer diameter"),
    ("mount_pitch",       "120 mm",                 "mm",   "Bracket fastener pitch along Y"),
    ("mount_hole_d",      "4.5 mm",                 "mm",   "M4 clearance hole"),
    ("bracket_t",         "3 mm",                   "mm",   "Bracket plate thickness"),
    ("bracket_w",         "40 mm",                  "mm",   "Bracket width along X"),
    ("bracket_l",         "40 mm",                  "mm",   "Bracket flange length along Y"),
    ("rfid_pad_W",        "30 mm",                  "mm",   "RFID pad width"),
    ("rfid_pad_D",        "15 mm",                  "mm",   "RFID pad depth"),
    ("rfid_pad_recess",   "0.4 mm",                 "mm",   "RFID pad recess depth"),
    ("align_pin_d",       "4 mm",                   "mm",   "Alignment-pin blind hole diameter"),
    ("align_pin_h",       "5 mm",                   "mm",   "Alignment-pin blind hole depth"),
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


def _build_body(design, comp):
    body_w = _val(design, "body_w")
    body_d = _val(design, "body_d")

    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-body_w / 2.0, -body_d / 2.0, 0),
        adsk.core.Point3D.create(body_w / 2.0, body_d / 2.0, 0),
    )
    inp = comp.features.extrudeFeatures.createInput(
        sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("body_h"))
    feat = comp.features.extrudeFeatures.add(inp)
    body = feat.bodies.item(0)
    body.name = "Manifold"
    return body


def _add_side_qdc(design, comp, body, side_sign, y_offset, z, name):
    """Add a QDC boss + thread bore on the +X (sign=+1) or -X (sign=-1) face."""
    body_w = _val(design, "body_w")
    boss_d = _val(design, "qdc_boss_d")
    boss_l = _val(design, "qdc_boss_l")
    bore_d = _val(design, "qdc_thread_clr")

    # Construction plane offset from YZ face by half body width.
    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(
        comp.yZConstructionPlane,
        adsk.core.ValueInput.createByReal(side_sign * body_w / 2.0),
    )
    plane = comp.constructionPlanes.add(plane_input)

    sketch = comp.sketches.add(plane)
    # Sketch local axes: x = Y_world, y = Z_world.
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(y_offset, z, 0), boss_d / 2.0
    )
    inp = comp.features.extrudeFeatures.createInput(
        sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
    )
    boss_dist = boss_l if side_sign > 0 else -boss_l
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(boss_dist))
    inp.participantBodies = [body]
    boss_feat = comp.features.extrudeFeatures.add(inp)

    # Bore through boss and into body for QDC threaded insert.
    bore_sketch = comp.sketches.add(plane)
    bore_sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(y_offset, z, 0), bore_d / 2.0
    )
    bore_inp = comp.features.extrudeFeatures.createInput(
        bore_sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation,
    )
    bore_depth = boss_l + body_w * 0.6  # входит в тело на ~60 % ширины
    bore_dist = bore_depth if side_sign > 0 else -bore_depth
    bore_inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(bore_dist))
    bore_inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(bore_inp)


def _add_rear_inlet(design, comp, body, x_offset, z, name):
    body_d = _val(design, "body_d")
    boss_d = _val(design, "rear_boss_d")
    boss_l = _val(design, "rear_boss_l")
    bore_d = _val(design, "rear_inlet_d")

    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(
        comp.xZConstructionPlane,
        adsk.core.ValueInput.createByReal(body_d / 2.0),
    )
    plane = comp.constructionPlanes.add(plane_input)

    sketch = comp.sketches.add(plane)
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(x_offset, z, 0), boss_d / 2.0
    )
    inp = comp.features.extrudeFeatures.createInput(
        sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(boss_l))
    inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(inp)

    bore_sketch = comp.sketches.add(plane)
    bore_sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(x_offset, z, 0), bore_d / 2.0
    )
    bore_inp = comp.features.extrudeFeatures.createInput(
        bore_sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation,
    )
    bore_inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(boss_l + body_d * 0.45))
    bore_inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(bore_inp)


def _add_top_rfid_pad(design, comp, body):
    body_h = _val(design, "body_h")
    pad_W = _val(design, "rfid_pad_W")
    pad_D = _val(design, "rfid_pad_D")
    recess = _val(design, "rfid_pad_recess")

    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByOffset(
        comp.xYConstructionPlane,
        adsk.core.ValueInput.createByReal(body_h),
    )
    plane = comp.constructionPlanes.add(plane_input)
    sketch = comp.sketches.add(plane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-pad_W / 2.0, -pad_D / 2.0, 0),
        adsk.core.Point3D.create(pad_W / 2.0, pad_D / 2.0, 0),
    )
    inp = comp.features.extrudeFeatures.createInput(
        sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.CutFeatureOperation,
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-recess))
    inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(inp)


def _add_alignment_blind_holes(design, comp, body):
    body_w = _val(design, "body_w")
    mount_pitch = _val(design, "mount_pitch")
    pin_d = _val(design, "align_pin_d")
    pin_h = _val(design, "align_pin_h")

    sketch = comp.sketches.add(comp.xYConstructionPlane)
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            cx = sx * (body_w / 2.0 - 5.0 / 10.0)  # 5 mm от кромки
            cy = sy * (mount_pitch / 2.0)
            sketch.sketchCurves.sketchCircles.addByCenterRadius(
                adsk.core.Point3D.create(cx, cy, 0), pin_d / 2.0
            )
    profs = adsk.core.ObjectCollection.create()
    for prof in sketch.profiles:
        profs.add(prof)
    inp = comp.features.extrudeFeatures.createInput(
        profs, adsk.fusion.FeatureOperations.CutFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(pin_h))
    inp.participantBodies = [body]
    comp.features.extrudeFeatures.add(inp)


def _build_bracket(design, root, name, y_position_cm):
    occ = _new_component(root, name)
    comp = occ.component
    bracket_t = _val(design, "bracket_t")
    bracket_w = _val(design, "bracket_w")
    bracket_l = _val(design, "bracket_l")
    hole_d = _val(design, "mount_hole_d")

    # Flange on XY plane.
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-bracket_w / 2.0, -bracket_l / 2.0, 0),
        adsk.core.Point3D.create(bracket_w / 2.0, bracket_l / 2.0, 0),
    )
    # 2 fastener holes per bracket (M4) along Y.
    for sy in (-1.0, 1.0):
        sketch.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(0, sy * (bracket_l / 2.0 - 8.0 / 10.0), 0),
            hole_d / 2.0,
        )

    # Pick the largest profile (rectangle minus the two holes).
    target = None
    largest = 0.0
    for prof in sketch.profiles:
        try:
            a = prof.areaProperties().area
        except Exception:
            continue
        if a > largest:
            largest = a
            target = prof
    if target is None:
        target = sketch.profiles.item(0)

    inp = comp.features.extrudeFeatures.createInput(
        target, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    inp.setDistanceExtent(False, adsk.core.ValueInput.createByString("bracket_t"))
    feat = comp.features.extrudeFeatures.add(inp)
    feat.bodies.item(0).name = name

    _move(occ, dy_cm=y_position_cm)
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
        design.rootComponent.name = "Miranda_RFV_Manifold"

        _ensure_params(design)

        root = design.rootComponent

        # Manifold body component.
        manifold_occ = _new_component(root, "Manifold")
        manifold_comp = manifold_occ.component
        body = _build_body(design, manifold_comp)

        # 4 side QDC ports: supply (upper) and return (lower) on each side.
        body_h = _val(design, "body_h")
        supply_z = _val(design, "qdc_supply_z") - body_h / 2.0
        return_z = _val(design, "qdc_return_z") - body_h / 2.0
        pitch_y = _val(design, "qdc_pitch_y")

        _add_side_qdc(design, manifold_comp, body, +1, +pitch_y / 2.0, supply_z, "QDC_R_Supply")
        _add_side_qdc(design, manifold_comp, body, +1, -pitch_y / 2.0, return_z, "QDC_R_Return")
        _add_side_qdc(design, manifold_comp, body, -1, +pitch_y / 2.0, supply_z, "QDC_L_Supply")
        _add_side_qdc(design, manifold_comp, body, -1, -pitch_y / 2.0, return_z, "QDC_L_Return")

        # 2 rear-facing inlets/outlets (centered on X, supply upper, return lower).
        _add_rear_inlet(design, manifold_comp, body, 0, supply_z, "Rear_Supply")
        _add_rear_inlet(design, manifold_comp, body, 0, return_z, "Rear_Return")

        _add_top_rfid_pad(design, manifold_comp, body)
        _add_alignment_blind_holes(design, manifold_comp, body)

        # Move the whole manifold to its target position in the chassis frame.
        centerline_y = _val(design, "centerline_y")
        bottom_clearance = _val(design, "bottom_clearance")
        _move(manifold_occ, dy_cm=centerline_y, dz_cm=bottom_clearance + body_h / 2.0)

        # Brackets attach beneath manifold ends along Y.
        mount_pitch = _val(design, "mount_pitch")
        _build_bracket(design, root, "Bracket_Front", centerline_y - mount_pitch / 2.0)
        _build_bracket(design, root, "Bracket_Rear", centerline_y + mount_pitch / 2.0)

        _export(design)
    except Exception:
        if ui is not None:
            ui.messageBox("Miranda RFV manifold script failed:\n" + traceback.format_exc())
        raise
