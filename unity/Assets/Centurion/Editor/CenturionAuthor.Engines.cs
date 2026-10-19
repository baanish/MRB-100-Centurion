using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace Centurion.Editor
{
    public static partial class CenturionAuthor
    {
        private const string EngineAudioFolder = ModFolder + "/Audio";

        private static void SwapEngineAudio(Build b)
        {
            foreach (var engine in b.Root.GetComponentsInChildren(GameType("Turbofan"), true))
                EngineAudioSource(engine, "turbineAudio").clip = Load<AudioClip>(EngineAudioFolder + "/centurion_fan_loop.wav");
            foreach (var nozzle in b.Root.GetComponentsInChildren(GameType("JetNozzle"), true))
                EngineAudioSource(nozzle, "thrustAudio").clip = Load<AudioClip>(EngineAudioFolder + "/centurion_thrust_loop.wav");
        }

        private static AudioSource EngineAudioSource(Component driver, string field)
        {
            var source = Prop(new SerializedObject(driver), field).objectReferenceValue as AudioSource;
            if (source == null) throw new InvalidDataException(driver.name + "." + field + " has no AudioSource");
            return source;
        }

        private static void AddCabinEngineSource(Build b, GameObject interior)
        {
            var source = interior.AddComponent<AudioSource>();
            source.clip = Load<AudioClip>(EngineAudioFolder + "/centurion_cabin_loop.wav");
            source.outputAudioMixerGroup = EngineAudioSource(b.Root.GetComponentsInChildren(GameType("Turbofan"), true).First(), "turbineAudio").outputAudioMixerGroup;
            source.loop = true;
            source.playOnAwake = false;
            source.spatialBlend = 0f;
            source.dopplerLevel = 0f;
            source.volume = 0f; // CabinEngineSound gates playback to this aircraft's cockpit.
        }

        private static void CheckEngineAudio(Build b)
        {
            foreach (var (type, field, clip) in new[] { ("Turbofan", "turbineAudio", "centurion_fan_loop"), ("JetNozzle", "thrustAudio", "centurion_thrust_loop") })
            {
                var drivers = b.Root.GetComponentsInChildren(GameType(type), true);
                if (drivers.Length != 2) throw new InvalidDataException("Engine audio requires two " + type + " drivers");
                foreach (var driver in drivers)
                    CheckEngineClip(EngineAudioSource(driver, field), clip);
            }
            var cabin = b.Parts["cockpit"].transform.Find(CockpitRoot).GetComponent<AudioSource>();
            CheckEngineClip(cabin, "centurion_cabin_loop");
            if (cabin.playOnAwake || cabin.volume != 0f || cabin.spatialBlend != 0f || cabin.outputAudioMixerGroup == null)
                throw new InvalidDataException("Cabin engine source must start silent, 2D and routed to Effects_General");
            b.Report.Add("Engine audio: 2 centurion_fan_loop, 2 centurion_thrust_loop, 1 centurion_cabin_loop; cabin gated by CabinEngineSound");
        }

        private static void CheckEngineClip(AudioSource source, string name)
        {
            var expected = Load<AudioClip>(EngineAudioFolder + "/" + name + ".wav");
            if (source == null || source.clip != expected || !source.loop || expected.channels != 1)
                throw new InvalidDataException("Engine audio must use the mono mod-owned loop " + name + ", never the stock clip");
        }

        // The detailed fan turns at run time: FanSpin (src/Centurion) turns fan_K_mesh about its local Z at engine K's
        // RPM, since the stock Turbofan turns nothing (the Alkyon's engine1 is the Turbofan, a capsule and an audio
        // source, no rotor) and the bundle binds no DLL type (docs/M3-DESIGN.md). The fan keeps the blockout's pivot
        // and rotation, so the build fails if the art moves either: a pivot off the nacelle's axis or a spin axis off
        // local Z would make the turning fan wobble in its case.
        private static void AddFan(Build b, int k, Transform nacelle)
        {
            var name = "fan_" + k;
            AddVisual(b, name, nacelle);
            var fan = b.Visuals[name];
            var axis = (List<object>)b.Blockout.Parts[name].Props["spin_axis_unity"];
            var spin = new Vector3(Convert.ToSingle(axis[0]), Convert.ToSingle(axis[1]), Convert.ToSingle(axis[2]));
            var offAxis = Vector3.Cross(fan.position - nacelle.position, fan.forward).magnitude;
            if (Mathf.Abs(Mathf.Abs(spin.z) - 1f) > 1e-4f || offAxis > 1e-3f)
                throw new InvalidDataException($"{name} must spin about its local Z on the nacelle's axis (FanSpin): spin axis {spin}, pivot {offAxis:F4} m off the axis.");
        }
    }
}
