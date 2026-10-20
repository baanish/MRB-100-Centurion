using System;
using System.IO;
using BepInEx;
using BepInEx.Bootstrap;

namespace Centurion;

/// <summary>
/// Gives NOAutopilot a Centurion profile. Its global gains hunt 47 deg of bank and wind up against the Centurion's slow,
/// alpha-limited pitch; NOAutopilotProfile.json softens six loops for this aircraft only (NOAutopilot picks a profile by
/// the aircraft's key, so no other aircraft changes). NOAutopilot reads player profiles only from its own config folder
/// (PidProfileManager.UserDir), not from another mod's, so the plugin writes the file there once. A profile already there
/// is the player's and is never overwritten; without NOAutopilot nothing is written.
/// </summary>
static class NoAutopilotProfile
{
    const string NoAutopilotGuid = "com.qwerty1423.NOAutopilot";
    const string Resource = "Centurion.NoAutopilotProfile.json";
    const string CenturionKey = "baanish_centurion";

    internal static void Install()
    {
        if (!Chainloader.PluginInfos.ContainsKey(NoAutopilotGuid)) return;
        string path = Path.Combine(Paths.ConfigPath, "NOAutopilot", "Profiles", CenturionKey + ".json");
        if (File.Exists(path)) return;
        try
        {
            using Stream? stream = typeof(NoAutopilotProfile).Assembly.GetManifestResourceStream(Resource);
            if (stream == null)
            {
                CenturionPlugin.Log.Error("NOAutopilot profile: embedded " + Resource + " missing");
                return;
            }
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using (var file = File.Create(path))
                stream.CopyTo(file);
            CenturionPlugin.Log.Info("NOAutopilot profile: wrote the Centurion profile to " + path);
        }
        catch (Exception e)
        {
            CenturionPlugin.Log.Error("NOAutopilot profile: could not write " + path + ": " + e.Message);
        }
    }
}
