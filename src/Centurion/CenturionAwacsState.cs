using HarmonyLib;
using UnityEngine;

namespace Centurion;

sealed class CenturionAwacsState : PilotBaseState
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-awacs", typeof(Pilot), nameof(Pilot.SwitchState), new[] { typeof(PilotBaseState) },
            prefix: AccessTools.Method(typeof(CenturionAwacsState), nameof(BeforeSwitchState))),
    };

    // The measured GE.1 loiter point. Idle opens the airbrakes, so recovery and orbit keep at least 0.05.
    const float OrbitHeight = 15000f, OrbitSpeed = 200f, OrbitEntryHeight = 14700f;
    internal const float ThrottleFloor = 0.05f;
    // Under TelescopeController's extend-below Mach 0.70, so the AI span schedule keeps the wing out: retracted at full fuel
    // with the beam, the sortie run topped out near 13.9 km and never reached the orbit.
    const float TransitMach = 0.68f;
    // Speed on pitch: the climb's height 8 km ahead rises 150 m per m/s over V_transit, up to 3,000 m (about 20 deg). At
    // 40 m per m/s and 800 m the sortie runs overspeeded to Mach 0.86 between 5 and 10 km and retracted.
    internal const float ClimbLeadPerMps = 150f, ClimbLeadMaxM = 3000f;
    // Throttle guards the climb's overspeed only: full until 10 m/s over V_transit (the replica peaks at Mach 0.72).
    internal const float ClimbOverspeedMps = 10f;
    // The orbit gives up height below this TAS (OrbitSpeed less 5 m/s).
    const float OrbitEnergyMps = 195f;
    // Detection, not survival, sets the standoff. Owner: "You have to accept the fact that you will be in the range of the
    // R9s, because otherwise, a stealth fighter can just operate with impunity." The design target is the stealthiest stock
    // fighter, an FS-20 Vortex (radarSize 0.001, SmallFighter1.asset; the KR-67 is 0.0015), clean, 1,000 m over the anchor.
    // Lower targets hide in clutter: the beam sees a Vortex 300 m up to 46 km level, 100 m up to 35 km
    // (tools/fm/awacs_detection_standoff.py). Without a working beam, or while it is stowed, a 20 km floor.
    const float StealthRcs = 0.001f, StealthAglM = 1000f, StandoffFloorM = 20000f, StandoffCapM = 75000f;
    Airbase? home, anchor;
    GlobalPosition homePoint;
    bool planned;
    int trackDirection;

    public string Phase { get; private set; } = AircraftReadout.NoText;
    public string HomeName { get; private set; } = AircraftReadout.NoText;
    public string AnchorName { get; private set; } = AircraftReadout.NoText;
    public float StandoffM { get; private set; } = (float)AircraftReadout.NotRead;
    public float AnchorDistM { get; private set; } = (float)AircraftReadout.NotRead;
    public int AnchorChanges { get; private set; }
    public float OrbitS { get; private set; }
    public float RecoveryFuelFrac { get; private set; } = (float)AircraftReadout.NotRead;
    internal AwacsArad Arad { get; } = new();

    static readonly System.Reflection.MethodInfo? CombatMissileAlert = AccessTools.Method(typeof(AIPilotCombatModes), "AICombat_OnMissileAlert");

    // Pilot.cs:185-193 ignores repeated redirects to this aircraft's existing instance.
    static void BeforeSwitchState(Pilot __instance, ref PilotBaseState state)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-awacs")) return;
        if (state is not AIPilotCombatModes) return;
        Aircraft aircraft = __instance.aircraft;
        if (aircraft != null && aircraft.IsServer && aircraft.LocalSim && aircraft.Player == null
            && aircraft.TryGetComponent<CenturionAi>(out var ai) && ai.IsAwacs)
        {
            // The stock combat state subscribes its missile alert in its constructor and drops it only in LeaveState,
            // which an instance replaced here never reaches (AIPilotCombatModes.cs:128, 255).
            if (CombatMissileAlert != null)
                aircraft.GetMissileWarningSystem().onMissileWarning -=
                    AccessTools.MethodDelegate<System.Action<MissileWarning.OnMissileWarning>>(CombatMissileAlert, state);
            state = ai.AwacsState;
        }
    }

    public override void EnterState(Pilot pilot)
    {
        this.pilot = pilot;
        Initialize(pilot);
        pilot.flightInfo.HasTakenOff = true;
        aircraft.SetFlightAssist(true);
        if (aircraft.gearState == LandingGear.GearState.LockedExtended) aircraft.SetGear(false);
        pilot.On1sCheck += Tick;
        pilot.On5sCheck += EjectionCheck;
        Arad.Bind(aircraft);
        if (!planned) homePoint = aircraft.GlobalPosition();
        PlanBases();
        // FuelChecker can return its initial true during the level's first five seconds (PilotBaseState.cs:13-27).
        SetPhase(aircraft.GetFuelLevel() <= 0.2f ? "recovery"
            : aircraft.GlobalPosition().y < OrbitEntryHeight ? "climb" : "orbit");
        Tick();
    }

    public override void UpdateState(Pilot pilot) { }

    void PlanBases()
    {
        FactionHQ? hq = aircraft.NetworkHQ;
        if (home == null || home.disabled || home.CurrentHQ != hq)
        {
            // The combat state's landing query, AIPilotCombatModes.cs:383-391.
            AircraftParameters parameters = aircraft.definition.aircraftParameters;
            var query = new RunwayQuery
            {
                RunwayType = RunwayQueryType.Landing,
                MinSize = parameters.takeoffDistance,
                LandingSpeed = parameters.takeoffSpeed,
                TailHook = aircraft.weaponManager.HasTailHook(),
            };
            home = hq != null ? hq.GetNearestAirbase(aircraft.transform.position, query) : null;
        }
        if (home != null) homePoint = home.center.GlobalPosition();
        HomeName = home != null ? MissionGeometryLog.AirbaseName(home) : AircraftReadout.NoText;

        // The anchor marks the front the beam watches: the hostile field nearest home, of any size, re-picked every tick as
        // fields change hands.
        Airbase? front = null;
        float nearest = float.PositiveInfinity;
        foreach (Airbase candidate in FactionRegistry.airbaseLookup.Values)
        {
            if (!IsHostile(candidate, hq)) continue;
            float distance = AwacsOrbit.LevelDistance(homePoint, candidate.center.GlobalPosition());
            if (distance >= nearest) continue;
            nearest = distance;
            front = candidate;
        }
        if (!planned || !ReferenceEquals(front, anchor))
        {
            string previousName = AnchorName;
            anchor = front;
            AnchorName = anchor != null ? MissionGeometryLog.AirbaseName(anchor) : AircraftReadout.NoText;
            if (planned)
            {
                AnchorChanges++;
                trackDirection = 0;
                CenturionPlugin.Log.Info($"AWACS anchor: {previousName} -> {AnchorName}");
            }
        }
        StandoffM = anchor != null ? DetectionStandoff() : StandoffFloorM;
        planned = true;
    }

    /// <summary>
    /// The farthest standoff at which the beam still sees the design target over the anchor from every point of the track.
    /// The game's radar sees a target while maxRange / d x RCS^0.25, less clutterFactor x clutter, exceeds minSignal
    /// (RadarParams.GetSignalStrength, RadarParams.cs:26-43); a target below the radar's horizon line adds the look-down
    /// clutter 1000 x (radar height - target height) / (d x target radar altitude) for d over 1 km (DetectorManager.cs:52-62).
    /// Both go as 1/d, so the slant reach is closed-form. The beam is stock Radome1's radar (minSignal 0.5, clutterFactor
    /// 0.05, all-round: Radome1.prefab:161-169) at 150 km once deployed: 51.9 km slant, 50.0 km level, and a whole-track
    /// standoff of 24.7 km (<see cref="AwacsOrbit.CoverageStandoff"/>). The nose radar (60 km, clutterFactor 0.3, a 60 deg cone
    /// along the legs) sees that Vortex only to 13 km and adds nothing.
    /// </summary>
    float DetectionStandoff()
    {
        Radar? beam = aircraft.TryGetComponent(out AwacsBeam mount) && mount.Deployed ? mount.BeamRadar : null;
        if (beam == null) return StandoffFloorM;
        RadarParams radar = beam.RadarParameters;
        float drop = OrbitHeight - StealthAglM;
        float slant = (radar.maxRange * Mathf.Pow(StealthRcs, 0.25f) - radar.clutterFactor * 1000f * drop / StealthAglM)
            / Mathf.Max(radar.minSignal, 0.01f);
        float level = slant > drop ? Mathf.Sqrt(slant * slant - drop * drop) : 0f;
        return Mathf.Clamp(AwacsOrbit.CoverageStandoff(level), StandoffFloorM, StandoffCapM);
    }

    static bool IsHostile(Airbase? airbase, FactionHQ? hq) => hq != null && airbase != null && !airbase.disabled
        && airbase.CurrentHQ != null && airbase.CurrentHQ != hq;

    void SetPhase(string phase)
    {
        if (Phase == phase) return;
        Phase = phase;
        OrbitS = 0f;
        if (phase == "recovery") RecoveryFuelFrac = aircraft.GetFuelLevel();
        stateDisplayName = "AWACS " + phase;
    }

    void Tick()
    {
        PlanBases();
        if (!fuelChecker.HasEnoughFuel()) SetPhase("recovery");
        GlobalPosition position = aircraft.GlobalPosition();
        if (Phase == "climb" && position.y >= OrbitEntryHeight) SetPhase("orbit");
        if (Phase == "recovery" && (home == null
            || (position.y < homePoint.y + 1600f && AwacsOrbit.LevelDistance(position, homePoint) < 30000f)))
        {
            pilot.SwitchState(pilot.AILandingState ?? new AIPilotLandingState());
            return;
        }
        Countermeasures();
        Arad.Tick(aircraft, pilot, Phase == "orbit");
    }

    void Countermeasures()
    {
        Missile? nearest = null;
        float distanceSquared = float.PositiveInfinity;
        foreach (Missile missile in missileWarningSystem.knownMissiles)
        {
            if (missile == null || missile.disabled || missile.targetID != aircraft.persistentID) continue;
            float distance = (missile.transform.position - aircraft.transform.position).sqrMagnitude;
            if (distance >= distanceSquared) continue;
            distanceSquared = distance;
            nearest = missile;
        }
        bool active = false;
        if (nearest != null)
        {
            // AIPilotCombatModes.cs:1165-1168, including its 1 m/s minimum closing rate.
            Vector3 delta = nearest.transform.position - aircraft.transform.position;
            float closing = Mathf.Max(Vector3.Dot(-delta.normalized, nearest.rb.velocity - aircraft.rb.velocity), 1f);
            active = delta.magnitude / closing < 8f;
            if (active) aircraft.countermeasureManager.ChooseCountermeasure(nearest);
        }
        aircraft.Countermeasures(active, aircraft.countermeasureManager.activeIndex);
    }

    public override void FixedUpdateState(Pilot pilot)
    {
        GlobalPosition position = aircraft.GlobalPosition();
        float speed = (aircraft.CockpitRB().velocity - aircraft.GetWindVelocity()).magnitude;
        float transit = Mathf.Min(150f * Mathf.Sqrt(LevelInfo.GetAirDensity(0f) / LevelInfo.GetAirDensity(position.y)), OrbitSpeed,
            TransitMach * LevelInfo.GetSpeedOfSound(position.y));
        float targetSpeed = Phase == "recovery" ? transit : OrbitSpeed;
        // Speed on pitch in the climb; in the orbit the same lead below OrbitEnergyMps trades height for speed rather than
        // holding 15 km at full throttle on the back of the drag curve, as the first full-fuel orbit did (155 m/s, 13.3 km).
        float height = Phase switch
        {
            "climb" => position.y + Mathf.Clamp(ClimbLeadPerMps * (speed - transit), -200f, ClimbLeadMaxM),
            "recovery" => Mathf.Max(homePoint.y + 1300f, position.y - 1200f),
            _ => Mathf.Min(OrbitHeight, position.y + Mathf.Clamp(ClimbLeadPerMps * (speed - OrbitEnergyMps), -1000f, ClimbLeadMaxM)),
        };
        controlInputs.throttle = Phase == "climb" ? Mathf.Clamp(1f - 0.1f * (speed - transit - ClimbOverspeedMps), ThrottleFloor, 1f)
            : Mathf.Clamp(0.6f + 0.1f * (targetSpeed - speed), ThrottleFloor, 1f);
        Vector2 mapSize = NetworkSceneSingleton<LevelInfo>.i.LoadedMapSettings.MapSize;
        destination = Phase == "recovery" ? AwacsOrbit.Circle(position, aircraft.transform.forward, homePoint, 10000f, height)
            : anchor == null ? AwacsOrbit.Circle(position, aircraft.transform.forward, homePoint, StandoffM, height)
            : AwacsOrbit.Racetrack(position, aircraft.transform.forward, anchor.center.GlobalPosition(), homePoint, StandoffM, height,
                mapSize, ref trackDirection);
        if (Phase == "orbit") Arad.TurnAim(aircraft, position, height, ref destination);
        aircraft.autopilot.AutoAim(destination, aimVelocity: true, ignoreCollisions: false, runwayAlign: false,
            0.5f, 40f, followTerrain: false, 0f, Vector3.zero);
        AnchorDistM = anchor != null ? AwacsOrbit.LevelDistance(position, anchor.center.GlobalPosition()) : (float)AircraftReadout.NotRead;
        if (Phase == "orbit") OrbitS += Time.fixedDeltaTime;
    }

    // Same crippled-aircraft policy as AIPilotCombatModes.cs:1230-1249.
    void EjectionCheck()
    {
        if (aircraft.cockpit.xform.position.y < Datum.LocalSeaY
            || (aircraft.speed < 1f && aircraft.radarAlt < 1f)
            || (aircraft.radarAlt > 40f && (Vector3.Dot(aircraft.cockpit.xform.forward, aircraft.rb.velocity) < 0f
                || aircraft.partDamageTracker.GetDetachedRatio() > 0.12f)))
            aircraft.StartEjectionSequence();
    }

    public override void LeaveState()
    {
        pilot.On1sCheck -= Tick;
        pilot.On5sCheck -= EjectionCheck;
        Arad.Unbind(aircraft);
        aircraft.Countermeasures(false, aircraft.countermeasureManager.activeIndex);
        Phase = AircraftReadout.NoText;
        OrbitS = 0f;
    }
}
