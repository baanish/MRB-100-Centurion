using HarmonyLib;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The span gauge: the Alkyon's stock wing-sweep gauge (WingAngleGauge, a HUD app in its HUD extras), which the Centurion's
/// HUD extras redraw as its right half in plan (CenturionAuthor.AuthorSpanGaugeHud, art/blender/status_silhouette.py): under
/// the gauge's wing icon the body and root wing are one fixed image ("root") and each telescoping stage a Filled image
/// ("stage1", "stage2"), every pivot on its part's outboard end, with empties at a stage's end retracted and extended
/// ("stage1_retracted", "stage1_extended", ...). The gauge finds the TelescopeController through IWingAngleGauge
/// (WingAngleGauge.cs:52) and turns its wing icon and input marker by the angles it reads (WingAngleGauge.cs:105-131); this
/// postfix undoes the turn, slides each stage between its ends with the extension, shows only what is outboard of the part it
/// nests in (the root's end for the first stage, the first stage's end for the second: the ends are streamwise, so a
/// horizontal fill cuts them true), puts the command marker at the tip's commanded place and writes the extension in percent.
/// </summary>
static class SpanGauge
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("span gauge", typeof(WingAngleGauge), nameof(WingAngleGauge.Refresh),
            postfix: AccessTools.Method(typeof(SpanGauge), nameof(AfterRefresh))),
    };

    static readonly string[] Stages = { "stage1", "stage2" };

    static void AfterRefresh(IWingAngleGauge ___wingAngleInterface, Transform ___wingIcon, Transform ___inputPivot, TextMeshProUGUI ___label)
    {
        if (CenturionPlugin.FeaturesOff.Contains("span gauge")) return;
        if (___wingAngleInterface is not TelescopeController telescope)
        {
            return;
        }

        var plan = ___wingIcon;
        plan.localRotation = Quaternion.identity;
        var (retracted, extended) = SlidePlan(plan, telescope.Extension);
        ___inputPivot.localRotation = Quaternion.identity;
        ___inputPivot.localPosition = Vector3.Lerp(retracted, extended, telescope.Command);
        ___label.text = Invariant($"SPAN {telescope.Extension * 100f:0}%");
    }

    /// <summary>
    /// Slides each stage of a span plan (the gauge's, or the wing display's copy, <see cref="WingDisplay"/>) to the
    /// extension, showing only what is outboard of the part it nests in; returns the tip's retracted and extended places.
    /// </summary>
    internal static (Vector3 Retracted, Vector3 Extended) SlidePlan(Transform plan, float extension)
    {
        var cover = plan.Find("root").localPosition.x;
        Vector3 retracted = default, extended = default;
        foreach (var name in Stages)
        {
            var stage = (RectTransform)plan.Find(name);
            retracted = plan.Find(name + "_retracted").localPosition;
            extended = plan.Find(name + "_extended").localPosition;
            stage.localPosition = Vector3.Lerp(retracted, extended, extension);
            stage.GetComponent<Image>().fillAmount = Mathf.Clamp01((stage.localPosition.x + stage.rect.xMax - cover) / stage.rect.width);
            cover = Mathf.Max(cover, stage.localPosition.x);
        }

        return (retracted, extended);
    }
}
