using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Centurion.Editor
{
    // The Centurion's own line art in the cockpit and the HUD, all from art/blender/status_silhouette.py: the tac screen
    // (the MFD the borrowed Alkyon cockpit instantiates, Cockpit.tacScreenUIPrefab) with its two engines, its top view and
    // its four hardpoint sets; the HUD's span gauge; and the HUD's damage diagram.
    public static partial class CenturionAuthor
    {
        private const string DonorTacScreen = Stock + "GameObject/tacScreen_fastBomber1_PLACEHOLDER.prefab";
        private const string TacScreenPath = ModFolder + "/Centurion_TacScreen.prefab";
        // The generator's sprites and the JSON that places them, in metres (x outboard along the right wing, s the station).
        private const string CockpitArtFolder = ModFolder + "/Cockpit";
        private const string StatusSilhouettePath = CockpitArtFolder + "/centurion_status_top.png";
        private const string StatusFramingPath = CockpitArtFolder + "/centurion_status_top.json";
        private const string SpanLayoutPath = CockpitArtFolder + "/centurion_span.json";
        private const string DamageLayoutPath = CockpitArtFolder + "/centurion_damage.json";
        // The span gauge's plan under the gauge's scaler: units per metre, at which the 45 m body stands as tall as the
        // Alkyon's fuselage art did and the extended wing reaches about as far as the stage bar it replaces, and where
        // the centreline at the origin station sits, left of the gauge's centre so the wing runs out to the right.
        private const float SpanGaugeUnitsPerMetre = 2.75f;
        private static readonly Vector2 SpanGaugePlanOrigin = new Vector2(-20f, 4.7f);

        // Reads the Turbofans and the hardpoint sets, so it runs after BuildEngines and BuildBays.
        private static void BuildCockpitDisplay(Build b)
        {
            var cockpit = b.Parts["cockpit"].GetComponentsInChildren(GameType("Cockpit"), true).Single();
            var screen = (GameObject)Object.Instantiate(Load<GameObject>(DonorTacScreen));
            try
            {
                screen.name = Path.GetFileNameWithoutExtension(TacScreenPath);
                var edit = new Build { Root = screen };
                DestroyWithReferences(edit, WarningLampObjects(screen).ToList());
                CheckWarningLamps(edit, Array.Empty<Object>());
                ShowEngines(b, edit);
                ShowHardpoints(b, edit);
                b.Report.AddRange(edit.Report);
                Set(cockpit, "tacScreenUIPrefab", SavePrefab(screen, TacScreenPath));
            }
            finally
            {
                Object.DestroyImmediate(screen);
            }
        }

        // Each EngineTelemetry names the engine it reads; the Alkyon's engines 3 and 4 are gone, so their gauges go and so
        // does a panel left with none. The panels keep their places: the cockpit maps regions of the screen's canvas onto
        // separate display tiles, and the Alkyon's two engine panels sit on two tiles side by side. The thrust dials end at
        // the most a Turbofan gives (static thrust at the speed curve's peak), where the Alkyon's ended at twice its 45 kN.
        private static void ShowEngines(Build b, Build edit)
        {
            var telemetryType = GameType("EngineTelemetry");
            var fans = b.Root.GetComponentsInChildren(GameType("Turbofan"), true).ToDictionary(f => f.name);
            string EngineOf(Component t) => Prop(new SerializedObject(t), "engineName").stringValue;
            var gauges = edit.Root.GetComponentsInChildren(telemetryType, true);
            var shown = gauges.Where(g => fans.ContainsKey(EngineOf(g))).ToArray();
            if (!new HashSet<string>(shown.Select(EngineOf)).SetEquals(fans.Keys) || shown.Length != fans.Count)
                throw new InvalidDataException($"The tac screen's engine gauges read [{string.Join(", ", gauges.Select(EngineOf))}], the aircraft's engines are [{string.Join(", ", fans.Keys)}]");
            var panels = gauges.Select(g => g.transform.parent).Distinct().ToArray();
            var empty = panels.Where(p => !p.GetComponentsInChildren(telemetryType, true).Any(shown.Contains)).ToArray();
            DestroyWithReferences(edit, gauges.Except(shown).Select(g => (Object)g.gameObject).Concat(empty.Select(p => (Object)p.gameObject)).ToList());

            foreach (var gauge in shown)
            {
                var fan = new SerializedObject(fans[EngineOf(gauge)]);
                var most = Prop(fan, "staticThrust").floatValue * Prop(fan, "speedThrust").animationCurveValue.keys.Max(k => k.value);
                var so = new SerializedObject(gauge);
                Num(so, "thrustGauge.maxValue", most);
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            b.Report.Add($"tac screen: engine gauges [{string.Join(", ", shown.Select(EngineOf))}], {empty.Length} empty panel(s) removed, thrust dials to {Prop(new SerializedObject(shown[0]), "thrustGauge.maxValue").floatValue:F0} N");
        }

        // The weapon panel: the silhouette, one numbered marker per hardpoint set on its hardpoint, and each station
        // row named after its set. PylonIndicator colours set i's images and texts by the ammo on hardpoint index i.
        private static void ShowHardpoints(Build b, Build edit)
        {
            var profile = (RectTransform)FindDeep(edit.Root.transform, "frontProfile");
            Set(ImageOf(profile), "m_Sprite", ImportSprite(StatusSilhouettePath));
            var framing = ReadLayout(StatusFramingPath);
            var perMetre = profile.sizeDelta.x / Convert.ToSingle(framing["size_m"]);
            var centreZ = OriginStation - Convert.ToSingle(framing["centre_station"]) - b.Blockout.Origin.z;

            var sets = Prop(new SerializedObject(b.Parts["cockpit"].GetComponent(GameType("WeaponManager"))), "hardpointSets");
            var indicator = new SerializedObject(edit.Root.GetComponentsInChildren(GameType("PylonIndicator"), true).Single());
            var elements = Prop(indicator, "pylonElementSets");
            if (elements.arraySize != sets.arraySize)
                throw new InvalidDataException($"The tac screen shows {elements.arraySize} hardpoint sets, the aircraft has {sets.arraySize}");
            var markers = new List<RectTransform>();
            var positions = new List<Vector2>();
            var doomed = new List<Object>();
            for (var i = 0; i < sets.arraySize; i++)
            {
                var set = sets.GetArrayElementAtIndex(i);
                var element = elements.GetArrayElementAtIndex(i);
                var images = Enumerable.Range(0, element.FindPropertyRelative("pylonImages").arraySize)
                    .Select(k => ((Component)element.FindPropertyRelative("pylonImages").GetArrayElementAtIndex(k).objectReferenceValue).transform).ToArray();
                // The Alkyon marks a pair of hardpoints with two markers; each Centurion set has one hardpoint on the centreline.
                var onProfile = images.Where(t => t.IsChildOf(profile)).ToArray();
                var marker = (RectTransform)onProfile.First();
                doomed.AddRange(onProfile.Skip(1).Select(t => (Object)t.gameObject));
                SetText(marker.GetComponentsInChildren<Component>(true).Single(c => c.GetType().Name == "TextMeshProUGUI"), (i + 1) + "\n");
                var hardpoint = (Transform)set.FindPropertyRelative("hardpoints").GetArrayElementAtIndex(0).FindPropertyRelative("transform").objectReferenceValue;
                var at = b.Root.transform.InverseTransformPoint(hardpoint.position);
                markers.Add(marker);
                positions.Add(new Vector2(at.x, at.z - centreZ) * perMetre);

                var texts = Enumerable.Range(0, element.FindPropertyRelative("pylonTexts").arraySize)
                    .Select(k => (Component)element.FindPropertyRelative("pylonTexts").GetArrayElementAtIndex(k).objectReferenceValue).ToArray();
                var name = texts.Single(t => Prop(new SerializedObject(t), "m_text").stringValue.StartsWith((i + 1) + " ", StringComparison.Ordinal));
                SetText(name, $"{i + 1} {set.FindPropertyRelative("name").stringValue.ToUpperInvariant()}");
            }

            // The aft bay's hardpoint and the dorsal mount's are 0.8 m apart: markers that would overlap spread fore and
            // aft about their midpoint until they clear.
            var size = markers[0].sizeDelta.y;
            var order = Enumerable.Range(0, positions.Count).OrderByDescending(i => positions[i].y).ToArray();
            for (var k = 1; k < order.Length; k++)
            {
                Vector2 ahead = positions[order[k - 1]], behind = positions[order[k]];
                if (Mathf.Abs(ahead.x - behind.x) >= size || ahead.y - behind.y >= size + 4f)
                    continue;
                var mid = (ahead.y + behind.y) / 2;
                positions[order[k - 1]] = new Vector2(ahead.x, mid + (size + 4f) / 2);
                positions[order[k]] = new Vector2(behind.x, mid - (size + 4f) / 2);
            }
            for (var i = 0; i < markers.Count; i++)
                markers[i].anchoredPosition = positions[i];
            DestroyWithReferences(edit, doomed);
            b.Report.Add($"tac screen: hardpoint markers at [{string.Join(", ", positions.Select(p => $"({p.x:F0}, {p.y:F0})"))}] on the {profile.sizeDelta.x:F0}-unit silhouette");
        }

        private static void SetText(Component text, string value)
        {
            var so = new SerializedObject(text);
            Prop(so, "m_text").stringValue = value;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        // The HUD extras: the Alkyon's, its wing-sweep gauge (WingAngleGauge) redrawn as the span gauge. Under the gauge's
        // scaler the Centurion's right half stands in plan, nose up: the body and root wing as one fixed sprite ("root"),
        // and each telescoping stage on its own Filled sprite with empties at its outboard end's retracted and extended
        // places. Every sprite's pivot is its part's outboard end. The gauge's wing icon is the plan and its input pivot
        // carries the command marker; src/Centurion/SpanGauge.cs slides the stages, cuts each where it leaves the part it
        // nests in, puts the marker at the commanded tip and writes the label.
        private static GameObject AuthorSpanGaugeHud()
        {
            var sprites = (Dictionary<string, object>)ReadLayout(SpanLayoutPath)["sprites"];
            var donor = (GameObject)new SerializedObject(Load<Object>(DonorParameters)).FindProperty("HUDExtras").objectReferenceValue;
            var instance = (GameObject)Object.Instantiate(donor);
            try
            {
                instance.name = Path.GetFileNameWithoutExtension(HudExtrasPath);
                var edit = new Build { Root = instance };
                // The donor's throttle gauge labels full throttle AFTERBURNER over an orange top band (its afterburner flag
                // and throttleRegions, ThrottleGauge.cs:115, 176). The Centurion's fans have none (AuthorPrefab strips the
                // nozzles' afterburners, the only source of afterburner thrust, JetNozzle.cs:399-406), so it reads 100%.
                var throttle = new SerializedObject(instance.GetComponentsInChildren(GameType("ThrottleGauge"), true).Single());
                Prop(throttle, "afterburner").boolValue = false;
                Prop(throttle, "throttleRegions").arraySize = 0;
                // The afterburner detent marker: with the flag off Initialize stops placing it, but it still draws at its
                // authored angle at the top of the arc, so it goes too.
                ((Transform)Prop(throttle, "throttleBoundaryPivot").objectReferenceValue).gameObject.SetActive(false);
                throttle.ApplyModifiedPropertiesWithoutUndo();
                var gauge = instance.GetComponentsInChildren(GameType("WingAngleGauge"), true).Single();
                gauge.name = "spanGauge";
                var scaler = gauge.transform.Find("scaler");
                DestroyWithReferences(edit, new List<Object> { scaler.Find("fuselage").gameObject, scaler.Find("tiltArc").gameObject });
                var axis = (RectTransform)scaler.Find("pivotOffset");
                axis.anchoredPosition = SpanGaugePlanOrigin;
                axis.localRotation = Quaternion.identity;
                var plan = axis.Find("wingPivot");
                var inputPivot = axis.Find("inputPivot");
                foreach (var hub in new[] { plan, inputPivot })
                {
                    hub.localPosition = Vector3.zero;
                    hub.localRotation = Quaternion.identity;
                    hub.localScale = Vector3.one;
                    ImageOf(hub).enabled = false;
                }

                Vector3 At(object metres)
                {
                    var p = ((List<object>)metres).Select(v => Convert.ToSingle(v)).ToArray();
                    return new Vector3(p[0], OriginStation - p[1], 0f) * SpanGaugeUnitsPerMetre;
                }
                RectTransform Place(RectTransform image, string sprite)
                {
                    var entry = (Dictionary<string, object>)sprites[sprite];
                    var r = ((List<object>)entry["rect_m"]).Select(v => Convert.ToSingle(v)).ToArray(); // x0, x1, s0, s1
                    var end = ((List<object>)entry["end_m"]).Select(v => Convert.ToSingle(v)).ToArray();
                    image.name = sprite.Substring(sprite.LastIndexOf('_') + 1);
                    image.anchorMin = image.anchorMax = new Vector2(0.5f, 0.5f);
                    image.pivot = new Vector2((end[0] - r[0]) / (r[1] - r[0]), (r[3] - end[1]) / (r[3] - r[2]));
                    image.sizeDelta = new Vector2(r[1] - r[0], r[3] - r[2]) * SpanGaugeUnitsPerMetre;
                    image.localPosition = At(entry["end_m"]);
                    image.localRotation = Quaternion.identity;
                    image.localScale = Vector3.one;
                    Set(ImageOf(image), "m_Sprite", ImportSprite(CockpitArtFolder + "/" + sprite + ".png"));
                    return image;
                }

                // The Alkyon's wing art becomes the root; each stage is a copy, filled from its outboard end.
                var root = Place((RectTransform)plan.Find("wingIcon"), "centurion_span_root");
                foreach (var k in new[] { 1, 2 })
                {
                    var sprite = "centurion_span_stage" + k;
                    var stage = Place((RectTransform)Object.Instantiate(root.gameObject, plan).transform, sprite);
                    var image = new SerializedObject(ImageOf(stage));
                    Prop(image, "m_Type").intValue = 3; // Filled
                    Prop(image, "m_FillMethod").intValue = 0; // Horizontal
                    Prop(image, "m_FillOrigin").intValue = 1; // Right: outboard
                    Prop(image, "m_FillAmount").floatValue = 1f;
                    image.ApplyModifiedPropertiesWithoutUndo();
                    foreach (var (place, key) in new[] { ("_retracted", "end_m"), ("_extended", "extended_end_m") })
                    {
                        var empty = new GameObject(stage.name + place, typeof(RectTransform)).transform;
                        empty.SetParent(plan, false);
                        empty.localPosition = At(((Dictionary<string, object>)sprites[sprite])[key]);
                    }
                }

                // The command marker sits just outboard of the commanded tip, pointing in at it.
                var marker = (RectTransform)inputPivot.Find("inputMarker");
                marker.pivot = new Vector2(0.5f, 0.5f);
                marker.sizeDelta = new Vector2(6f, 6f);
                marker.localRotation = Quaternion.Euler(0f, 0f, 90f);
                marker.localPosition = new Vector3(5f, 0f, 0f);
                inputPivot.SetAsLastSibling();

                var label = (RectTransform)gauge.transform.Find("label");
                label.name = "spanLabel";
                // One line for SPAN 100%, left of the body.
                label.sizeDelta = new Vector2(160f, label.sizeDelta.y);
                label.anchoredPosition = new Vector2(-80f, label.anchoredPosition.y);
                SetText(label.GetComponents<Component>().Single(c => c.GetType().Name == "TextMeshProUGUI"), "SPAN 0%");

                var so = new SerializedObject(gauge);
                Prop(so, "wingIcon").objectReferenceValue = plan;
                Prop(so, "fade").boolValue = false;
                Prop(so, "fadeImages").arraySize = 0; // Initialize reads every fade image's alpha; with fade off none is needed
                so.ApplyModifiedPropertiesWithoutUndo();
                Debug.Log("[Centurion] HUD extras: the wing-sweep gauge redrawn as the span gauge, the root and two stages in plan");
                return SavePrefab(instance, HudExtrasPath);
            }
            finally
            {
                Object.DestroyImmediate(instance);
            }
        }

        // The HUD's damage diagram (StatusDisplay): the Alkyon's, over the Centurion's top view, with one filled sprite
        // per part the game damages, named as its UnitPart (PartStatusDisplay.FindPart matches names; fuselage_M is the
        // prefab's root), each where centurion_damage.json places it in the frame. The fire lights for engines 3 and 4 go;
        // those for engines 1 and 2 take their nacelles' shapes, with their captions outboard.
        private static GameObject AuthorDamageDiagram()
        {
            var parts = (Dictionary<string, object>)ReadLayout(DamageLayoutPath)["parts"];
            var instance = (GameObject)Object.Instantiate(Load<GameObject>(DonorStatusDisplay));
            GameObject template = null;
            try
            {
                instance.name = Path.GetFileNameWithoutExtension(StatusDisplayPath);
                var edit = new Build { Root = instance };
                var frame = (RectTransform)instance.transform;
                Set(ImageOf(frame), "m_Sprite", ImportSprite(StatusSilhouettePath));
                var displayType = GameType("StatusDisplay");
                var entries = Prop(new SerializedObject(instance.GetComponent(displayType)), "statusDisplays");
                var alkyon = Enumerable.Range(0, entries.arraySize)
                    .Select(i => ((Component)entries.GetArrayElementAtIndex(i).FindPropertyRelative("partImage").objectReferenceValue).gameObject).Distinct().ToArray();
                var threshold = entries.GetArrayElementAtIndex(0).FindPropertyRelative("redStatusThreshold").floatValue;
                template = Object.Instantiate(alkyon[0]); // outside the frame until the new images are made from it
                var engines = parts.Keys.Count(k => k.StartsWith("nacelle_", StringComparison.Ordinal));
                var fires = frame.Cast<Transform>().Where(t => t.name.StartsWith("ENGINE ", StringComparison.Ordinal) && t.name.EndsWith(" FIRE", StringComparison.Ordinal)).ToArray();
                var unused = fires.Where(f => int.Parse(f.name.Split(' ')[1]) > engines).Select(f => (Object)f.gameObject);
                DestroyWithReferences(edit, alkyon.Select(g => (Object)g).Concat(unused).ToList());

                var size = frame.sizeDelta;
                RectTransform Place(Transform t, object rect)
                {
                    var r = ((List<object>)rect).Select(v => Convert.ToSingle(v)).ToArray(); // u0, v0, u1, v1 of the frame
                    var image = (RectTransform)t;
                    image.anchorMin = image.anchorMax = image.pivot = new Vector2(0.5f, 0.5f);
                    image.localRotation = Quaternion.identity;
                    image.localScale = Vector3.one;
                    image.sizeDelta = new Vector2((r[2] - r[0]) * size.x, (r[3] - r[1]) * size.y);
                    image.anchoredPosition = new Vector2(((r[0] + r[2]) / 2 - 0.5f) * size.x, ((r[1] + r[3]) / 2 - 0.5f) * size.y);
                    return image;
                }
                Sprite SpriteOf(string part) => ImportSprite(CockpitArtFolder + "/Damage/" + (string)((Dictionary<string, object>)parts[part])["sprite"] + ".png");

                var images = new List<Component>();
                foreach (var part in parts.Keys.OrderBy(k => k, StringComparer.Ordinal))
                {
                    var go = Object.Instantiate(template, frame);
                    go.name = part == "fuselage_M" ? Path.GetFileNameWithoutExtension(PrefabPath) : part;
                    Place(go.transform, ((Dictionary<string, object>)parts[part])["rect"]);
                    var image = ImageOf(go.transform);
                    Set(image, "m_Sprite", SpriteOf(part));
                    images.Add(image);
                }
                var display = new SerializedObject(instance.GetComponent(displayType));
                entries = Prop(display, "statusDisplays");
                entries.arraySize = images.Count;
                for (var i = 0; i < images.Count; i++)
                {
                    entries.GetArrayElementAtIndex(i).FindPropertyRelative("partImage").objectReferenceValue = images[i];
                    entries.GetArrayElementAtIndex(i).FindPropertyRelative("redStatusThreshold").floatValue = threshold;
                }
                display.ApplyModifiedPropertiesWithoutUndo();

                foreach (var fire in frame.Cast<Transform>().Where(t => t.name.StartsWith("ENGINE ", StringComparison.Ordinal)).ToArray())
                {
                    var nacelle = "nacelle_" + fire.name.Split(' ')[1];
                    var light = Place(fire, ((Dictionary<string, object>)parts[nacelle])["rect"]);
                    Set(ImageOf(fire), "m_Sprite", SpriteOf(nacelle));
                    var caption = (RectTransform)fire.GetChild(0);
                    var outboard = Mathf.Sign(light.anchoredPosition.x);
                    caption.anchoredPosition = new Vector2(outboard * Mathf.Abs(caption.anchoredPosition.x), caption.anchoredPosition.y);
                    fire.SetAsLastSibling();
                }
                Debug.Log($"[Centurion] damage diagram: {images.Count} parts over the Centurion's top view, fire lights for engines 1 to {engines}");
                return SavePrefab(instance, StatusDisplayPath);
            }
            finally
            {
                Object.DestroyImmediate(instance);
                if (template != null)
                    Object.DestroyImmediate(template);
            }
        }

        private static Dictionary<string, object> ReadLayout(string path) =>
            File.Exists(path) ? (Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(path))
                : throw new FileNotFoundException("Run art/blender/status_silhouette.py first.", path);

        // A generated sprite as a single sprite, as the stock status sprites import.
        private static Sprite ImportSprite(string path)
        {
            if (!File.Exists(path))
                throw new FileNotFoundException("Run art/blender/status_silhouette.py first.", path);
            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            if (importer.textureType != TextureImporterType.Sprite || importer.spriteImportMode != SpriteImportMode.Single || importer.mipmapEnabled || !importer.alphaIsTransparency)
            {
                importer.textureType = TextureImporterType.Sprite;
                importer.spriteImportMode = SpriteImportMode.Single;
                importer.mipmapEnabled = false;
                importer.alphaIsTransparency = true;
                importer.SaveAndReimport();
            }
            return Load<Sprite>(path);
        }
    }
}
