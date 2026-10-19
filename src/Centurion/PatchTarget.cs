using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace Centurion;

/// <summary>
/// One Harmony patch the mod wants, named by the feature it serves. The game method is looked up by name, so a game
/// update that renames or removes it switches that feature off instead of failing the plugin (skill patching.md).
/// </summary>
public sealed class PatchTarget
{
    public PatchTarget(string feature, Type type, string method, Type[]? parameters = null, MethodInfo? prefix = null, MethodInfo? postfix = null, MethodInfo? transpiler = null)
    {
        Feature = feature;
        Type = type;
        Method = method;
        Parameters = parameters;
        Prefix = prefix;
        Postfix = postfix;
        Transpiler = transpiler;
    }

    public string Feature { get; }
    public Type Type { get; }
    public string Method { get; }
    public Type[]? Parameters { get; }
    public MethodInfo? Prefix { get; }
    public MethodInfo? Postfix { get; }
    public MethodInfo? Transpiler { get; }

    string Name => Type.Name + "." + Method;

    /// <summary>
    /// Patches each target and logs one line per target: "found/patched" or "missing: feature off". Returns the features
    /// switched off, so their code can stand down.
    /// </summary>
    public static HashSet<string> InstallAll(Harmony harmony, IReadOnlyList<PatchTarget> targets, CenturionLog log)
    {
        var off = new HashSet<string>();
        var installed = new List<(PatchTarget Target, MethodInfo Original)>();
        log.Info($"Harmony: {targets.Count} patch targets");
        foreach (PatchTarget target in targets)
        {
            if (off.Contains(target.Feature)) continue;
            try
            {
                MethodInfo? original = AccessTools.DeclaredMethod(target.Type, target.Method, target.Parameters);
                if (original == null) throw new MissingMethodException(target.Type.FullName, target.Method);
                installed.Add((target, original));
                harmony.Patch(
                    original,
                    target.Prefix == null ? null : new HarmonyMethod(target.Prefix),
                    target.Postfix == null ? null : new HarmonyMethod(target.Postfix),
                    target.Transpiler == null ? null : new HarmonyMethod(target.Transpiler));
                log.Info($"patch {target.Feature}: {target.Name} found/patched");
            }
            catch (Exception e)
            {
                off.Add(target.Feature);
                // Include the failed target: Harmony may have registered a prefix before a transpiler threw.
                for (int i = installed.Count - 1; i >= 0; i--)
                {
                    var entry = installed[i];
                    if (entry.Target.Feature != target.Feature) continue;
                    foreach (MethodInfo? patch in new[] { entry.Target.Transpiler, entry.Target.Prefix, entry.Target.Postfix })
                    {
                        if (patch != null) harmony.Unpatch(entry.Original, patch);
                    }
                }
                log.Error($"patch {target.Feature}: {target.Name} failed to patch: feature off ({e.GetType().Name}: {e.Message})");
            }
        }

        return off;
    }
}
