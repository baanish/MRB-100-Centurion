using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Centurion;

/// <summary>
/// Turns each engine's detailed fan with its RPM. The stock Turbofan turns nothing (the Alkyon's engine is a Turbofan, a
/// capsule and an audio source, with no rotor), so without this the Centurion's fans stand still. The fan is
/// <c>fan_K_mesh</c> beside engine K under <c>nacelle_K</c> (CenturionAuthor.AddFan, which checks its pivot is on the
/// engine's axis and its spin axis is local Z). Added to each Centurion by <see cref="CenturionSystems"/>; visual only, so
/// every peer runs it from its own engines.
/// </summary>
sealed class FanSpin : MonoBehaviour
{
    const string FanPrefix = "fan_", FanSuffix = "_mesh";
    // The real fan's 1,700 to 2,000 rpm moves its 22 blades (16.4 deg apart) one to eight pitches a frame, which reads as
    // a random flicker or a slow turn backwards. So the fan turns at most 0.4 of a pitch a frame, always read as forward
    // motion, and in proportion to the RPM below that: 400 deg/s at full RPM is the cap at 60 fps.
    const float FullRpmDegPerS = 400f;
    const float MaxStepDeg = 6.5f;

    readonly List<(Turbofan Engine, Transform Fan)> fans = new();
    readonly double[] turnDeg = new double[2];

    internal void Read(Dictionary<string, object> state)
    {
        state["fans_found"] = fans.Count;
        for (int i = 0; i < turnDeg.Length; i++) state[$"fan_{i + 1}_turn_deg"] = System.Math.Round(turnDeg[i], 3);
    }

    void Awake()
    {
        // Complex physics unparents the nacelles before SetLocalSim adds this component.
        foreach (Turbofan engine in GetComponent<Aircraft>().engineStates.OfType<Turbofan>())
        {
            Transform? nacelle = engine.transform.parent;
            if (nacelle == null)
            {
                continue;
            }

            foreach (Transform child in nacelle)
            {
                if (child.name.StartsWith(FanPrefix) && child.name.EndsWith(FanSuffix))
                {
                    fans.Add((engine, child));
                }
            }
        }
    }

    void Update()
    {
        foreach ((Turbofan engine, Transform fan) in fans)
        {
            if (engine == null || fan == null)
            {
                continue;
            }

            // The blades' leading edges lead with the top of the disc moving to the aircraft's right (local +X): a turn
            // about local Z by a negative angle (m4/engines.py blade_section).
            float step = Mathf.Min(engine.GetRPMRatio() * FullRpmDegPerS * Time.deltaTime, MaxStepDeg);
            fan.Rotate(0f, 0f, -step, Space.Self);
            int index = fan.name == "fan_1_mesh" ? 0 : 1;
            turnDeg[index] += step;
        }
    }
}
