using System.Diagnostics;
#if CENTURION_DEV
using System.Collections.Generic;
using System.Text;
using UnityEngine;
#endif
using BepInEx.Logging;

namespace Centurion;

/// <summary>
/// Every line the mod writes starts with "[Centurion]", so it greps out of LogOutput.log and player.log alike.
/// Info, Warning and Error are unbounded: for startup and one-shot lines only. Stage lines (systems-design section 8)
/// are bounded to one line per key per second, with a 60 s summary of how often each key fired; stage lines carry ids
/// and roles, never coordinates. Only a dev build (CENTURION_DEV) logs stages: in a release build the compiler drops every
/// Stage, StageLine and Tick call with its arguments, and StageDue is always false.
/// </summary>
public sealed class CenturionLog
{
    readonly ManualLogSource source;

    public CenturionLog(ManualLogSource source) => this.source = source;

    public void Info(string message) => source.LogInfo("[Centurion] " + message);

    public void Warning(string message) => source.LogWarning("[Centurion] " + message);

    public void Error(string message) => source.LogError("[Centurion] " + message);

    [Conditional("CENTURION_DEV")]
    public void Stage(string key, string message)
    {
        if (StageDue(key))
        {
            StageLine(key, message);
        }
    }

    [Conditional("CENTURION_DEV")]
    public void StageLine(string key, string message) => source.LogInfo("[Centurion] " + key + ": " + message);

#if CENTURION_DEV
    const float KeyIntervalS = 1f;
    const float SummaryIntervalS = 60f;

    sealed class StageKey
    {
        public float LastLoggedAt = float.NegativeInfinity;
        public int Count;
        public int Suppressed;
    }

    readonly Dictionary<string, StageKey> stages = new();
    float nextSummaryAt = SummaryIntervalS;

    /// <summary>Off drops stage lines and their summaries; Info, Warning and Error still print.</summary>
    public bool StageEnabled { get; set; }

    /// <summary>
    /// Counts a stage line under the key and says whether it prints now, for a caller on the physics step that builds its
    /// line only then and hands it to <see cref="StageLine"/>.
    /// </summary>
    public bool StageDue(string key)
    {
        if (!StageEnabled)
        {
            return false;
        }

        if (!stages.TryGetValue(key, out StageKey stage))
        {
            stage = new StageKey();
            stages.Add(key, stage);
        }

        stage.Count++;
        float now = Time.unscaledTime;
        if (now - stage.LastLoggedAt < KeyIntervalS)
        {
            stage.Suppressed++;
            return false;
        }

        stage.LastLoggedAt = now;
        return true;
    }

    /// <summary>Called every frame; prints and resets the per-key counters once every 60 s when any key fired.</summary>
    public void Tick()
    {
        float now = Time.unscaledTime;
        if (now < nextSummaryAt)
        {
            return;
        }

        nextSummaryAt = now + SummaryIntervalS;
        StringBuilder? line = null;
        foreach (KeyValuePair<string, StageKey> entry in stages)
        {
            StageKey stage = entry.Value;
            if (stage.Count == 0)
            {
                continue;
            }

            line ??= new StringBuilder("[Centurion] last 60 s:");
            line.Append(' ').Append(entry.Key).Append('=').Append(stage.Count);
            if (stage.Suppressed > 0)
            {
                line.Append(" (").Append(stage.Suppressed).Append(" suppressed)");
            }

            stage.Count = 0;
            stage.Suppressed = 0;
        }

        if (line != null)
        {
            source.LogInfo(line.ToString());
        }
    }
#else
    /// <summary>A release build logs no stage lines.</summary>
    public bool StageDue(string key) => false;
#endif
}
