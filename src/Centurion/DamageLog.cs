using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// A stage line for every hit the local player's Centurion takes: a part's damage (net amount by kind, hit points
/// left), a part coming off (with the part it hung from), a joint breaking, a gear leg breaking. The game's damage event
/// (UnitPart.onApplyDamage) carries no dealer, so the source is the damage kind; impact is a collision. A part coming
/// off or a joint breaking applies no damage, which is what the framework's damage event with amount 0 means. Only the
/// Centurion's own parts are subscribed, so nothing runs for any other unit.
/// </summary>
sealed class DamageLog
{
    /// <summary>AircraftDefinition.jsonKey of the Centurion (CenturionAuthor.JsonKey).</summary>
    const string CenturionKey = "baanish_centurion";

    sealed class Watched
    {
        public string Parent = "";
        public Action<UnitPart.OnApplyDamage> Damage = null!;
    }

    readonly CenturionLog log;
    readonly Dictionary<UnitPart, Watched> parts = new();
    readonly List<LandingGear> gears = new();
    Aircraft? bound;

    public DamageLog(CenturionLog log) => this.log = log;

    /// <summary>Every frame: follows the local Centurion, and its part list, which fills as the parts wake.</summary>
    public void Update(bool enabled)
    {
        Aircraft? aircraft = enabled && GameManager.GetLocalAircraft(out Aircraft local) && local.definition != null && local.definition.jsonKey == CenturionKey ? local : null;
        if (aircraft != bound)
        {
            Unbind();
            if (aircraft != null)
            {
                bound = aircraft;
                gears.AddRange(aircraft.GetComponentsInChildren<LandingGear>(true));
                gears.ForEach(g => g.onGearBreak += GearBroke);
            }
        }

        if (bound != null && bound.partLookup.Count != parts.Count)
        {
            UnbindParts();
            foreach (UnitPart part in bound.partLookup)
            {
                var watched = new Watched
                {
                    Parent = part.transform.parent != null && part.transform.parent.GetComponentInParent<UnitPart>() is UnitPart parent ? parent.name : "the aircraft",
                    Damage = d => Damaged(part, d),
                };
                parts[part] = watched;
                part.onApplyDamage += watched.Damage;
                part.onPartDetached += Detached;
                part.onJointBroken += JointBroken;
            }
        }
    }

    void Damaged(UnitPart part, UnitPart.OnApplyDamage d)
    {
        var kinds = new[] { ("pierce", d.pierceDamage), ("blast", d.blastDamage), ("fire", d.fireDamage), ("impact", d.impactDamage) }
            .Where(k => k.Item2 != 0f).Select(k => Invariant($"{k.Item1} {k.Item2:0.##}"));
        float total = d.pierceDamage + d.blastDamage + d.fireDamage + d.impactDamage;
        log.Stage("damage " + part.name, Invariant($"{part.name} took {total:0.##} hp ({string.Join(", ", kinds)}), {d.hitPoints:0.#} hp left{(d.detached ? ", detached" : "")}"));
    }

    void Detached(UnitPart part) =>
        log.Stage("detach " + part.name, Invariant($"{part.name} came off {(parts.TryGetValue(part, out Watched w) ? w.Parent : "?")} with {part.hitPoints:0.#} hp"));

    /// <summary>UnitPart raises this for any joint on the part breaking (OnJointBreak) and when it fragments.</summary>
    void JointBroken(UnitPart part) =>
        log.Stage("joint " + part.name, Invariant($"a joint on {part.name} broke or it fragmented, {part.hitPoints:0.#} hp"));

    void GearBroke(LandingGear gear) => log.Stage("gear " + gear.name, $"gear leg {gear.name} broke");

    void UnbindParts()
    {
        foreach (KeyValuePair<UnitPart, Watched> entry in parts)
        {
            entry.Key.onApplyDamage -= entry.Value.Damage;
            entry.Key.onPartDetached -= Detached;
            entry.Key.onJointBroken -= JointBroken;
        }

        parts.Clear();
    }

    void Unbind()
    {
        UnbindParts();
        gears.ForEach(g => g.onGearBreak -= GearBroke);
        gears.Clear();
        bound = null;
    }
}
