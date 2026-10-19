using System.Linq;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>What the span should do about a medium hangar (<see cref="HangarGuard.Approach"/>).</summary>
enum HangarGuardAction { Clear, Retract, Snap }

/// <summary>
/// Where an aircraft stands against the medium hangars (hangar_med, the only one the Centurion fits): the telescoping span
/// keeps out of them (<see cref="Approach"/>) and the AWACS beam stays stowed near them (<see cref="Holds"/>). Spawn
/// transforms are read each step, since a hangar on a moving unit carries it along (Hangar.cs:505-507, 627-631); the hangar
/// list is looked up again every <see cref="ScanS"/>, since a client's or a carrier's hangars register after the mission start.
/// One instance per aircraft and caller.
/// </summary>
sealed class HangarGuard
{
    const string MediumHangarKey = "hangar_med";
    const float ScanS = 5f;
    // Radar altitude above 1 m for less than this is still the ground: a bounce or a bump on the taxiway.
    const float GroundHopS = 0.5f;

    readonly Aircraft aircraft;
    Transform[] spawns = System.Array.Empty<Transform>();
    float scannedAt = float.NegativeInfinity, onGroundAt = float.NegativeInfinity;

    public HangarGuard(Aircraft aircraft) => this.aircraft = aircraft;

    /// <summary>The spawn point (floor centre) of the medium hangar nearest the aircraft on the ground plane; null when the map has none.</summary>
    public Transform? Spawn
    {
        get
        {
            Scan();
            Vector3 position = aircraft.transform.position;
            Transform? nearest = null;
            float nearestM = float.PositiveInfinity;
            foreach (Transform spawn in spawns)
            {
                if (spawn != null)
                {
                    float distance = Vector3.ProjectOnPlane(spawn.position - position, Vector3.up).magnitude;
                    if (distance < nearestM)
                    {
                        nearest = spawn;
                        nearestM = distance;
                    }
                }
            }

            return nearest;
        }
    }

    /// <summary>On the ground (<see cref="GroundHopS"/>) within radiusM of any medium hangar's spawn point.</summary>
    public bool Holds(float radiusM)
    {
        if (!OnGround())
        {
            return false;
        }

        Scan();
        Vector3 position = aircraft.transform.position;
        foreach (Transform spawn in spawns)
        {
            if (spawn != null && Vector3.ProjectOnPlane(spawn.position - position, Vector3.up).magnitude < radiusM)
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>
    /// For the span, on the ground (<see cref="GroundHopS"/>), near any medium hangar or on a path into one: the door is 45.8 m
    /// wide against 87.1 m extended. Inside reachM plus marginM the span holds at 0. Further out, if the straight ground track
    /// enters the reach, the span retracts while the stages can still be home first, at this speed and the extension's
    /// remaining slew (extension times travelS seconds), plus the margin; when even that is too late it snaps home.
    /// </summary>
    public HangarGuardAction Approach(float reachM, float marginM, float extension, float travelS)
    {
        if (!OnGround())
        {
            return HangarGuardAction.Clear;
        }

        Scan();
        Vector3 position = aircraft.transform.position;
        Vector3 velocity = Vector3.ProjectOnPlane(aircraft.rb.velocity, Vector3.up);
        float speed = velocity.magnitude;
        float slewM = speed * extension * travelS;
        HangarGuardAction worst = HangarGuardAction.Clear;
        foreach (Transform spawn in spawns)
        {
            if (spawn == null)
            {
                continue;
            }

            Vector3 toHangar = Vector3.ProjectOnPlane(spawn.position - position, Vector3.up);
            float distance = toHangar.magnitude;
            if (distance < reachM + marginM)
            {
                return HangarGuardAction.Retract;
            }

            float along = speed > 0.1f ? Vector3.Dot(toHangar, velocity) / speed : 0f;
            float miss2 = distance * distance - along * along;
            if (along <= 0f || miss2 >= reachM * reachM)
            {
                continue;
            }

            // Ground distance along the track to where it enters the reach.
            float entry = along - Mathf.Sqrt(reachM * reachM - miss2);
            if (entry < slewM)
            {
                CenturionPlugin.Log.Stage("hangar-guard-snap", Invariant($"{aircraft.name}: {entry:0} m from a medium hangar's reach at {speed:0.0} m/s, extension {extension:0.00} snapped home"));
                return HangarGuardAction.Snap;
            }

            if (entry < slewM + marginM)
            {
                worst = HangarGuardAction.Retract;
            }
        }

        return worst;
    }

    bool OnGround()
    {
        if (aircraft.radarAlt < 1f)
        {
            onGroundAt = Time.fixedTime;
        }

        return Time.fixedTime - onGroundAt <= GroundHopS;
    }

    void Scan()
    {
        if (Time.fixedTime - scannedAt <= ScanS)
        {
            return;
        }

        scannedAt = Time.fixedTime;
        spawns = Object.FindObjectsOfType<Hangar>()
            .Where(h => h.TryGetComponent(out Unit unit) && unit.definition != null && unit.definition.jsonKey == MediumHangarKey && h.GetSpawnTransform() != null)
            .Select(h => h.GetSpawnTransform()).ToArray();
    }
}
