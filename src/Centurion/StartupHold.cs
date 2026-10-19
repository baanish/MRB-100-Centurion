using BepInEx.Bootstrap;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// Every automatic start waits on MainMenu.WaitForLoaded, State == Loaded: -autoHost, -autoConnect, a dedicated server's
/// mission and a Steam lobby join (CommandLineArgParser.cs:178-350, DedicatedServerManager.cs:106, SteamLobby.cs:494). The game
/// sets Loaded when its own loads finish (MainMenu.cs:198), and Blueprinter adds the Centurion to the encyclopedia from a frame
/// to several seconds later. So a host started that way spawned none of the mission's Centurions ("Unit Type
/// 'baanish_centurion' not found in Encyclopedia", runs 20261015-021324 and -022014) and a client started that way registered
/// no Centurion prefab with Mirage (NetworkManagerNuclearOption.RegisterPrefabs), so every Centurion spawn failed there ("No
/// prefab for 1E4D7863", runs 20261012-134304 and -134631). The state reads Loading until the Centurion is in
/// Encyclopedia.Lookup and Blueprinter's ops after it have had <see cref="SettleS"/>, for at most <see cref="MaxHoldS"/>, and
/// only while Blueprinter is loaded. A start from the menu does not wait on it.
/// </summary>
static class StartupHold
{
    const string CenturionKey = "baanish_centurion";
    const string BlueprinterGuid = "com.nikkorap.blueprinter";
    const float SettleS = 1f, MaxHoldS = 30f;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("startup-hold", typeof(MainMenu), "get_State", postfix: AccessTools.Method(typeof(StartupHold), nameof(AfterState))),
    };

    static float heldSince = float.NaN, registeredAt = float.NaN;
    static bool released;

    static void AfterState(ref MainMenu.LoadingState __result)
    {
        if (CenturionPlugin.FeaturesOff.Contains("startup-hold")) return;
        if (__result == MainMenu.LoadingState.Loaded && !released && Holding())
        {
            __result = MainMenu.LoadingState.Loading;
        }
    }

    static bool Holding()
    {
        if (!Chainloader.PluginInfos.ContainsKey(BlueprinterGuid))
        {
            released = true;
            return false;
        }

        float now = Time.realtimeSinceStartup;
        if (float.IsNaN(heldSince))
        {
            heldSince = now;
        }

        if (float.IsNaN(registeredAt) && Encyclopedia.Lookup != null && Encyclopedia.Lookup.ContainsKey(CenturionKey))
        {
            registeredAt = now;
        }

        bool settled = !float.IsNaN(registeredAt) && now - registeredAt >= SettleS;
        if (!settled && now - heldSince < MaxHoldS)
        {
            return true;
        }

        released = true;
        CenturionPlugin.Log.Info(Invariant($"startup hold: released {now - heldSince:0.0} s after the game's menu loaded, {(settled ? "the Centurion registered" : $"no Centurion in the encyclopedia after {MaxHoldS} s")}"));
        return false;
    }
}
