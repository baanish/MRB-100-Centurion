using System;
using System.Reflection;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

sealed class TankFireSpread : MonoBehaviour
{
    // Stock collider fire can spread sooner; 40 s caps the wait for an attached, fuelled neighbour.
    internal const float BurnS = 40f;
    static readonly string[] Names = { "fuselage_F", "fuselage_M", "fuselage_R", "tailcone" };
    static readonly FieldInfo? TankPart = AccessTools.Field(typeof(FuelTank), "part");
    static readonly FieldInfo? OnFire = AccessTools.Field(typeof(FuelTank), "onFire");
    readonly FuelTank?[] tanks = new FuelTank?[Names.Length];
    readonly UnitPart?[] parts = new UnitPart?[Names.Length];
    readonly float[] startedAt = { -1f, -1f, -1f, -1f };
    Aircraft aircraft = null!;

    void Awake()
    {
        aircraft = GetComponent<Aircraft>();
        if (TankPart == null || OnFire == null)
        {
            CenturionPlugin.Log.Error("tank fire spread: FuelTank.part/onFire missing; spread disabled");
            enabled = false;
            return;
        }
        foreach (FuelTank tank in aircraft.GetFuelTanks())
        {
            if (tank == null || TankPart.GetValue(tank) is not UnitPart part || part == null) continue;
            int index = Array.IndexOf(Names, part.gameObject == aircraft.gameObject ? "fuselage_M" : part.name);
            if (index < 0) continue;
            tanks[index] = tank;
            parts[index] = part;
        }
    }

    void Update()
    {
        if (!aircraft.IsServer) return;
        float now = Time.time;
        for (int i = 0; i < tanks.Length; i++)
        {
            FuelTank? tank = tanks[i];
            UnitPart? part = parts[i];
            bool burning = tank != null && part != null && !part.IsDetached()
                && (bool)OnFire!.GetValue(tank);
            startedAt[i] = burning ? (startedAt[i] < 0f ? now : startedAt[i]) : -1f;
        }
        for (int i = 0; i < tanks.Length; i++)
        {
            if (startedAt[i] < 0f || now - startedAt[i] < BurnS) continue;
            Ignite(i, i - 1);
            Ignite(i, i + 1);
        }
    }

    void Ignite(int from, int to)
    {
        if (to < 0 || to >= tanks.Length) return;
        FuelTank? tank = tanks[to];
        UnitPart? part = parts[to];
        if (tank == null || part == null || part.IsDetached() || tank.GetLevel() <= 0f
            || (bool)OnFire!.GetValue(tank)) return;
        // Unit.FuelTankStatus sends the reliable stock RPC, whose receiver calls FuelTank.UpdateStatus.
        aircraft.FuelTankStatus(part.id, false, true);
        // A dedicated server has no local client to receive that RPC, but must start stock fire damage too.
        if (!(bool)OnFire.GetValue(tank)) tank.UpdateStatus(false, true);
        CenturionPlugin.Log.Info(Invariant($"tank fire spread: {Names[from]} -> {Names[to]} after {Time.time - startedAt[from]:0.0} s"));
    }

    internal float BurningSeconds(string name)
    {
        int index = Array.IndexOf(Names, name);
        return index < 0 || startedAt[index] < 0f ? 0f : Time.time - startedAt[index];
    }
}
