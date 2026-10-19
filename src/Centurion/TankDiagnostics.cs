using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace Centurion;

static class TankDiagnostics
{
    internal static ConfigEntry<string> Hit = null!;
    static readonly string[] Names = { "fuselage_M", "fuselage_F", "fuselage_R", "tailcone" };
    static readonly FieldInfo? TankPart = AccessTools.Field(typeof(FuelTank), "part");
    static readonly FieldInfo? OnFire = AccessTools.Field(typeof(FuelTank), "onFire");
    static readonly FieldInfo? FireSpawn = AccessTools.Field(typeof(FuelTank), "fireEffectSpawn");
    static readonly FieldInfo? LeakRate = AccessTools.Field(typeof(FuelTank), "leakRate");
    static Aircraft? hitAircraft;
    static string applied = "";

    internal static void ApplyHit(Aircraft aircraft)
    {
        if (aircraft != hitAircraft)
        {
            hitAircraft = aircraft;
            applied = "";
        }
        string name = Hit.Value;
        if (name == "") { applied = ""; return; }
        if (name == applied || aircraft.definition == null || aircraft.definition.jsonKey != "baanish_centurion"
            || !aircraft.LocalSim || !aircraft.IsServer) return;
        applied = name;
        UnitPart? part = aircraft.partLookup.FirstOrDefault(p => p != null
            && (p.gameObject == aircraft.gameObject ? "fuselage_M" : p.name) == name);
        if (part == null || part.IsDetached() || part.hitPoints < 99f || part.GetComponent<FuelTank>() == null)
        {
            CenturionPlugin.Log.Warning("Debug.TankHit requires an intact part with a fuel tank");
            return;
        }
        // Net damage through the stock RPC, not a forced tank status. At 49 HP the donor tank leaks 22 kg/s;
        // 1 fire damage exceeds its 1/leakRate ignition threshold, so the stock damage handler ignites it.
        aircraft.Damage(part.id, new DamageInfo(50f, 0f, 1f, 0f));
        CenturionPlugin.Log.Info("Debug.TankHit: stock damage sent to " + name);
    }

    internal static void AddDefaults(Dictionary<string, object> state)
    {
        var tanks = new Dictionary<string, object>();
        foreach (string name in Names)
        {
            var tank = new Dictionary<string, object> { ["readable"] = false, ["on_fire"] = false, ["fire_active"] = false };
            foreach (string key in new[] { "fuel_kg", "leak_kg_s", "part_hp", "tank_offset_m", "fire_offset_m", "fire_tank_offset_m",
                "fire_x_m", "fire_y_m", "fire_z_m", "fire_check_x_m", "fire_check_y_m", "fire_check_z_m" })
                tank[key] = AircraftReadout.NotRead;
            tanks[name] = tank;
        }
        state["fuel_tanks"] = tanks;
    }

    internal static void Read(Aircraft aircraft, Dictionary<string, object> state)
    {
        if (TankPart == null || OnFire == null || FireSpawn == null || LeakRate == null) return;
        var tanks = (Dictionary<string, object>)state["fuel_tanks"];
        foreach (FuelTank tank in aircraft.GetFuelTanks())
        {
            if (tank == null || TankPart.GetValue(tank) is not UnitPart part) continue;
            string name = part.gameObject == aircraft.gameObject ? "fuselage_M" : part.name;
            if (!tanks.TryGetValue(name, out object entry)) continue;
            var values = (Dictionary<string, object>)entry;
            Transform centre = part.CenterOfMass != null ? part.CenterOfMass : part.transform;
            values["readable"] = true;
            values["fuel_kg"] = AircraftReadout.Round(tank.GetLevel());
            values["leak_kg_s"] = AircraftReadout.Round((float)LeakRate.GetValue(tank));
            values["part_hp"] = AircraftReadout.Round(part.hitPoints);
            values["on_fire"] = (bool)OnFire.GetValue(tank);
            values["tank_offset_m"] = AircraftReadout.Round(Vector3.Distance(tank.transform.position, centre.position));
            Vector3 check = aircraft.transform.InverseTransformPoint(tank.transform.position);
            values["fire_check_x_m"] = AircraftReadout.Round(check.x);
            values["fire_check_y_m"] = AircraftReadout.Round(check.y);
            values["fire_check_z_m"] = AircraftReadout.Round(check.z);
            var effect = FireSpawn.GetValue(tank) as GameObject;
            if (effect == null) continue;
            values["fire_active"] = effect.activeInHierarchy;
            Vector3 fire = aircraft.transform.InverseTransformPoint(effect.transform.position);
            values["fire_x_m"] = AircraftReadout.Round(fire.x);
            values["fire_y_m"] = AircraftReadout.Round(fire.y);
            values["fire_z_m"] = AircraftReadout.Round(fire.z);
            values["fire_offset_m"] = AircraftReadout.Round(Vector3.Distance(effect.transform.position, centre.position));
            values["fire_tank_offset_m"] = AircraftReadout.Round(Vector3.Distance(effect.transform.position, tank.transform.position));
        }
    }
}
