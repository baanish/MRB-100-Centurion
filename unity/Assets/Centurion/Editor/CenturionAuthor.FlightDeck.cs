using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Blueprinter;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Centurion.Editor
{
    // The Centurion's own flight deck (docs/COCKPIT-DESIGN.md), in place of the cloned Alkyon cockpit: the interior from
    // art/blender/cockpit/flightdeck.py's export in art/export_cockpit, drawn only in cockpit view, with the stock KR-67
    // sticks and throttles placed by reference on its pivots; the Darkreach's two
    // crew rigs with their ejection seats, the pilot (pilots[0], the player) on the left and the mission commander on the
    // right; four Canopies (the two escape hatches, the crew door, the cracking inner glass); and the checks that the
    // crew's way out through the hatches is clear of every collider. The cockpit part keeps the Alkyon's systems (its
    // AeroPart, AutopilotPlane, ControlsFilter and WeaponManager) and nothing of its art.
    public static partial class CenturionAuthor
    {
        private const string CockpitRoot = "flightdeck_int";
        private const string CockpitMeshFolder = ModFolder + "/Cockpit/Interior";
        private static string CockpitExportFolder => Path.Combine(RepoRoot, "art", "export_cockpit");
        private const string DarkreachPrefab = Stock + "GameObject/Darkreach_PLACEHOLDER.prefab";

        // The design's measurements (art/blender/flightdeck_layout.py): the pilot's eye, left of the centreline, and the
        // floor under it; the nose collider's notch height, which the cockpit's own collider stays under.
        private const float EyeStation = 6.55f, EyeOut = 0.55f, EyeHeight = 5.00f, FloorHeight = 3.75f, NotchHeight = 5.10f;
        // The cockpit part's collider: the flight deck's volume under the notch (stations, half width, heights).
        private const float CockpitBoxFore = 5.30f, CockpitBoxAft = 6.90f, CockpitBoxHalfWidth = 0.9f, CockpitBoxBottom = 3.80f, CockpitBoxTop = 5.05f;
        // The camera marker's opacity on the screen (owner: 25% was almost invisible; flightdeck.py MARKER_OPACITY).
        private const float MarkerOpacity = 0.5f;
        // The powered legends' glow over their emission map (the soft keys', caution and warning keys' and annunciators').
        private const float LegendGlow = 1.5f;
        // The flood light under the overhead between the seats: where, how far it reaches, how bright, its warm white.
        private const float FloodStation = 6.2f, FloodHeight = 5.05f, FloodRange = 2.6f, FloodIntensity = 1.5f;
        private static readonly Color FloodColour = new Color(1f, 0.95f, 0.88f);
        // The wing display's wing, the HUD span gauge's plan turned to hang down the page (canvas units, millimetres): its
        // millimetres per aircraft metre, which bring the extended tip to just over the percentage; where along the span
        // it leaves the page's top edge, outboard of the body the root sprite also draws; the station centred across it;
        // the width of the page it is clipped to, which leaves out the tail the root sprite draws aft of the wing.
        private const float WingDisplayMmPerMetre = 4.6f, WingDisplayTopSpan = 3.4f, WingDisplayCentreStation = 23f, WingDisplayClipWidth = 110f;
        private static readonly Color MfdGreen = new Color(0f, 1f, 0f, 1f);
        // The screen: a mod copy of the stock glass_int with its mirror finish off (docs/COCKPIT-DESIGN.md "Forward view").
        private static readonly Color ScreenTint = new Color(0.80f, 0.92f, 0.95f, 0.25f);
        private const float ScreenSmoothness = 0.2f;
        private const string CanopyBaseMap = "Texture2D_15033af04b7f42909945f09cd1b851a9";
        private const string CanopyMetallic = "Vector1_5ec4e4d573524154b63367e0518c1a6e";
        // Near-clear undamaged panes: a faint grime trace, no scratch relief or metallic mirror finish.
        // The stock crack map and Canopy-driven _Cracked_Amount remain independent of this finish.
        private const float CanopySmoothness = 0.2f, CanopyGrime = 0.02f;
        // Escape hatch Canopies (the Darkreach's canopy with the design's numbers): jettisoned mass, the force up the hatch's
        // own up axis and how long it pushes; the crew door's swing; the inner glass's cracking between the nose's hit
        // points 100 (none) and 70 (full), the Darkreach's.
        private const float HatchMass = 30f, HatchForce = 4000f, HatchFireTime = 0.2f, DoorOpenDeg = 100f, GlassCrackStart = 100f, GlassCrackFull = 70f;
        // The Alkyon's stick throw and a throttle lever's travel for the shorter Centurion levers.
        private const float StickRange = 6f, ThrottleRange = 40f;
        // The stock seat's rail (EjectionSeat.cs:75-111, the PilotDismounted nozzle's up in the cockpit frame, Unity axes:
        // +X right, +Y up, +Z forward; the same for both seats, since the nozzle sits in the PilotDismounted prefab placed at
        // each Pilot), its 1.5 m length, the last step where its colliders turn on (1.44 m), and the pilot capsule the escape
        // probe sweeps (radius, and its ends below and above the Pilot transform, caps included).
        private static readonly Vector3 SeatRail = new Vector3(-0.024f, 0.973f, 0.230f);
        private const float RailCollidable = 1.44f, RailEnd = 1.50f, CapsuleRadius = 0.25f, CapsuleBelow = 0.40f, CapsuleAbove = 0.90f;

        // Interior parts on layer 14 (structure the main camera also draws); the rest on 3, the cockpit layer the overlay
        // camera draws with its 1 cm near plane. As the stock cockpits put their tub and their near items.
        private static readonly HashSet<string> CockpitStructure = new HashSet<string> { CockpitRoot, "band_bezel", "labels", "hatch_liner_L", "hatch_liner_R" };
        // The lamps the stock CockpitWarningLights flashes on a missile warning: the interior's lenses (the caution keys',
        // the annunciators' and the master warning lamps' on the glareshield, flightdeck.py build_warning_lamps).
        // Never cockpit renderers, which the cockpit camera turns on as it enters: off until a warning.
        private static readonly HashSet<string> WarningLamps = new HashSet<string> { "warning_lenses" };

        private static Vector3 Prefab(Build b, float station, float height, float outLeft = 0f) =>
            new Vector3(-outLeft, height - b.Blockout.Origin.y, OriginStation - station - b.Blockout.Origin.z);

        // Runs after BuildEngines (the Cockpit's engine sources) and before BuildCockpitDisplay (its tac screen prefab).
        private static void BuildFlightDeck(Build b)
        {
            if (!File.Exists(Path.Combine(CockpitExportFolder, "blockout.json")))
                throw new FileNotFoundException("No flight deck export: run art/blender/cockpit/flightdeck.py and tools/export_blockout.py --out art/export_cockpit.",
                    Path.Combine(CockpitExportFolder, "blockout.json"));
            var interior = Blockout.Load(CockpitExportFolder, CockpitRoot);
            var cockpit = b.Parts["cockpit"];
            var aircraft = new SerializedObject(b.Aircraft);

            // The cockpit part at the middle of the deck floor, under the eyes, on the centreline: a bail-out's dismount
            // spots are measured from it (PilotDismounted.FindDismountSpot), and the camera takes its rotation.
            var oldCockpit = cockpit.GetComponentsInChildren(GameType("Cockpit"), true).Single();
            var cockpitComponent = (Component)cockpit.AddComponent(GameType("Cockpit"));
            EditorUtility.CopySerialized(oldCockpit, cockpitComponent);
            var tacScreenMaterial = Load<Material>(Stock + "Material/tacScreenDisplay_PLACEHOLDER.mat");
            var doomed = cockpit.transform.Cast<Transform>().Where(t => t.name != "CoM").Select(t => (Object)t.gameObject).ToList();
            var capsule = cockpit.GetComponent(GameType("EscapeCapsule"));
            if (capsule != null)
                doomed.Add(capsule); // it selects the whole-cockpit ejection even when disabled
            DestroyWithReferences(b, doomed);
            cockpit.transform.SetPositionAndRotation(Prefab(b, EyeStation, FloorHeight), Quaternion.identity);
            var interiorRoot = new GameObject(CockpitRoot) { layer = 14 };
            interiorRoot.transform.SetParent(cockpit.transform, false);
            AddCabinEngineSource(b, interiorRoot);

            // The cockpit's collider: the deck's volume under the notch, so it never closes the hatches' path.
            var box = cockpit.AddComponent<BoxCollider>();
            var lo = Prefab(b, CockpitBoxAft, CockpitBoxBottom, -CockpitBoxHalfWidth);
            var hi = Prefab(b, CockpitBoxFore, CockpitBoxTop, CockpitBoxHalfWidth);
            box.center = cockpit.transform.InverseTransformPoint((lo + hi) / 2);
            box.size = new Vector3(Mathf.Abs(hi.x - lo.x), hi.y - lo.y, Mathf.Abs(hi.z - lo.z));
            var com = cockpit.transform.Find("CoM");
            com.position = cockpit.transform.TransformPoint(box.center);

            // The interior's meshes and materials.
            BlueprinterAssets.EnsureFolder(CockpitMeshFolder);
            var meshes = ImportBlockout(interior, InteriorSlots(interior, tacScreenMaterial), CockpitExportFolder, CockpitMeshFolder);
            var renderers = new Dictionary<string, MeshRenderer>();
            foreach (var part in interior.Parts.Values.Where(p => p.Fbx != null).OrderBy(p => p.Name, StringComparer.Ordinal))
            {
                var go = part.Name == CockpitRoot ? interiorRoot : new GameObject(part.Name) { layer = CockpitStructure.Contains(part.Name) ? 14 : 3 };
                if (go != interiorRoot)
                    go.transform.SetParent(interiorRoot.transform, false);
                go.transform.SetPositionAndRotation(part.Pivot - b.Blockout.Origin, part.Rotation);
                go.AddComponent<MeshFilter>().sharedMesh = meshes[part.Name].Render;
                var renderer = go.AddComponent<MeshRenderer>();
                renderer.sharedMaterials = meshes[part.Name].Materials;
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                // Drawn only in cockpit view: the camera turns them on as it enters (Aircraft.SetCockpitRenderers), and
                // nothing turns them off at spawn, so they start off.
                renderer.enabled = false;
                renderers[part.Name] = renderer;
            }
            // The stock parts on the export's pivots (flightdeck.py stock_pivots), by reference: each pivot names its stock
            // mesh and material and whether it is mirrored for the hand that works it (a negative X scale).
            foreach (var part in interior.Parts.Values.Where(p => p.Fbx == null && p.Props.ContainsKey("stock_mesh")).OrderBy(p => p.Name, StringComparer.Ordinal))
            {
                var go = new GameObject(part.Name) { layer = 3 };
                go.transform.SetParent(interiorRoot.transform, false);
                go.transform.SetPositionAndRotation(part.Pivot - b.Blockout.Origin, part.Rotation);
                if (Convert.ToInt32(part.Props["mirror"]) != 0)
                    go.transform.localScale = new Vector3(-1f, 1f, 1f);
                go.AddComponent<MeshFilter>().sharedMesh = Load<Mesh>(Stock + "Mesh/" + (string)part.Props["stock_mesh"] + "_PLACEHOLDER.asset");
                var renderer = go.AddComponent<MeshRenderer>();
                renderer.sharedMaterial = Load<Material>(Stock + "Material/" + (string)part.Props["stock_material"] + "_PLACEHOLDER.mat");
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                renderer.enabled = false;
                renderers[part.Name] = renderer;
            }
            AuthorWingDisplay(b, interior.Parts["wing_display"], interiorRoot.transform);
            var lamps = (Component)interiorRoot.AddComponent(GameType("CockpitWarningLights"));
            var lampSo = new SerializedObject(lamps);
            var lightRenderers = Prop(lampSo, "lightRenderers");
            var lampNames = WarningLamps.OrderBy(n => n, StringComparer.Ordinal).ToArray();
            lightRenderers.arraySize = lampNames.Length;
            for (var i = 0; i < lampNames.Length; i++)
                lightRenderers.GetArrayElementAtIndex(i).objectReferenceValue = renderers[lampNames[i]];
            Prop(lampSo, "aircraft").objectReferenceValue = b.Aircraft;
            lampSo.ApplyModifiedPropertiesWithoutUndo();

            // The flood light: the stock cockpits take the sun through bubble canopies, and the enclosed flight deck mostly
            // can't, so its panels sat in shade near black (sRGB 23 against the Darkreach's sunlit 119). A dim, shadowless
            // point light under the overhead lights the cockpit layers only.
            var flood = new GameObject("cockpit_flood") { layer = 3 }.AddComponent<Light>();
            flood.transform.SetParent(interiorRoot.transform, false);
            flood.transform.position = Prefab(b, FloodStation, FloodHeight);
            flood.type = LightType.Point;
            flood.range = FloodRange;
            flood.intensity = FloodIntensity;
            flood.color = FloodColour;
            flood.shadows = LightShadows.None;
            flood.cullingMask = (1 << 3) | (1 << 14);
            flood.renderMode = LightRenderMode.Auto;

            // The crew: the Darkreach's pilot and WSO rigs with their seats, the pilot left with the stock helmet camera point
            // on the design eye, the mission commander mirrored right.
            var crew = AuthorCrew(b, cockpit);
            var helmet = FindDeep(crew[0].transform, "helmetCamPoint");
            Prop(aircraft, "cockpitViewPoint").objectReferenceValue = helmet;
            var pilots = Prop(aircraft, "pilots");
            pilots.arraySize = crew.Length;
            for (var i = 0; i < crew.Length; i++)
                pilots.GetArrayElementAtIndex(i).objectReferenceValue = crew[i];

            // The Cockpit on the new interior: its sidesticks, the two throttles on the pedestal, the tac screen's faces.
            var so = new SerializedObject(cockpitComponent);
            Prop(so, "aircraft").objectReferenceValue = b.Aircraft;
            Prop(so, "tacScreenRender").objectReferenceValue = renderers["tacScreen"];
            var sticks = Prop(so, "joysticks");
            sticks.arraySize = 2;
            foreach (var (i, name) in new[] { (0, "stick_L"), (1, "stick_R") })
            {
                sticks.GetArrayElementAtIndex(i).FindPropertyRelative("transform").objectReferenceValue = renderers[name].transform;
                sticks.GetArrayElementAtIndex(i).FindPropertyRelative("range").floatValue = StickRange;
            }
            var throttles = Prop(so, "throttles");
            throttles.arraySize = 2;
            foreach (var (i, name) in new[] { (0, "throttle_1"), (1, "throttle_2") })
            {
                var t = throttles.GetArrayElementAtIndex(i);
                t.FindPropertyRelative("rotation").boolValue = true;
                t.FindPropertyRelative("motion").boolValue = false;
                t.FindPropertyRelative("transform").objectReferenceValue = renderers[name].transform;
                t.FindPropertyRelative("range").floatValue = ThrottleRange;
            }
            var fans = b.Root.GetComponentsInChildren(GameType("Turbofan"), true).Select(f => f.gameObject).OrderBy(g => g.name, StringComparer.Ordinal).ToArray();
            var sources = Prop(so, "engineSources");
            sources.arraySize = fans.Length;
            for (var i = 0; i < fans.Length; i++)
                sources.GetArrayElementAtIndex(i).objectReferenceValue = fans[i];
            so.ApplyModifiedPropertiesWithoutUndo();

            foreach (var targetCam in b.Root.GetComponentsInChildren(GameType("TargetCam"), true))
                Set(targetCam, "targetScreenRenderer", renderers["tacScreen"]);

            // The exits and the inner glass, each a Canopy (listed: Aircraft.canopies is serialized, never scanned).
            var canopies = AuthorExits(b, renderers["glass_int"]);
            var listed = Prop(aircraft, "canopies");
            listed.arraySize = canopies.Count;
            for (var i = 0; i < canopies.Count; i++)
                listed.GetArrayElementAtIndex(i).objectReferenceValue = canopies[i];

            // Each escape hatch's liner and handle go with the hatch when it jettisons.
            foreach (var side in new[] { "L", "R" })
                renderers["hatch_liner_" + side].transform.SetParent(b.Visuals["nose_hatch_" + side], true);

            // Cockpit view: the interior on, its warning lamps left to CockpitWarningLights; the nose and radar fairing off
            // (PlaceSystems lists them).
            var cockpitList = Prop(aircraft, "cockpitRenderers");
            var ordered = renderers.Where(r => !WarningLamps.Contains(r.Key)).OrderBy(r => r.Key, StringComparer.Ordinal).Select(r => r.Value).ToArray();
            cockpitList.arraySize = ordered.Length;
            for (var i = 0; i < ordered.Length; i++)
                cockpitList.GetArrayElementAtIndex(i).objectReferenceValue = ordered[i];
            aircraft.ApplyModifiedPropertiesWithoutUndo();

            var eye = Prefab(b, EyeStation, EyeHeight, EyeOut);
            var tris = renderers.Values.Sum(r => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3);
            b.Report.Add($"flight deck: {ordered.Length} cockpit renderers, {tris} triangles (G4.1: at most 36,000); eye at {helmet.position} " +
                $"({(helmet.position - eye).magnitude * 100:F1} cm from the design eye {eye}); crew [{string.Join(", ", crew.Select(c => c.name))}]; " +
                $"canopies [{string.Join(", ", canopies.Select(c => c.name))}]; cockpit collider {box.size} at {box.transform.TransformPoint(box.center)}");
            if (tris > 36000)
                throw new InvalidDataException($"The flight deck draws {tris} triangles; G4.1 allows 36,000");
            if ((helmet.position - eye).magnitude > 0.01f)
                throw new InvalidDataException($"The pilot's helmet camera point sits at {helmet.position}, not the design eye {eye}");
            CheckWarningLamps(b, lampNames.Select(n => (Object)renderers[n].gameObject).Append(lamps));
            var glass = renderers["glass_int"].sharedMaterial;
            var stockGlass = Load<Material>(Stock + "Material/FastBomber1_glass_int_PLACEHOLDER.mat");
            if (glass.GetTexture(CanopyBaseMap) != ImportExportTexture(interior, "cockpit_glass.png", true, false, CockpitExportFolder)
                || glass.shader != stockGlass.shader || !glass.HasProperty("_Cracked_Amount")
                || glass.GetFloat("_Cracked_Amount") != 0f
                || glass.GetFloat(CanopyMetallic) != 0f || glass.GetFloat("_Smoothness") != CanopySmoothness
                || glass.GetFloat("_Grime_Intensity") != CanopyGrime || glass.GetFloat("_Scratches_Intensity") != 0f)
                throw new InvalidDataException("Inner glass must use the uniform cockpit_glass tint and stock cracking shader, with metallic 0, smoothness 0.2, grime 0.02, scratches 0 and no initial cracks.");
            foreach (var map in new[] { "_Grime", "_SampleTexture2D_51ab9e981153496b807052eb4be84d33_Texture_1_Texture2D", "_SampleTexture2D_5415c280ead44b35b01bd558db4d1a80_Texture_1_Texture2D" })
                if (!glass.GetTexture(map) || glass.GetTexture(map) != stockGlass.GetTexture(map))
                    throw new InvalidDataException($"Inner glass must preserve the stock grime, crack and scratch maps: {map}");
            if (glass.GetVector("_Cracks_Tiling") != stockGlass.GetVector("_Cracks_Tiling"))
                throw new InvalidDataException("Inner glass must preserve the stock crack tiling.");
        }

        // Controller references catch unnamed lamps; mesh/material names catch lamps left behind without a controller.
        private static HashSet<Object> WarningLampObjects(GameObject root)
        {
            var objects = new HashSet<Object>();
            foreach (var (type, field) in new[] { ("CockpitWarningLights", "lightRenderers"), ("MissileWarningLight", "images") })
                foreach (var controller in root.GetComponentsInChildren(GameType(type), true))
                {
                    objects.Add(controller);
                    if (type == "MissileWarningLight")
                        objects.Add(controller.gameObject);
                    var targets = Prop(new SerializedObject(controller), field);
                    for (var i = 0; i < targets.arraySize; i++)
                        if (targets.GetArrayElementAtIndex(i).objectReferenceValue is Component target)
                            objects.Add(target.gameObject);
                }
            foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
            {
                var mesh = renderer is SkinnedMeshRenderer skinned ? skinned.sharedMesh
                    : renderer.TryGetComponent(out MeshFilter filter) ? filter.sharedMesh : null;
                if (renderer.GetComponentsInParent<Transform>(true).Any(t => IsWarningLampName(t.name) || IsWarningLampName(t.tag))
                    || (mesh != null && IsWarningLampName(mesh.name))
                    || renderer.sharedMaterials.Any(m => m != null && IsWarningLampName(m.name)))
                    objects.Add(renderer.gameObject);
            }
            return objects;
        }

        private static bool IsWarningLampName(string name)
        {
            var key = name.Replace("_", "").Replace("-", "").Replace(" ", "").ToLowerInvariant();
            return key.Contains("missilewarning") || key.Contains("warninglight") || key.Contains("warninglamp")
                || key.Contains("warninglens") || key.Contains("warningstrip") || key.Contains("missilethreatlight");
        }

        private static void CheckWarningLamps(Build b, IEnumerable<Object> allowed)
        {
            var unexpected = WarningLampObjects(b.Root).Except(allowed).Select(o =>
                o is Component c ? $"{PathOf(c.transform, b.Root.transform)}:{c.GetType().Name}" : PathOf(((GameObject)o).transform, b.Root.transform)).ToArray();
            if (unexpected.Length > 0)
                throw new InvalidDataException("Stock missile warning lamps remain outside the flight deck's own set: " + string.Join(", ", unexpected));
        }

        // The wing display's page (flightdeck.py wing_canvas): a world-space canvas, a millimetre to the unit, off until
        // src/Centurion/WingDisplay.cs turns it on with the interior. Its "page" carries a copy of the HUD span gauge's plan
        // (AuthorSpanGaugeHud: the root sprite, each stage's Filled sprite and its ends), turned so the right wing hangs
        // from the page's top edge with the nose to the right, in MFD green; the plugin clips it to the page (the body
        // outboard of the top edge's span is cut off), slides its stages as the gauge does, and writes the percentage and
        // the word from one line of the stock tac screen's MFD text, inactive here, that it copies.
        private static void AuthorWingDisplay(Build b, BlockoutPart page, Transform interiorRoot)
        {
            var canvasObject = new GameObject("wing_display", typeof(RectTransform)) { layer = 3 };
            var rect = (RectTransform)canvasObject.transform;
            rect.SetParent(interiorRoot, false);
            rect.SetPositionAndRotation(page.Pivot - b.Blockout.Origin, page.Rotation);
            rect.sizeDelta = new Vector2(Convert.ToSingle(page.Props["canvas_w"]), Convert.ToSingle(page.Props["canvas_h"])) * 1000f;
            rect.localScale = Vector3.one * 0.001f;
            var canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.enabled = false;

            var pageRect = (RectTransform)new GameObject("page", typeof(RectTransform)).transform;
            pageRect.SetParent(rect, false);
            pageRect.anchorMin = new Vector2(0.5f, 0f);
            pageRect.anchorMax = new Vector2(0.5f, 1f);
            pageRect.sizeDelta = new Vector2(WingDisplayClipWidth, 0f);
            var plan = (RectTransform)Object.Instantiate(FindDeep(Load<GameObject>(HudExtrasPath).transform, "wingPivot").gameObject, pageRect).transform;
            plan.name = "plan";
            plan.anchorMin = plan.anchorMax = new Vector2(0.5f, 0.5f);
            plan.localRotation = Quaternion.Euler(0f, 0f, -90f);
            plan.localScale = Vector3.one * (WingDisplayMmPerMetre / SpanGaugeUnitsPerMetre);
            plan.localPosition = new Vector3((WingDisplayCentreStation - OriginStation) * WingDisplayMmPerMetre,
                rect.sizeDelta.y / 2f + WingDisplayTopSpan * WingDisplayMmPerMetre, 0f);
            foreach (var image in plan.GetComponentsInChildren<Behaviour>(true).Where(c => c.GetType().Name == "Image" && c.enabled))
            {
                var so = new SerializedObject(image);
                Prop(so, "m_Color").colorValue = MfdGreen;
                so.ApplyModifiedPropertiesWithoutUndo();
            }

            var text = (RectTransform)Object.Instantiate(FindDeep(Load<GameObject>(DonorTacScreen).transform, "Title TWR").gameObject, rect).transform;
            text.name = "text";
            text.anchorMin = text.anchorMax = text.pivot = new Vector2(0.5f, 0.5f);
            text.localPosition = Vector3.zero;
            text.localRotation = Quaternion.identity;
            text.localScale = Vector3.one;
            text.gameObject.SetActive(false);
            var font = new SerializedObject(text.GetComponents<Component>().Single(c => c.GetType().Name == "TextMeshProUGUI")).FindProperty("m_fontAsset");
            if (font == null || font.objectReferenceValue == null)
                throw new InvalidDataException("The wing display's MFD text template has no font asset: the plugin's lines would draw nothing.");
            foreach (var t in canvasObject.GetComponentsInChildren<Transform>(true))
                t.gameObject.layer = 3;
        }

        // The interior's material slots: its three atlases and the switch kit's on opaque Lit copies, the legends on a
        // cutout copy that glows where its emission map is lit, the stock shared materials by reference (aircraft_structure
        // tinted by the export's vertex colour, Matte_black, hotas, CockpitWarningLight), the stock tac screen and canopy
        // glass, and the screen and its camera marker on mod copies of the stock glass_int.
        private static Dictionary<string, Material> InteriorSlots(Blockout interior, Material tacScreen)
        {
            Material Atlas(string name, string stem)
            {
                var atlas = OpaqueLit(SlotMaterials["jet_mechanical"], name);
                atlas.SetTexture("_BaseMap", ImportExportTexture(interior, stem + "_b.png", true, false, CockpitExportFolder));
                atlas.SetTexture("_MainTex", atlas.GetTexture("_BaseMap"));
                atlas.SetTexture("_MetallicGlossMap", ImportExportTexture(interior, stem + "_m.png", false, false, CockpitExportFolder));
                atlas.EnableKeyword("_METALLICSPECGLOSSMAP");
                atlas.SetFloat("_Smoothness", 1f); // the map's alpha carries it
                atlas.SetTexture("_BumpMap", ImportExportTexture(interior, stem + "_n.png", false, true, CockpitExportFolder));
                atlas.EnableKeyword("_NORMALMAP");
                atlas.SetTexture("_OcclusionMap", ImportExportTexture(interior, stem + "_ao.png", false, false, CockpitExportFolder));
                atlas.EnableKeyword("_OCCLUSIONMAP");
                return SaveAsset(atlas, SkinFolder + "/" + name + ".mat");
            }

            // The stencils: alpha-clipped at half coverage, and nothing else, so the material takes the game's alpha-test Lit
            // variant (camonet's keywords): with emission too it fell to a variant without the clip, and every legend's
            // quad drew whole, as a grey bar.
            var labels = new Material(Load<Material>(SlotMaterials["jet_mechanical"])) { name = "Centurion_cockpit_labels" };
            var legends = ImportExportTexture(interior, "cockpit_labels_b.png", true, false, CockpitExportFolder);
            labels.SetTexture("_BaseMap", legends);
            labels.SetTexture("_MainTex", legends);
            labels.SetColor("_BaseColor", Color.white);
            labels.SetColor("_Color", Color.white);
            labels.SetFloat("_AlphaClip", 1f);
            labels.SetFloat("_Cutoff", 0.5f);
            labels.EnableKeyword("_ALPHATEST_ON");
            labels.SetOverrideTag("RenderType", "TransparentCutout");
            labels.renderQueue = (int)UnityEngine.Rendering.RenderQueue.AlphaTest;
            labels.SetTexture("_MetallicGlossMap", null);
            labels.DisableKeyword("_METALLICSPECGLOSSMAP");
            labels.SetFloat("_Metallic", 0f);
            labels.SetFloat("_Smoothness", 0.3f);
            labels.SetTexture("_BumpMap", null);
            labels.DisableKeyword("_NORMALMAP");
            labels.SetTexture("_OcclusionMap", null);
            labels.DisableKeyword("_OCCLUSIONMAP");
            labels.DisableKeyword("_EMISSION");

            // The powered legends (the soft keys', the caution and warning keys', the annunciators'): the stock warning
            // lamp's transparent, emissive material with the legend atlas as its coverage and glow, a variant the game ships.
            var lit = new Material(Load<Material>(Stock + "Material/CockpitWarningLight_PLACEHOLDER.mat")) { name = "Centurion_cockpit_legends" };
            lit.SetTexture("_BaseMap", legends);
            lit.SetTexture("_MainTex", legends);
            lit.SetColor("_BaseColor", Color.white);
            lit.SetColor("_Color", Color.white);
            lit.SetTexture("_EmissionMap", ImportExportTexture(interior, "cockpit_labels_e.png", true, false, CockpitExportFolder));
            lit.SetColor("_EmissionColor", Color.white * LegendGlow);
            lit.globalIlluminationFlags = MaterialGlobalIlluminationFlags.None;

            Material Screen(string name, string map, Color colour)
            {
                var m = new Material(Load<Material>(Stock + "Material/glass_int_PLACEHOLDER.mat")) { name = name };
                var texture = ImportExportTexture(interior, map, true, false, CockpitExportFolder);
                m.SetTexture("_BaseMap", texture);
                m.SetTexture("_MainTex", texture);
                m.SetTexture("_MetallicGlossMap", null);
                m.DisableKeyword("_METALLICSPECGLOSSMAP");
                m.SetColor("_BaseColor", colour);
                m.SetColor("_Color", colour);
                m.SetFloat("_Metallic", 0f);
                m.SetFloat("_Smoothness", ScreenSmoothness);
                return SaveAsset(m, SkinFolder + "/" + name + ".mat");
            }

            var glass = new Material(Load<Material>(Stock + "Material/FastBomber1_glass_int_PLACEHOLDER.mat")) { name = "Centurion_canopy_int" };
            glass.SetTexture(CanopyBaseMap, ImportExportTexture(interior, "cockpit_glass.png", true, false, CockpitExportFolder));
            glass.SetFloat(CanopyMetallic, 0f);
            glass.SetFloat("_Smoothness", CanopySmoothness);
            glass.SetFloat("_Grime_Intensity", CanopyGrime);
            glass.SetFloat("_Scratches_Intensity", 0f);

            return new Dictionary<string, Material>
            {
                { "Centurion_cockpit_panel", Atlas("Centurion_cockpit_panel", "cockpit_panel") },
                { "Centurion_cockpit_console", Atlas("Centurion_cockpit_console", "cockpit_console") },
                { "Centurion_cockpit_shell", Atlas("Centurion_cockpit_shell", "cockpit_shell") },
                { "Centurion_cockpit_kit", Atlas("Centurion_cockpit_kit", "cockpit_kit") },
                { "Centurion_cockpit_labels", SaveAsset(labels, SkinFolder + "/Centurion_cockpit_labels.mat") },
                { "Centurion_cockpit_legends", SaveAsset(lit, SkinFolder + "/Centurion_cockpit_legends.mat") },
                { "aircraft_structure", Load<Material>(SlotMaterials["aircraft_structure"]) },
                { "Matte_black", Load<Material>(Stock + "Material/Matte_black_PLACEHOLDER.mat") },
                { "hotas", Load<Material>(Stock + "Material/hotas_PLACEHOLDER.mat") },
                { "CockpitWarningLight", Load<Material>(Stock + "Material/CockpitWarningLight_PLACEHOLDER.mat") },
                { "tacScreenDisplay", tacScreen },
                { "canopy_int", SaveAsset(glass, SkinFolder + "/Centurion_canopy_int.mat") },
                { "Centurion_band", Screen("Centurion_band", "cockpit_band.png", ScreenTint) },
                { "Centurion_band_marker", Screen("Centurion_band_marker", "cockpit_marker.png", new Color(1f, 1f, 1f, MarkerOpacity)) },
            };
        }

        // The Darkreach's Pilot and WSO, each with its rig and seat, under the cockpit: the pilot's helmet camera point on
        // the design eye, the WSO (the mission commander) mirrored across the centreline. References the copies keep to the
        // Darkreach (its Aircraft, cockpit part and trimmer) are rebound to the Centurion's.
        private static Component[] AuthorCrew(Build b, GameObject cockpit)
        {
            var stock = Load<GameObject>(DarkreachPrefab);
            var pilotType = GameType("Pilot");
            var part = cockpit.GetComponent(GameType("AeroPart"));
            var trimmer = cockpit.GetComponent(GameType("ControlsFilter"));
            var crew = new List<Component>();
            foreach (var name in new[] { "Pilot", "WSO" })
            {
                var go = Object.Instantiate(stock.transform.Find("fuselage_F/cockpit/" + name).gameObject, cockpit.transform, false);
                go.name = name;
                go.transform.localRotation = Quaternion.identity;
                foreach (var component in go.GetComponentsInChildren<Component>(true))
                {
                    var so = new SerializedObject(component);
                    var it = so.GetIterator();
                    while (it.Next(true))
                    {
                        if (it.propertyType != SerializedPropertyType.ObjectReference || it.objectReferenceValue == null
                            || AssetDatabase.GetAssetPath(it.objectReferenceValue) != DarkreachPrefab)
                            continue;
                        var target = it.objectReferenceValue.GetType().Name;
                        it.objectReferenceValue = target == "Aircraft" ? b.Aircraft : target == "AeroPart" || target == "UnitPart" ? part
                            : target == "ControlsFilter" ? trimmer : null;
                        if (it.objectReferenceValue == null)
                            b.Report.Add($"cleared {name}/{component.GetType().Name}.{it.propertyPath}: it pointed at the Darkreach's {target}");
                    }
                    so.ApplyModifiedPropertiesWithoutUndo();
                }
                var pilot = go.GetComponent(pilotType);
                var ps = new SerializedObject(pilot);
                Prop(ps, "ejectionSeat").boolValue = true;
                // Both bail out left, beside the crew door (PilotDismounted.FindDismountSpot: Left is 0).
                Prop(ps, "exitDirection").intValue = 0;
                ps.ApplyModifiedPropertiesWithoutUndo();
                crew.Add(pilot);
            }
            var helmet = FindDeep(crew[0].transform, "helmetCamPoint");
            crew[0].transform.position += Prefab(b, EyeStation, EyeHeight, EyeOut) - helmet.position;
            var p = crew[0].transform.position;
            crew[1].transform.position = new Vector3(-p.x, p.y, p.z);
            return crew.ToArray();
        }

        // The escape hatches over the seats (Canopies that jettison their panel up the hatch's normal), the crew door (a
        // hinge-only Canopy that swings it out on the ground and in the preview) and the inner glass (a Canopy that only
        // cracks with the nose's damage). Returns them in Aircraft.canopies' order.
        private static List<Component> AuthorExits(Build b, Renderer innerGlass)
        {
            var canopyType = GameType("Canopy");
            var nose = b.Parts["nose"].transform;
            var nosePart = b.Part("nose");
            var stockCanopy = Load<GameObject>(DarkreachPrefab).transform.Find("fuselage_F/cockpit/canopyHingea/canopyHingeb/canopyFrame").GetComponent(canopyType);
            var jettisonSound = new SerializedObject(stockCanopy).FindProperty("ejectSound").objectReferenceValue;
            var result = new List<Component>();

            Component Canopy(GameObject host)
            {
                var canopy = host.AddComponent(canopyType);
                var so = new SerializedObject(canopy);
                Prop(so, "attachedPart").objectReferenceValue = nosePart;
                Prop(so, "ejectSound").objectReferenceValue = jettisonSound;
                Num(so, "openSpeed", 1);
                Num(so, "glassDamageThreshold", GlassCrackStart);
                Num(so, "glassDamageLimit", GlassCrackFull);
                Prop(so, "canopyHinges").arraySize = 0;
                Prop(so, "glassRenderers").arraySize = 0;
                so.ApplyModifiedPropertiesWithoutUndo();
                result.Add(canopy);
                return canopy;
            }

            // Hatches: each panel jettisons as itself, its collider (off until then) a box over the panel above the notch, so
            // it starts clear of the nose's collider.
            foreach (var side in new[] { "L", "R" })
            {
                var name = "nose_hatch_" + side;
                AddVisual(b, name, nose);
                var panel = b.Visuals[name];
                var bounds = panel.GetComponent<MeshRenderer>().bounds;
                var floor = Mathf.Max(bounds.min.y, NotchHeight - b.Blockout.Origin.y + 0.01f);
                var collider = panel.gameObject.AddComponent<BoxCollider>();
                collider.center = panel.InverseTransformPoint(new Vector3(bounds.center.x, (floor + bounds.max.y) / 2, bounds.center.z));
                collider.size = new Vector3(bounds.size.x, bounds.max.y - floor, bounds.size.z);
                collider.enabled = false;
                var so = new SerializedObject(Canopy(panel.gameObject));
                Prop(so, "ejectionTransform").objectReferenceValue = panel;
                Prop(so, "ejectionCollider").objectReferenceValue = collider;
                Num(so, "mass", HatchMass);
                Prop(so, "ejectionForce").vector3Value = new Vector3(0, HatchForce, 0);
                Prop(so, "forcePosition").vector3Value = Vector3.zero;
                Num(so, "fireTime", HatchFireTime);
                so.ApplyModifiedPropertiesWithoutUndo();
            }

            // The crew door: CanopyHinge turns its transform's localEulerAngles.x (Canopy.cs:18), so the hinge sits at
            // identity under a mount whose local X runs up the door's forward edge (the blockout's nose_door frame), and
            // the panel under the hinge. The swing is whichever sign takes the door out of the side.
            var mount = new GameObject("nose_door") { layer = b.Root.layer }.transform;
            mount.SetParent(nose, false);
            mount.SetPositionAndRotation(b.Blockout.Local("nose_door"), b.Blockout.Rotation("nose_door"));
            var hinge = new GameObject("nose_door_hinge") { layer = b.Root.layer }.transform;
            hinge.SetParent(mount, false);
            AddVisual(b, "nose_door_visible", hinge);
            b.Visuals["nose_door"] = mount;
            var door = b.Visuals["nose_door_visible"].GetComponent<MeshRenderer>();
            float Outboard(float angle)
            {
                hinge.localEulerAngles = Vector3.right * angle;
                return door.bounds.center.x; // the door is on the left, -X: more negative is further out
            }
            var swing = Outboard(DoorOpenDeg) < Outboard(-DoorOpenDeg) ? DoorOpenDeg : -DoorOpenDeg;
            var openAt = door.bounds.center;
            hinge.localRotation = Quaternion.identity;
            var doorCanopy = new SerializedObject(Canopy(mount.gameObject));
            var hinges = Prop(doorCanopy, "canopyHinges");
            hinges.arraySize = 1;
            hinges.GetArrayElementAtIndex(0).FindPropertyRelative("transform").objectReferenceValue = hinge;
            hinges.GetArrayElementAtIndex(0).FindPropertyRelative("hingeAngle").floatValue = swing;
            doorCanopy.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"crew door: hinge {swing:+0;-0} deg about {mount.right} at {mount.position}; open, its middle at {openAt} (closed {door.bounds.center})");

            // The inner panes crack with the nose's damage, as the Darkreach's canopy does.
            var glass = new SerializedObject(Canopy(innerGlass.gameObject));
            var panes = Prop(glass, "glassRenderers");
            panes.arraySize = 1;
            panes.GetArrayElementAtIndex(0).objectReferenceValue = innerGlass;
            glass.ApplyModifiedPropertiesWithoutUndo();
            return result;
        }

        // docs/COCKPIT-DESIGN.md "Escape": each seat's capsule (and its rider) at the rail's last steps, where the seat and
        // pilot colliders turn on, and each hatch's collider as it jettisons, against every enabled aircraft collider, the
        // cockpit part's included. The stock overlap check skips disabled colliders and same-part pairs, so it can't see this.
        private static List<string> EscapeProbe(Build b)
        {
            var problems = new List<string>();
            var crewColliders = new HashSet<Collider>(b.Root.GetComponentsInChildren(GameType("Pilot"), true).SelectMany(p => p.GetComponentsInChildren<Collider>(true)));
            var hatches = new[] { "nose_hatch_L", "nose_hatch_R" }.Select(n => b.Visuals[n].GetComponent<BoxCollider>()).ToArray();
            var airframe = b.Root.GetComponentsInChildren<Collider>(true)
                .Where(c => c.enabled && !c.isTrigger && !crewColliders.Contains(c) && !(c is MeshCollider m && m.sharedMesh == null)).ToArray();
            var probe = new GameObject("escape_probe").AddComponent<CapsuleCollider>();
            try
            {
                probe.radius = CapsuleRadius;
                probe.height = CapsuleBelow + CapsuleAbove;
                probe.center = new Vector3(0, (CapsuleAbove - CapsuleBelow) / 2, 0);
                foreach (var pilot in b.Root.GetComponentsInChildren(GameType("Pilot"), true))
                    foreach (var rail in new[] { RailCollidable, RailEnd })
                    {
                        probe.transform.position = pilot.transform.position + SeatRail * rail;
                        Physics.SyncTransforms();
                        foreach (var c in airframe)
                            if (Physics.ComputePenetration(probe, probe.transform.position, probe.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth) && depth > 0.001f)
                                problems.Add($"escape: {pilot.name}'s capsule at {rail} m up the rail overlaps {PathOf(c.transform, b.Root.transform)} by {depth:F3} m");
                    }
                foreach (var hatch in hatches)
                {
                    hatch.enabled = true;
                    Physics.SyncTransforms();
                    foreach (var c in airframe)
                        if (Physics.ComputePenetration(hatch, hatch.transform.position, hatch.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth) && depth > 0.001f)
                            problems.Add($"escape: {hatch.name}'s jettison collider overlaps {PathOf(c.transform, b.Root.transform)} by {depth:F3} m");
                    hatch.enabled = false;
                }
                b.Report.Add($"escape probe: both capsules at {RailCollidable} and {RailEnd} m up the rail and both hatch colliders clear of {airframe.Length} airframe colliders" +
                    (problems.Count == 0 ? "" : $" ({problems.Count} overlaps)"));
            }
            finally
            {
                Object.DestroyImmediate(probe.gameObject);
            }
            return problems;
        }
    }
}
