using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The wing display: the flight deck's sixth display, outboard of the pilot's flight display, a page of the Centurion's own
/// rather than one of the tac screen's (owner's sketch). One wing stands for both, since they extend together and a lost
/// stage 1 jettisons the other (TelescopeController.OneStage1Lost): the HUD span gauge's own line art, the right wing turned
/// to hang from the page's top edge, its stages sliding down out of the root as the span grows exactly as the gauge slides
/// them (SpanGauge.SlidePlan), and the span in percent at the page's foot. A lost stage leaves the wing with everything
/// outboard of it and the percentage turns amber, over JETTISONED when the stage 1 panels have gone, or OUTER LOST when only
/// a stage 2 has: nothing pairs that loss, so the other stage 2 stays on. Green on black, the tac screen's MFD style.
/// Authoring stands the canvas (CenturionAuthor.AuthorWingDisplay, art/blender/cockpit/flightdeck.py wing_canvas) with the
/// plan on its page and one line of MFD text to copy. The canvas draws only while the interior does (cockpit view:
/// Aircraft.cockpitRenderers), and redraws only when what it shows changes.
/// </summary>
sealed class WingDisplay : MonoBehaviour
{
    const string CanvasName = "wing_display";
    // The percentage at the page's foot and the word over it, in canvas millimetres from the page's centre: height and size.
    const float PercentY = -100f, PercentSize = 16f, WordY = -84f, WordSize = 9f;
    // The tac screen's MFD green, and the stock caution amber.
    static readonly Color Green = new(0f, 1f, 0f, 1f), Amber = new(1f, 0.69f, 0f, 1f);

    TelescopeController telescope = null!;
    Canvas canvas = null!;
    Renderer interior = null!;
    Transform plan = null!, stage1 = null!, stage2 = null!;
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
        var plan = canvas == null ? null : canvas.transform.Find("page/plan");
        if (canvas == null || interior == null || template == null || template.GetComponent<TextMeshProUGUI>()?.font == null
            || plan == null || plan.Find("root") == null || plan.Find("stage1") == null || plan.Find("stage2") == null)
        {
            TelescopeController.Log.Error($"wing display on {aircraft.name}: " + (canvas == null ? $"no {CanvasName} canvas on any part"
                : interior == null ? "its canvas is not under the interior's renderer"
                : plan == null || plan.Find("stage2") == null ? "its page has no span gauge plan" : "its canvas has no MFD text template with a font")
                + ", so the display stays dark");
            return;
        }

        var display = canvas.gameObject.AddComponent<WingDisplay>();
        display.telescope = controller;
        display.canvas = canvas;
        display.interior = interior;
        display.plan = plan;
        display.stage1 = plan.Find("stage1");
        display.stage2 = plan.Find("stage2");
        plan.parent.gameObject.AddComponent<RectMask2D>(); // the page: the body the root sprite draws is cut off at its top
        display.percent = display.Text(template.gameObject, "percent", PercentY, PercentSize);
        display.word = display.Text(template.gameObject, "word", WordY, WordSize);
        TelescopeController.Log.Stage("wing-display-built", Invariant(
            $"{aircraft.name}: {plan.GetComponentsInChildren<Image>(true).Count(i => i.enabled)} plan sprites and 2 texts on layer {canvas.gameObject.layer}, canvas {((RectTransform)canvas.transform).sizeDelta.x:0} x {((RectTransform)canvas.transform).sizeDelta.y:0} mm"));
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
        SpanGauge.SlidePlan(plan, extension);
        // LostMask: bits 0 and 1 a stage 1, 2 and 3 a stage 2 off its stage 1 (one riding a lost stage 1 goes with it).
        bool inner = (now.Item2 & 3) != 0, outer = (now.Item2 & 12) != 0;
        stage1.gameObject.SetActive(!inner);
        stage2.gameObject.SetActive(!inner && !outer);
        percent.text = Invariant($"{extension * 100f:0}%");
        percent.color = inner || outer ? Amber : Green;
        word.text = inner ? "JETTISONED" : outer ? "OUTER LOST" : "";
        word.color = Amber;
    }
}
