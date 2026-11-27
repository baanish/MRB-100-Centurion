using System.Linq;
using UnityEngine;

namespace Centurion;

/// <summary>
/// Moves the flight deck's three state levers, which nothing in the game moves (the stock Cockpit animates only the sticks
/// and the throttles, from the control inputs: Cockpit.cs:23-46). Each lever is its own part in the export
/// (art/blender/cockpit/flightdeck_build.py LEVERS), standing at the rest end of its slot, with an empty at the other end,
/// <c>&lt;name&gt;_end</c>, that authoring places from its slide axis and travel (CenturionAuthor.FlightDeck.cs); the lever
/// slides between the two:
/// - <c>lever_gear</c>: DOWN at rest, UP with the gear commanded up (Aircraft.gearState retracted or retracting), moving
///   over a third of a second, from the command rather than the legs' travel;
/// - <c>lever_span</c>: RET at rest, EXT at a full commanded span (<see cref="TelescopeController.Command"/>), in
///   proportion between;
/// - <c>lever_flap</c>: 0 at rest, 30 at the far end, 15 midway: the flap command the surfaces follow
///   (<see cref="SurfaceRules.ReadFlapCommand"/>).
/// As the stock Cockpit, it moves them only on the aircraft the HUD shows (Cockpit_OnAircraftInitialize enables the
/// cockpit for CombatHUD's aircraft and disables it for every other): no one sees any other aircraft's cockpit. Added to
/// each Centurion by <see cref="CenturionSystems"/>; a lever it cannot find stays where it stands, with one log line.
/// </summary>
sealed class CockpitLevers : MonoBehaviour
{
    const float GearSeconds = 0.33f;
    const float FlapFullDeg = 30f;

    Aircraft aircraft = null!;
    TelescopeController? telescope;
    Lever? gear, span, flap;
    ControlSurface[] surfaces = System.Array.Empty<ControlSurface>();
    bool found;

    sealed class Lever
    {
        public Transform Part = null!;
        public Vector3 Rest, End;
        public float At;

        public void Set(float at)
        {
            At = at;
            Part.localPosition = Vector3.Lerp(Rest, End, at);
        }
    }

    void Start()
    {
        aircraft = GetComponent<Aircraft>();
        telescope = GetComponent<TelescopeController>();
        // Complex physics unparents each part onto its own rigidbody (AeroPart.CreateRB), so the cockpit is found through
        // partLookup, not the aircraft's children (as WingDisplay finds its canvas).
        var all = aircraft.partLookup.Where(p => p != null).SelectMany(p => p.GetComponentsInChildren<Transform>(true)).ToList();
        Lever? Find(string name)
        {
            Transform? part = all.FirstOrDefault(t => t.name == name), end = all.FirstOrDefault(t => t.name == name + "_end");
            return part == null || end == null || end.parent != part.parent ? null
                : new Lever { Part = part, Rest = part.localPosition, End = end.localPosition };
        }
        gear = Find("lever_gear");
        span = Find("lever_span");
        flap = Find("lever_flap");
        found = gear != null || span != null || flap != null;
        surfaces = aircraft.partLookup.Where(p => p != null).Select(p => p.GetComponent<ControlSurface>()).Where(s => s != null).ToArray();
        if (gear == null || span == null || flap == null)
        {
            CenturionPlugin.Log.Warning($"cockpit levers on {aircraft.name}: " + string.Join(", ",
                new[] { ("lever_gear", gear), ("lever_span", span), ("lever_flap", flap) }.Where(l => l.Item2 == null).Select(l => l.Item1))
                + " or its _end missing, so it stays where it stands");
        }
    }

    void Update()
    {
        if (!found || SceneSingleton<CombatHUD>.i == null || SceneSingleton<CombatHUD>.i.aircraft != aircraft)
        {
            return;
        }

        if (gear != null && aircraft.gearState != LandingGear.GearState.Uninitialized)
        {
            bool up = aircraft.gearState == LandingGear.GearState.LockedRetracted || aircraft.gearState == LandingGear.GearState.Retracting;
            gear.Set(Mathf.MoveTowards(gear.At, up ? 1f : 0f, Time.deltaTime / GearSeconds));
        }

        if (span != null && telescope != null)
        {
            span.Set(Mathf.Clamp01(telescope.Command));
        }

        if (flap != null)
        {
            float deg = 0f;
            foreach (ControlSurface surface in surfaces)
            {
                if (surface != null && SurfaceRules.ReadFlapCommand(surface, out float command))
                {
                    deg = Mathf.Max(deg, command);
                }
            }

            flap.Set(Mathf.Clamp01(deg / FlapFullDeg));
        }
    }
}
