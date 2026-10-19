using System.Linq;
using UnityEngine;

namespace Centurion;

/// <summary>The authored flight deck bed, audible only inside this aircraft's cockpit.</summary>
sealed class CabinEngineSound : MonoBehaviour
{
    // A separate cabin layer has no stock gain to inherit. Start within the 0.1 to 0.15 audition range.
    const float CabinVolume = 0.12f;
    const float TurbineMaxPitch = 1.2f;
    Aircraft aircraft = null!;
    AudioSource source = null!;
    Turbofan[] engines = null!;

    void Awake()
    {
        aircraft = GetComponent<Aircraft>();
        source = aircraft.cockpit.transform.Find("flightdeck_int").GetComponent<AudioSource>();
        engines = aircraft.engineStates.OfType<Turbofan>().ToArray();
    }

    void LateUpdate()
    {
        if (source == null) return;
        CameraStateManager cam = SceneSingleton<CameraStateManager>.i;
        // CameraStateManager.SwitchState:177 and CameraCockpitState.EnterState:56 use this state and followed unit.
        bool inside = aircraft != null && cam != null && cam.currentState == cam.cockpitState && cam.followingUnit == aircraft;
        float rpmRatio = 0f;
        foreach (Turbofan engine in engines)
            if (engine != null) rpmRatio += engine.GetRPMRatio();
        if (engines.Length > 0) rpmRatio /= engines.Length;
        source.volume = inside && rpmRatio > 0f ? CabinVolume : 0f;
        source.pitch = rpmRatio * TurbineMaxPitch;
        if (source.volume > 0f)
        {
            if (!source.isPlaying) source.Play();
        }
        else if (source.isPlaying) source.Stop();
    }

    void OnDisable()
    {
        if (source != null) source.Stop();
    }
}
