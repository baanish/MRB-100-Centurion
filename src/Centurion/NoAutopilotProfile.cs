using System;
using System.IO;
using System.Text.RegularExpressions;
using BepInEx;
using BepInEx.Bootstrap;

namespace Centurion;

/// <summary>
/// Gives NOAutopilot a Centurion profile. Its global gains hunt 47 deg of bank and wind up against the Centurion's slow,
/// alpha-limited pitch; NOAutopilotProfile.json softens the loops for this aircraft only (NOAutopilot picks a profile by
/// the aircraft's key, so no other aircraft changes). NOAutopilot reads player profiles only from its own config folder
/// (PidProfileManager.UserDir), not from another mod's, so the plugin writes the file there once. A profile already there
/// is the player's: its values are never overwritten, and only a missing Trk entry is added. Without NOAutopilot nothing
/// is written.
/// </summary>
static class NoAutopilotProfile
{
    const string NoAutopilotGuid = "com.qwerty1423.NOAutopilot";
    const string Resource = "Centurion.NoAutopilotProfile.json";


    internal static void Install()
    {
        if (!Chainloader.PluginInfos.ContainsKey(NoAutopilotGuid)) return;
        string path = Path.Combine(Paths.ConfigPath, "NOAutopilot", "Profiles", CenturionPlugin.JsonKey + ".json");
        try
        {
            using Stream? stream = typeof(NoAutopilotProfile).Assembly.GetManifestResourceStream(Resource);
            if (stream == null)
            {
                CenturionPlugin.Log.Error("NOAutopilot profile: embedded " + Resource + " missing");
                return;
            }
            string profile = new StreamReader(stream).ReadToEnd();
            if (File.Exists(path))
            {
                AddTrackGains(path, profile);
                return;
            }
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, profile);
            CenturionPlugin.Log.Info("NOAutopilot profile: wrote the Centurion profile to " + path);
        }
        catch (Exception e)
        {
            CenturionPlugin.Log.Error("NOAutopilot profile: could not write " + path + ": " + e.Message);
        }
    }

    /// <summary>
    /// NOAutopilot 6.0 renamed the course loop's gains from Crs to Trk and ignores Crs, so a profile written by 0.1.x
    /// flew its track hold on NOAutopilot's global gains (a 4.5 deg bank cycle every 37 s). Adds the shipped Trk entry
    /// to a profile that has none and leaves every other value as the player has it; Crs stays for NOAutopilot 5.x.
    /// </summary>
    static void AddTrackGains(string path, string profile)
    {
        string existing = File.ReadAllText(path);
        if (existing.Contains("\"Trk\"")) return;
        Match track = Regex.Match(profile, "\"Trk\"\\s*:\\s*\"[^\"]*\"");
        int open = existing.IndexOf('{');
        if (!track.Success || open < 0) return;
        bool empty = existing.Substring(open + 1).TrimStart().StartsWith("}");
        File.WriteAllText(path, existing.Insert(open + 1, "\n  " + track.Value + (empty ? "\n" : ",")));
        CenturionPlugin.Log.Info("NOAutopilot profile: added the track gains (Trk) to " + path);
    }
}
