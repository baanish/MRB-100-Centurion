using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace Centurion;

/// <summary>
/// Stock power and countermeasure readouts. Flare counts follow successful launches, independently of the ejector's ammo.
/// </summary>
static class PowerReadout
{
    static readonly FieldInfo? EngineInterfaces = AccessTools.Field(typeof(PowerSupply), "engineInterfaces");
    static readonly FieldInfo? ChargePerRpm = AccessTools.Field(typeof(PowerSupply), "chargePerRPM");
    static readonly FieldInfo? PowerSources = AccessTools.Field(typeof(PowerSupply), "powerSources");
    // jamIntensityCurrent survives release; jamIntensityPrev is the contribution still on the aircraft.
    static readonly FieldInfo? JamIntensity = AccessTools.Field(typeof(RadarJammer), "jamIntensityPrev");
    static readonly ConditionalWeakTable<Aircraft, FlareCount> FlareCounts = new();

    sealed class FlareCount
    {
        internal int Ejected;
    }

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("cm-count", typeof(IRFlare), "LaunchFlare", new[] { typeof(Aircraft), typeof(Transform), typeof(Vector3) },
            postfix: AccessTools.Method(typeof(PowerReadout), nameof(AfterLaunchFlare))),
    };

    internal static void Install(ConfigFile config, CenturionLog log)
    {
        foreach (var field in new[]
        {
            ("PowerSupply.engineInterfaces", EngineInterfaces), ("PowerSupply.chargePerRPM", ChargePerRpm),
            ("PowerSupply.powerSources", PowerSources), ("RadarJammer.jamIntensityPrev", JamIntensity),
        })
        {
            if (field.Item2 == null)
            {
                log.Warning($"power readout: {field.Item1} missing, its readout stays -999");
            }
        }
    }

    static void AfterLaunchFlare(Aircraft aircraft)
    {
        if (CenturionPlugin.FeaturesOff.Contains("cm-count")) return;
        if (aircraft != null && aircraft.definition.jsonKey == "baanish_centurion")
        {
            FlareCounts.GetValue(aircraft, _ => new FlareCount()).Ejected++;
        }
    }

    internal static void AddDefaults(Dictionary<string, object> state)
    {
        foreach (string key in new[]
        {
            "capacitor_kj", "capacitor_frac", "capacitor_charge_kw", "capacitor_sources",
            "ecm_intensity", "jammer_on", "flares", "flares_ejected", "ignition",
        })
        {
            state[key] = AircraftReadout.NotRead;
        }
    }

    internal static void Read(Dictionary<string, object> state, Aircraft aircraft)
    {
        PowerSupply power = aircraft.GetPowerSupply();
        if (power != null)
        {
            state["capacitor_kj"] = AircraftReadout.Round(power.GetChargeKJ());
            state["capacitor_frac"] = AircraftReadout.Round(power.GetCharge());
            if (PowerSources?.GetValue(power) is GameObject[] sources)
            {
                state["capacitor_sources"] = sources.Length;
            }
            if (EngineInterfaces?.GetValue(power) is IEngine[] engines && ChargePerRpm?.GetValue(power) is float perRpm)
            {
                float rpm = 0f;
                bool readable = true;
                foreach (IEngine engine in engines)
                {
                    if (engine == null)
                    {
                        readable = false;
                        break;
                    }
                    rpm += engine.GetRPM();
                }
                if (readable)
                {
                    state["capacitor_charge_kw"] = AircraftReadout.Round(perRpm * rpm);
                }
            }
        }
        state["ecm_intensity"] = AircraftReadout.Round(aircraft.GetECMIntensity());
        state["ignition"] = aircraft.Ignition ? 1 : 0;
        RadarJammer jammer = aircraft.GetComponent<RadarJammer>();
        if (jammer != null && JamIntensity?.GetValue(jammer) is float intensity)
        {
            state["jammer_on"] = intensity > 0f ? 1 : 0;
        }
        FlareEjector flares = aircraft.GetComponent<FlareEjector>();
        if (flares != null)
        {
            state["flares"] = flares.GetAmmo();
        }
        if (!CenturionPlugin.FeaturesOff.Contains("cm-count"))
        {
            state["flares_ejected"] = FlareCounts.TryGetValue(aircraft, out FlareCount count) ? count.Ejected : 0;
        }
    }

    internal static void ReadRemote(Dictionary<string, object> state)
    {
    }
}
