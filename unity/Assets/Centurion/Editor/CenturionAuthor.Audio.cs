using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace Centurion.Editor
{
    public static partial class CenturionAuthor
    {
        private const string SweepClipPath = "Assets/Blueprinter/_donotship/AudioClip/ShelterMovingSound_PLACEHOLDER.ogg";

        private static void AddSurfaceAudio(Build b)
        {
            var roots = (b.Parts["wing_root_L"].transform.position + b.Parts["wing_root_R"].transform.position) * 0.5f;
            var flaps = (b.Parts["flap_L1"].transform.position + b.Parts["flap_R1"].transform.position) * 0.5f;
            // One central hydraulic drive with two co-located layers, as auditioned, rather than a pair on every stage.
            Add("telescope_audio_a", roots, Load<AudioClip>(SweepClipPath), 30f, 50f);
            Add("telescope_audio_b", roots, Load<AudioClip>(SweepClipPath), 30f, 50f);
            Add("flap_audio", flaps, Load<AudioClip>(EngineAudioFolder + "/centurion_flap_loop.wav"), 30f, 50f);

            void Add(string name, Vector3 position, AudioClip clip, float min, float max)
            {
                var go = new GameObject(name);
                go.transform.SetParent(b.Parts["fuselage_F"].transform, false);
                go.transform.position = position;
                var source = go.AddComponent<AudioSource>();
                source.clip = clip;
                source.outputAudioMixerGroup = EngineAudioSource(b.Root.GetComponentsInChildren(GameType("Turbofan"), true).First(), "turbineAudio").outputAudioMixerGroup;
                source.loop = true;
                source.playOnAwake = false;
                source.volume = 0f;
                source.spatialBlend = 1f;
                source.rolloffMode = AudioRolloffMode.Logarithmic;
                source.minDistance = min;
                source.maxDistance = max;
                source.dopplerLevel = 0f;
                source.bypassListenerEffects = true;
            }
        }

        private static void CheckSurfaceAudio(Build b)
        {
            foreach (var name in new[] { "telescope_audio_a", "telescope_audio_b", "flap_audio" })
            {
                var sources = b.Root.GetComponentsInChildren<AudioSource>(true).Where(s => s.name == name).ToArray();
                var clipPath = name == "flap_audio" ? EngineAudioFolder + "/centurion_flap_loop.wav" : SweepClipPath;
                if (sources.Length != 1 || sources[0].clip == null || sources[0].clip != Load<AudioClip>(clipPath))
                    throw new InvalidDataException(name + " requires its selected AudioClip reference: " + clipPath);
                var source = sources[0];
                if (!source.loop || source.playOnAwake || source.volume != 0f || source.spatialBlend != 1f
                    || source.rolloffMode != AudioRolloffMode.Logarithmic || source.minDistance != 30f || source.maxDistance != 50f
                    || source.dopplerLevel != 0f || !source.bypassListenerEffects
                    || source.outputAudioMixerGroup == null || source.outputAudioMixerGroup.name != "Effects_General")
                    throw new InvalidDataException(name + " must start silent with the stock 3D sweep settings and Effects_General routing");
                if (name == "flap_audio" && source.clip.channels != 1)
                    throw new InvalidDataException("Flap audio requires the mono mod-owned candidate B loop");
            }
            b.Report.Add("Surface audio: 2 ShelterMovingSound placeholder layers, 1 centurion_flap_loop; clips and Effects_General routing checked");
        }
    }
}
