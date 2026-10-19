using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The wing display: the flight deck's sixth display, outboard of the pilot's flight display, a page of the Centurion's own
/// rather than one of the tac screen's (owner's sketch). One telescope column stands for both wings, since they extend
/// together and a lost stage 1 jettisons the other (TelescopeController.OneStage1Lost): the root hangs from the page's top,
/// open there, each stage slides out of the one it nests in as the span grows, the raked tip on the last, and the span in
/// percent sits at the page's foot. A lost stage leaves the column with everything outboard of it and the percentage turns
/// amber, over JETTISONED when the stage 1 panels have gone, or OUTER LOST when only a stage 2 has: nothing pairs that loss,
/// so the other stage 2 stays on. Green on black, the tac screen's MFD style.
/// Authoring stands the canvas (CenturionAuthor.AuthorWingDisplay, art/blender/cockpit/flightdeck.py wing_canvas) with one
/// line of MFD text to copy; this draws the rest. The canvas draws only while the interior does (cockpit view:
/// Aircraft.cockpitRenderers), and redraws only when what it shows changes.
/// </summary>
sealed class WingDisplay : MonoBehaviour
{
    const string CanvasName = "wing_display";
    // The column in canvas units, millimetres on the page, centred with y up (the page is 143 by 224, inside the bezel's
    // dark margin): the root's length down from the page's top, each part's width from the root out, how far each stage
    // slides out of the one it nests in over the full span, how much of stage 2 stands out of stage 1 retracted, the tip
    // cap's width and its inboard and outboard depth, and the line weight.
    const float Top = 112f, RootLength = 48f, Travel = 58f, Stub = 10f, TipWidth = 20f, TipInboard = 10f, TipOutboard = 4f, Line = 1.2f;
    static readonly float[] Widths = { 30f, 22f, 14f };
    // The percentage at the page's foot and the word over it: height and size.
    const float PercentY = -100f, PercentSize = 16f, WordY = -84f, WordSize = 9f;
    // The tac screen's MFD green, and the stock caution amber.
    static readonly Color Green = new(0f, 1f, 0f, 1f), Amber = new(1f, 0.69f, 0f, 1f);

    TelescopeController telescope = null!;
    Canvas canvas = null!;
    Renderer interior = null!;
    readonly Image[][] parts = new Image[3][]; // root, stage 1, stage 2: each its two sides and its outboard end
    readonly Image[] tip = new Image[4]; // its inboard edge, two sides and raked outboard edge
    Transform stage1 = null!, stage2 = null!;
    TextMeshProUGUI percent = null!, word = null!;
    (int Extension, int Lost) shown = (-1, -1);

    /// <summary>
    /// Puts the display on the Centurion's wing display canvas, found through partLookup: in complex physics each part
    /// sits on its own rigidbody outside the aircraft's hierarchy (AeroPart.CreateRB unparents it), so a search of the
    /// aircraft's children missed the cockpit and the display stayed black. Anything it needs that is missing is an error.
    /// </summary>
    internal static void Attach(Aircraft aircraft, TelescopeController controller)
    {
        var canvas = aircraft.partLookup.Where(p => p != null).SelectMany(p => p.GetComponentsInChildren<Canvas>(true))
            .FirstOrDefault(c => c.name == CanvasName);
        var interior = canvas == null ? null : canvas.transform.parent.GetComponent<Renderer>();
        var template = canvas == null ? null : canvas.transform.Find("text");
        if (canvas == null || interior == null || template == null || template.GetComponent<TextMeshProUGUI>()?.font == null)
        {
            TelescopeController.Log.Error($"wing display on {aircraft.name}: " + (canvas == null ? $"no {CanvasName} canvas on any part"
                : interior == null ? "its canvas is not under the interior's renderer" : "its canvas has no MFD text template with a font")
                + ", so the display stays dark");
            return;
        }

        var display = canvas.gameObject.AddComponent<WingDisplay>();
        display.telescope = controller;
        display.canvas = canvas;
        display.interior = interior;
        display.Build(template.gameObject);
        TelescopeController.Log.Stage("wing-display-built", Invariant(
            $"{aircraft.name}: {display.GetComponentsInChildren<Image>(true).Length} lines and 2 texts on layer {canvas.gameObject.layer}, canvas {((RectTransform)canvas.transform).sizeDelta.x:0} x {((RectTransform)canvas.transform).sizeDelta.y:0} mm"));
    }

