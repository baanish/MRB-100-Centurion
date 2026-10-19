using System;
using System.Collections.Generic;
using BepInEx.Configuration;
using HarmonyLib;
using NuclearOption.NetworkTransforms;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// What the simulating peer knows about its Centurion and every other peer needs to agree with: the span's extension, which
/// stages are gone, the radar master and the AWACS beam's target. It rides in the stock input snapshot's Custom Axis 1
/// (AircraftNetworkTransform.CreateSnapshot, about every 0.2 s, AircraftNetworkTransform.cs:413-424), which the server relays
/// and every observer applies (Aircraft.ApplySetInputs, Aircraft.cs:1790-1797), a late joiner from its first snapshot. Unlike
/// the reliable part-break and radar RPCs it reaches a peer that joined after them, and unlike the command the axis carried
/// before, observers set their state from it instead of integrating it, so a lost snapshot is corrected by the next one.
/// No new Mirage message, so a vanilla server never sees an unknown id. The owner's own Custom Axis 1 still holds the
/// command; only the sent copy carries the word.
/// </summary>
sealed class OwnerState : MonoBehaviour
{
    const string CenturionKey = "baanish_centurion";

    // The half-float the axis travels as must stay finite (NetworkFloatHelper.Validate rejects the snapshot otherwise): bit 14
    // is the top exponent bit, so clearing it keeps the exponent under 31. Bit 15, the sign, marks a word; a plain command
    // from a build without it is a non-negative half and reads as none.
    const ushort Marker = 0x8000;
    const int ExtensionMask = 0xFF, LostShift = 8, RadarBit = 1 << 12, BeamBit = 1 << 13;
    const float LogIntervalS = 0.5f;
    // A copy's first 5 s of words, about every 0.2 s.
    const int CapacitorWords = 25;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("owner-state", typeof(AircraftNetworkTransform), "CreateSnapshot",
            postfix: AccessTools.Method(typeof(OwnerState), nameof(AfterCreateSnapshot))),
        new("owner-state", typeof(Aircraft), nameof(Aircraft.ApplySetInputs), new[] { typeof(CompressedInputs) },
            postfix: AccessTools.Method(typeof(OwnerState), nameof(AfterApplySetInputs))),
    };

    /// <summary>Every live Centurion's holder, local and remote.</summary>
    static readonly List<OwnerState> All = new();
    static readonly string[] Kinds = { "player", "ai" };
    static readonly string[] Keys = { "pid", "sim", "span_frac", "lost", "detached_stages", "radar_master", "awacs_deploy", "words" };

    static ConfigEntry<bool> diagnostics = null!;
    static ConfigEntry<bool> stateLog = null!;
    static CenturionLog log = null!;

    Aircraft aircraft = null!;
    float nextLogAt;
    bool capacitorStarted;

    /// <summary>True once a word from the simulating peer has arrived here; never on the simulating peer.</summary>
    public bool Received { get; private set; }
    public int Words { get; private set; }
    /// <summary>The owner's extension, 0 to 1, to 1/255.</summary>
    public float Extension { get; private set; }
    /// <summary>The owner's lost stages: bit 0 stage 1 left, 1 stage 1 right, 2 stage 2 left, 3 stage 2 right (<see cref="TelescopeController.LostMask"/>).</summary>
    public int Lost { get; private set; }
    public bool RadarMaster { get; private set; } = true;
    public bool BeamUp { get; private set; }

    internal static void Install(ConfigFile config, CenturionLog log)
    {
        OwnerState.log = log;
        if (!config.TryGetEntry("Diagnostics", "Enabled", out diagnostics))
        {
            throw new InvalidOperationException("OwnerState requires Diagnostics.Enabled to be bound before Install");
        }

        stateLog = config.Bind("Diagnostics", "OwnerStateLog", false,
            "With Diagnostics.Enabled, log each Centurion's span, lost stages, radar master and beam on this peer twice a second, keyed by persistent id with the wall clock, for comparing peers (tests/agentic/centurion_mp_agreement.py)");
    }

    /// <summary>The aircraft's state holder, added on first sight; null for any other aircraft.</summary>
    internal static OwnerState? For(Aircraft aircraft)
    {
        if (aircraft.definition == null || aircraft.definition.jsonKey != CenturionKey)
        {
            return null;
        }

        return aircraft.TryGetComponent(out OwnerState state) ? state : aircraft.gameObject.AddComponent<OwnerState>();
    }

    void Awake()
    {
        aircraft = GetComponent<Aircraft>();
        All.Add(this);
    }

    void OnDestroy() => All.Remove(this);

    internal static void AddDefaults(Dictionary<string, object> state)
    {
        foreach (string kind in Kinds)
        {
            foreach (string key in Keys)
            {
                state[$"mp_{kind}_{key}"] = AircraftReadout.NotRead;
            }
        }
    }

    /// <summary>
    /// mp_player_* reads the first Centurion another peer's player flies, mp_ai_* the first one no player flies (simulated on
    /// the host), each as this peer has it, with its persistent id: a scenario compares one aircraft across peers by these.
    /// </summary>
    internal static void ReadPeers(Dictionary<string, object> state)
    {
        foreach (string kind in Kinds)
        {
            OwnerState? found = All.Find(s => s != null && s.aircraft != null && !s.aircraft.disabled
                && (kind == "ai" ? s.aircraft.Player == null : s.aircraft.Player != null && !s.aircraft.Player.IsLocalPlayer));
            if (found == null)
            {
                continue;
            }

            Aircraft a = found.aircraft;
            string prefix = $"mp_{kind}_";
            state[prefix + "pid"] = (double)a.persistentID.Id;
            state[prefix + "sim"] = a.LocalSim ? 1 : 0;
            state[prefix + "words"] = found.Words;
            if (a.TryGetComponent(out TelescopeController telescope))
            {
                state[prefix + "span_frac"] = AircraftReadout.Round(telescope.Extension);
                state[prefix + "lost"] = telescope.LostMask;
                state[prefix + "detached_stages"] = telescope.DetachedStages;
            }

            if (a.TryGetComponent(out RadarSuite radar))
            {
                state[prefix + "radar_master"] = radar.Master ? 1 : 0;
            }

            if (a.TryGetComponent(out AwacsBeam beam) && beam.Fitted)
            {
                state[prefix + "awacs_deploy"] = AircraftReadout.Round(beam.Deploy);
            }
        }
    }

    static void AfterCreateSnapshot(AircraftNetworkTransform __instance, ref NetworkTransformBase.NetworkSnapshot __result)
    {
        if (CenturionPlugin.FeaturesOff.Contains("owner-state")) return;
        if (!__result.ClientInputs.HasValue || __instance.Aircraft == null || !__instance.Aircraft.LocalSim || For(__instance.Aircraft) is not { } state)
        {
            return;
        }

        CompressedInputs inputs = __result.ClientInputs.Value;
        inputs.customAxis1.Value = state.OwnWord();
        __result.ClientInputs = inputs;
    }

    static void AfterApplySetInputs(Aircraft __instance, CompressedInputs inputs)
    {
        if (CenturionPlugin.FeaturesOff.Contains("owner-state")) return;
        ushort word = inputs.customAxis1.Value;
        if ((word & Marker) == 0 || For(__instance) is not { } state)
        {
            return;
        }

        state.Receive(word);
        // Anything else reading the axis on this copy reads the owner's extension, not the word's bits.
        __instance.GetInputs().customAxis1 = state.Extension;
    }

    ushort OwnWord()
    {
        int word = Marker;
        if (aircraft.TryGetComponent(out TelescopeController telescope))
        {
            word |= Mathf.RoundToInt(Mathf.Clamp01(telescope.Extension) * ExtensionMask) | (telescope.LostMask << LostShift);
        }

        if (!aircraft.TryGetComponent(out RadarSuite radar) || radar.Master)
        {
            word |= RadarBit;
        }

        if (aircraft.TryGetComponent(out AwacsBeam beam) && beam.TargetUp)
        {
            word |= BeamBit;
        }

        return (ushort)word;
    }

    void Receive(ushort word)
    {
        Extension = (word & ExtensionMask) / (float)ExtensionMask;
        Lost = (word >> LostShift) & 0xF;
        RadarMaster = (word & RadarBit) != 0;
        BeamUp = (word & BeamBit) != 0;
        // The capacitor starts full for an aircraft spawned in the air (PowerSupply.PowerSupply_OnSpawnedInPosition), judged by
        // radar altitude, which a copy has only after its first snapshots (Aircraft.cs:1206-1209); so a copy of an airborne spawn
        // started empty and charged from its engines, and the laser a host repeats for a client drew next to nothing (run
        // 20261015-042721: 308 to 385 of 2,000 kJ). Over its first words the copy has a position, so it takes the owner's start.
        if (!capacitorStarted && Words < CapacitorWords && aircraft.radarAlt > 0f)
        {
            capacitorStarted = true;
            if (aircraft.radarAlt > aircraft.definition.spawnOffset.y + 1f && aircraft.GetPowerSupply() is { } power && power.GetCharge() < 1f)
            {
                power.SetFullyCharged();
                log.Info($"owner state for {aircraft.name}: airborne at first sight, capacitor charged as its owner's was at spawn");
            }
        }

        if (!Received)
        {
            log.Info(Invariant($"owner state for {aircraft.name} ({aircraft.persistentID.Id}): first word, extension {Extension:0.000}, lost {Lost}, radar {(RadarMaster ? "on" : "off")}, beam {(BeamUp ? "up" : "down")}"));
        }

        Received = true;
        Words++;
    }

    void Update()
    {
        if (!stateLog.Value || !diagnostics.Value || Time.unscaledTime < nextLogAt)
        {
            return;
        }

        nextLogAt = Time.unscaledTime + LogIntervalS;
        float extension = aircraft.TryGetComponent(out TelescopeController telescope) ? telescope.Extension : float.NaN;
        int lost = telescope != null ? telescope.LostMask : -1;
        int radar = aircraft.TryGetComponent(out RadarSuite suite) ? (suite.Master ? 1 : 0) : -1;
        float beam = aircraft.TryGetComponent(out AwacsBeam awacs) && awacs.Fitted ? awacs.Deploy : float.NaN;
        log.Info(Invariant($"mp-state t={DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()} pid={aircraft.persistentID.Id} sim={(aircraft.LocalSim ? 1 : 0)} player={(aircraft.Player != null ? 1 : 0)} ext={extension:0.000} lost={lost} radar={radar} beam={beam:0.000} words={Words}"));
    }
}
