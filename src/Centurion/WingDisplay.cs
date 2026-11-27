using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The wing display: the flight deck's sixth display, outboard of the pilot's flight display, a page of the Centurion's own
/// rather than one of the tac screen's (owner's sketch). One wing stands for both, since they extend together and, while
/// both wing roots are on, a lost stage 1 jettisons the other (TelescopeController.OneStage1Lost): the HUD span gauge's own
/// line art, the right wing turned to hang from the page's top edge, its stages sliding down out of the root as the span
/// grows exactly as the gauge slides them (SpanGauge.SlidePlan), and the span in percent at the page's foot. A lost stage
/// leaves the wing with everything outboard of it and the percentage turns amber, over WING LOST when a wing root has gone
/// (nothing is jettisoned, so the other wing keeps its panels), JETTISONED when the stage 1 panels have, or OUTER LOST when
/// only a stage 2 has: nothing pairs that loss, so the other stage 2 stays on. Green on black, the tac screen's MFD style.
/// Authoring stands the canvas (CenturionAuthor.AuthorWingDisplay, art/blender/cockpit/flightdeck.py wing_canvas) with the
/// plan on its page and one line of MFD text to copy. The canvas draws only while the interior does (cockpit view:
/// Aircraft.cockpitRenderers), and redraws only when what it shows changes.
/// </summary>
sealed class WingDisplay : MonoBehaviour
{
    const string CanvasName = "wing_display";
    // The percentage at the page's foot and the word over it, in canvas millimetres up from the page's foot: height and
    // size. From the foot, not the centre: on a page shorter than 0.1.3's 224 mm the percentage fell under the bezel.
    const float PercentUp = 12f, PercentSize = 16f, WordUp = 28f, WordSize = 9f;
    // The tac screen's MFD green at three quarters, as the authored wing outline is (full green bloomed under night
    // vision), and the stock caution amber.
    static readonly Color Green = new(0f, 0.75f, 0f, 1f), Amber = new(1f, 0.69f, 0f, 1f);

    TelescopeController telescope = null!;
    Canvas canvas = null!;
    Renderer interior = null!;
    Transform plan = null!, stage1 = null!, stage2 = null!;
    UnitPart[] roots = null!;
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
        if (canvas == null || interior == null || template == null || !(template.TryGetComponent(out TextMeshProUGUI text) && text.font != null)
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
        display.roots = aircraft.partLookup.Where(p => p != null && (p.name == "wing_root_L" || p.name == "wing_root_R")).ToArray();
        plan.parent.gameObject.AddComponent<RectMask2D>(); // the page: the body the root sprite draws is cut off at its top
        var foot = -((RectTransform)canvas.transform).sizeDelta.y / 2f;
        display.percent = display.Text(template.gameObject, "percent", foot + PercentUp, PercentSize);
        display.word = display.Text(template.gameObject, "word", foot + WordUp, WordSize);
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
        // A lost root takes its stage 1 too, which is how the redraw sees it.
        bool rootLost = roots.Any(r => r == null || r.IsDetached());
        word.text = rootLost ? "WING LOST" : inner ? "JETTISONED" : outer ? "OUTER LOST" : "";
        word.color = Amber;
    }
}