    void Build(GameObject textTemplate)
    {
        var root = Group("root");
        stage1 = Group("stage1");
        stage2 = Group("stage2", stage1);
        var parents = new[] { root, stage1, stage2 };
        for (int k = 0; k < 3; k++)
        {
            parts[k] = new[] { Bar(parents[k]), Bar(parents[k]), Bar(parents[k]) };
        }

        var cap = Group("tip", stage2);
        for (int k = 0; k < tip.Length; k++)
        {
            tip[k] = Bar(cap);
        }

        percent = Text(textTemplate, "percent", PercentY, PercentSize);
        word = Text(textTemplate, "word", WordY, WordSize);
    }

    Transform Group(string name, Transform? parent = null)
    {
        var group = new GameObject(name, typeof(RectTransform)) { layer = canvas.gameObject.layer }.transform;
        group.SetParent(parent ?? canvas.transform, false);
        return group;
    }

    Image Bar(Transform parent)
    {
        var bar = new GameObject("line", typeof(RectTransform), typeof(CanvasRenderer), typeof(Image)) { layer = canvas.gameObject.layer };
        bar.transform.SetParent(parent, false);
        var image = bar.GetComponent<Image>();
        image.color = Green;
        image.raycastTarget = false;
        return image;
    }

    TextMeshProUGUI Text(GameObject template, string name, float y, float size)
    {
        var copy = Instantiate(template, canvas.transform);
        copy.name = name;
        copy.SetActive(true);
        var text = copy.GetComponent<TextMeshProUGUI>();
        var rect = text.rectTransform;
        rect.sizeDelta = new Vector2(((RectTransform)canvas.transform).sizeDelta.x, size * 1.5f);
        rect.localPosition = new Vector3(0f, y, 0f);
        text.enableAutoSizing = false;
        text.fontSize = size;
        text.alignment = TextAlignmentOptions.Center;
        text.enableWordWrapping = false;
        text.text = "";
        return text;
    }

    /// <summary>A line Line thick from a to b, in canvas millimetres.</summary>
    static void Draw(Image bar, Vector2 a, Vector2 b)
    {
        var rect = bar.rectTransform;
        var d = b - a;
        rect.sizeDelta = new Vector2(d.magnitude + Line, Line);
        rect.localPosition = (a + b) / 2f;
        rect.localRotation = Quaternion.Euler(0f, 0f, Mathf.Atan2(d.y, d.x) * Mathf.Rad2Deg);
    }

    /// <summary>A part's two sides from y down length, and its outboard end; returns where that end is.</summary>
    static float Section(Image[] bars, float width, float y, float length)
    {
        float x = width / 2f, end = y - length;
        Draw(bars[0], new Vector2(-x, y), new Vector2(-x, end));
        Draw(bars[1], new Vector2(x, y), new Vector2(x, end));
        Draw(bars[2], new Vector2(-x, end), new Vector2(x, end));
        return end;
    }

    void LateUpdate()
    {
        bool on = interior.enabled;
        if (canvas.enabled != on)
        {
            canvas.enabled = on;
        }

        var now = (Mathf.RoundToInt(telescope.Extension * 1000f), telescope.LostMask);
        if (!on || now == shown)
        {
            return;
        }

        if (shown.Extension < 0)
        {
            TelescopeController.Log.Stage("wing-display-drawn", Invariant(
                $"{telescope.name}: first drawn in cockpit view at {telescope.Extension * 100f:0}%, lost stages {now.Item2}"));
        }

        shown = now;
        float extension = telescope.Extension;
        float y = Section(parts[0], Widths[0], Top, RootLength);
        y = Section(parts[1], Widths[1], y, Travel * extension);
        y = Section(parts[2], Widths[2], y, Stub + Travel * extension);
        float x = TipWidth / 2f;
        Draw(tip[0], new Vector2(-x, y), new Vector2(x, y));
        Draw(tip[1], new Vector2(-x, y), new Vector2(-x, y - TipInboard));
        Draw(tip[2], new Vector2(x, y), new Vector2(x, y - TipOutboard));
        Draw(tip[3], new Vector2(-x, y - TipInboard), new Vector2(x, y - TipOutboard));

        // LostMask: bits 0 and 1 a stage 1, 2 and 3 a stage 2 off its stage 1 (one riding a lost stage 1 goes with it).
        bool inner = (now.Item2 & 3) != 0, outer = (now.Item2 & 12) != 0;
        stage1.gameObject.SetActive(!inner);
        stage2.gameObject.SetActive(!outer);
        percent.text = Invariant($"{extension * 100f:0}%");
        percent.color = inner || outer ? Amber : Green;
        word.text = inner ? "JETTISONED" : outer ? "OUTER LOST" : "";
        word.color = Amber;
    }
}
