using System.Collections.Generic;
using System.Runtime.CompilerServices;
using HarmonyLib;
using UnityEngine;

namespace Centurion;

/// <summary>
/// A Centurion's jammer counts twice against a radar-guided missile's seeker and once, as stock, against search radars.
/// Stock subtracts the target's ECM intensity once from the raw return in RadarParams.GetSignalStrength
/// (RadarParams.cs:28-43, called from Aircraft.GetRadarReturn, Aircraft.cs:747-755). The postfix recomputes the return
/// with twice the ECM only when the emitter is an ARH or SARH missile (ARHSeeker.cs:242, SARHSeeker.cs:217), keeping stock's
/// threshold and its warning RPC; doubling RadarJammer.jammingIntensity instead would also blank search radars.
/// </summary>
static class MissileJamming
{
#if CENTURION_DEV
    static readonly ConditionalWeakTable<Aircraft, Returns> LastReturns = new();

    sealed class Returns
    {
        internal readonly Sample Missile = new();
        internal readonly Sample Search = new();
    }

    sealed class Sample
    {
        internal float Stock, Actual, Ecm;
        internal float Time = float.NegativeInfinity;
    }
#endif

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("missile-jamming", typeof(Aircraft), nameof(Aircraft.GetRadarReturn),
            new[] { typeof(Vector3), typeof(Radar), typeof(Unit), typeof(float), typeof(float), typeof(RadarParams), typeof(bool) },
            postfix: AccessTools.Method(typeof(MissileJamming), nameof(AfterGetRadarReturn))),
    };

    static void AfterGetRadarReturn(Aircraft __instance, Vector3 source, Radar radar, Unit emitter, float dist,
        float clutter, RadarParams radarParams, ref float __result)
    {
        if (CenturionSystems.Of(__instance) == null) return;
        float ecm = __instance.GetECMIntensity();
        if (ecm <= 0f) return;

        // ECM is subtracted only above this raw-signal threshold (RadarParams.cs:28-43).
        float raw = Mathf.Min(radarParams.maxRange / dist * Mathf.Pow(__instance.RCS, 0.25f), radarParams.maxSignal)
            - clutter * radarParams.clutterFactor;
        if (!(raw > radarParams.minSignal)) return;

        bool missile = emitter is Missile && (emitter.TryGetComponent<ARHSeeker>(out _) || emitter.TryGetComponent<SARHSeeker>(out _));
#if CENTURION_DEV
        float stock = __result;
#endif
        if (missile)
        {
            // Keep the original warning RPC; SARH supplies the illuminator's source and parameters (Aircraft.cs:747-755; SARHSeeker.cs:217).
            Vector3 direction = FastMath.NormalizedDirection(source, __instance.transform.position);
            __result = radarParams.GetSignalStrength(direction, dist, __instance.rb, __instance.RCS, clutter, ecm * 2f);
        }
#if CENTURION_DEV
        else if (emitter is Missile || radar == null) return;

        Returns returns = LastReturns.GetValue(__instance, _ => new Returns());
        Sample sample = missile ? returns.Missile : returns.Search;
        sample.Stock = stock;
        sample.Actual = __result;
        sample.Ecm = ecm;
        sample.Time = Time.time;
#endif
    }

#if CENTURION_DEV
    internal static void AddDefaults(Dictionary<string, object> state)
    {
        foreach (string kind in new[] { "missile", "search" })
        {
            state[kind + "_return_1x"] = AircraftReadout.NotRead;
            state[kind + "_return_actual"] = AircraftReadout.NotRead;
            state[kind + "_ecm_multiplier"] = AircraftReadout.NotRead;
        }
    }

    internal static void Read(Dictionary<string, object> state, Aircraft aircraft)
    {
        if (!LastReturns.TryGetValue(aircraft, out var returns)) return;
        ReadSample(state, "missile", returns.Missile);
        ReadSample(state, "search", returns.Search);
    }

    static void ReadSample(Dictionary<string, object> state, string kind, Sample sample)
    {
        if (Time.time - sample.Time > 2f) return;
        state[kind + "_return_1x"] = AircraftReadout.Round(sample.Stock);
        state[kind + "_return_actual"] = AircraftReadout.Round(sample.Actual);
        state[kind + "_ecm_multiplier"] = AircraftReadout.Round(1f + (sample.Stock - sample.Actual) / sample.Ecm);
    }
#endif
}
