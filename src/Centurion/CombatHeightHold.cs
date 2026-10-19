using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The combat AI's terrain following, as stock tunes it for jets, flew the AI Centurion into the sea after takeoff. Two
/// stock rules in AutopilotPlane.AutoAim do it, and for a Centurion in AIPilotCombatModes this prefix undoes both:
/// - The height is scaled by Lerp(0.1, 1, (airspeed - 0.9 x landingSpeed) / landingSpeed) (AutopilotPlane.cs:46), full only
///   at 1.9 x landingSpeed. Jets cruise past that; at the Centurion's landingSpeed 105 it takes 200 m/s, so after takeoff
///   (90 to 120 m/s) the combat AI's 190 m command became 14 to 60 m. The prefix divides the height by the same scale.
/// - Unless aimVelocity is set, the nose, not the flight path, points at the waypoint (AutopilotPlane.cs:34), and the
///   combat AI sets it only in break-off, retreat and radar evasion (AIPilotCombatModes.cs:447, 487, 1177). The waypoint
///   sits about 2 km ahead (TerrainWarningSystem.cs:49), so a 100 m rise is 2.5 degrees; the Centurion flies 5 degrees of
///   alpha at those speeds, so with its nose on the waypoint it sank at 2 degrees. The prefix aims the flight path.
/// The landing states keep both stock rules, so the approach, which landingSpeed also sets, is untouched; the takeoff and
/// AWACS states do not follow terrain. A Centurion carrying bombs or missiles flies <see cref="AiHighStrike"/>'s high profile instead.
/// </summary>
static class CombatHeightHold
{
    const string CenturionKey = "baanish_centurion";
    const float LowestScale = 0.1f;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("combat-height-hold", typeof(AutopilotPlane), nameof(AutopilotPlane.AutoAim),
            new[] { typeof(GlobalPosition), typeof(bool), typeof(bool), typeof(bool), typeof(float), typeof(float), typeof(bool), typeof(float), typeof(Vector3) },
            prefix: AccessTools.Method(typeof(CombatHeightHold), nameof(BeforeAutoAim))),
    };

    static void BeforeAutoAim(AutopilotPlane __instance, ref GlobalPosition destination, ref bool aimVelocity, ref float bankAllowed,
        ref bool followTerrain, ref float altitudeHold)
    {
        if (CenturionPlugin.FeaturesOff.Contains("combat-height-hold")) return;
        Aircraft aircraft = __instance.aircraft;
        if (aircraft == null || aircraft.definition == null || aircraft.definition.jsonKey != CenturionKey) return;
        if (aircraft.pilots.Length == 0 || aircraft.pilots[0].currentState is not AIPilotCombatModes combat) return;
        if (AiHighStrike.Steer(aircraft, combat, ref destination, ref aimVelocity, ref followTerrain, ref bankAllowed, ref altitudeHold)) return;
        if (!followTerrain) return;

        // AirspeedChecker.GetAirspeed (Autopilot.cs:109-117): forward airspeed against the wind, recomputed each call.
        float airspeed = Vector3.Dot(aircraft.cockpit.xform.forward,
            aircraft.rb.velocity - NetworkSceneSingleton<LevelInfo>.i.GetWind(aircraft.GlobalPosition()));
        float landingSpeed = aircraft.GetAircraftParameters().landingSpeed;
        float scale = Mathf.Lerp(LowestScale, 1f, (airspeed - landingSpeed * 0.9f) / landingSpeed);
        if (CenturionPlugin.Log.StageDue("combat-height-hold"))
        {
            Vector3 velocity = aircraft.rb.velocity;
            CenturionPlugin.Log.StageLine("combat-height-hold", Invariant(
                $"{aircraft.name} {aircraft.persistentID} command {altitudeHold:F0} m, stock would hold {altitudeHold * scale:F0} m at {airspeed:F1} m/s, radar alt {aircraft.radarAlt:F0} m, nose {Mathf.Asin(aircraft.cockpit.xform.forward.y) * Mathf.Rad2Deg:F1} deg, path {Mathf.Asin(velocity.y / Mathf.Max(velocity.magnitude, 1f)) * Mathf.Rad2Deg:F1} deg, stock aims {(aimVelocity ? "path" : "nose")}"));
        }
        altitudeHold /= scale;
        aimVelocity = true;
    }
}
