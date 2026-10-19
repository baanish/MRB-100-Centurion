using System.Linq;
using UnityEngine;

namespace Centurion;

sealed class SurfaceMotionSound : MonoBehaviour
{
    // Keep idle landing near its selected level while the louder clip competes with full thrust.
    const float FlapIdleVolume = 0.45f;
    Aircraft aircraft = null!;
    AudioSource wingA = null!, wingB = null!, flap = null!;
    Turbofan[] engines = null!;
    (ControlSurface surface, float angle)[] flaps = null!;
    float wingVolume;
    bool sampledFlaps;

    internal static SurfaceMotionSound For(Aircraft aircraft) =>
        aircraft.TryGetComponent(out SurfaceMotionSound sound) ? sound : aircraft.gameObject.AddComponent<SurfaceMotionSound>();

    void Start()
    {
        aircraft = GetComponent<Aircraft>();
        engines = aircraft.engineStates.OfType<Turbofan>().ToArray();
        var sources = aircraft.partLookup.Where(p => p != null).SelectMany(p => p.GetComponentsInChildren<AudioSource>(true)).ToArray();
        wingA = sources.FirstOrDefault(s => s.name == "telescope_audio_a")!;
        wingB = sources.FirstOrDefault(s => s.name == "telescope_audio_b")!;
        flap = sources.FirstOrDefault(s => s.name == "flap_audio")!;
        if (wingA == null || wingB == null || flap == null || wingA.clip == null || wingB.clip == null || flap.clip == null)
        {
            CenturionPlugin.Log.Error("Surface motion audio needs the authored telescope and flap sources with clips");
            enabled = false;
            return;
        }
        flaps = aircraft.partLookup.Where(p => p != null).Select(p => p.GetComponent<ControlSurface>())
            .Where(s => s != null && FlapPreset.ReadMotion(s, out _, out _)).Select(s => (s, 0f)).ToArray();
        foreach (var source in new[] { wingA, wingB, flap }) aircraft.RegisterDopplerSound(source);
    }

    bool Followed => aircraft != null && !aircraft.disabled && aircraft.isActiveAndEnabled && SceneSingleton<CameraStateManager>.i != null
        && SceneSingleton<CameraStateManager>.i.followingUnit == aircraft;

    internal void WingMotion(float rate, bool stop)
    {
        if (!enabled || wingA == null || wingB == null) return;
        // Preserve the Alkyon's Clamp law, including its alternating full-motion gain and pitch.
        wingVolume = stop || !Followed ? 0f : Mathf.Clamp(rate - wingVolume,
            wingVolume - 4f * Time.fixedDeltaTime, wingVolume + 4f * Time.fixedDeltaTime);
        float n = Mathf.InverseLerp(0.1f, 1f, wingVolume);
        Play(wingA, n * 0.85f, Mathf.Lerp(0.2f, 1f, n) * 0.75f);
        Play(wingB, n * 0.30f, Mathf.Lerp(0.2f, 1f, n) * 0.55f, 1.7f);
    }

    void FixedUpdate()
    {
        if (flap == null || flaps == null) return;
        float rate = 0f;
        for (int i = 0; i < flaps.Length; i++)
        {
            if (flaps[i].surface == null || !FlapPreset.ReadMotion(flaps[i].surface, out float angle, out float speed)) continue;
            float delta = Mathf.Abs(angle - flaps[i].angle), step = speed * Time.fixedDeltaTime;
            // Initialization and correction snaps are not servo travel. Each direction reaches full gain at its own rate.
            if (sampledFlaps && step > 0f && delta <= step * 1.1f)
                rate = Mathf.Max(rate, Mathf.Clamp01(delta / step));
            flaps[i].angle = angle;
        }
        sampledFlaps = true;
        float rpmRatio = 0f, idleRatio = 0f;
        foreach (Turbofan engine in engines)
            if (engine != null)
            {
                rpmRatio += engine.GetRPMRatio();
                idleRatio += engine.GetMinRPM() / engine.GetMaxRPM();
            }
        if (engines.Length > 0) { rpmRatio /= engines.Length; idleRatio /= engines.Length; }
        float volume = Mathf.Lerp(FlapIdleVolume, 1f, Mathf.InverseLerp(idleRatio, 1f, rpmRatio));
        Play(flap, Followed ? rate * volume : 0f, 1f);
    }

    static void Play(AudioSource source, float volume, float pitch, float offset = 0f)
    {
        if (source == null) return;
        source.volume = volume;
        source.pitch = pitch;
        if (volume > 0f)
        {
            if (!source.isPlaying) { source.time = offset; source.Play(); }
        }
        else if (source.isPlaying) source.Stop();
    }

    void LateUpdate()
    {
        if (!Followed) OnDisable();
    }

    void OnDisable()
    {
        wingVolume = 0f;
        sampledFlaps = false;
        Play(wingA, 0f, 1f);
        Play(wingB, 0f, 1f);
        Play(flap, 0f, 1f);
    }

    void OnDestroy()
    {
        if (aircraft == null) return;
        foreach (var source in new[] { wingA, wingB, flap })
            if (source != null) aircraft.DeregisterDopplerSound(source);
    }
}
