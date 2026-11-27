using System.Collections.Generic;
using System.Linq;

namespace Centurion;

/// <summary>
/// One Centurion-sized rack of a weapon from an optional weapon pack, built at runtime by <see cref="PackBayMounts"/> from the
/// pack's own mount (<see cref="DonorKey"/>) when the pack is installed. Positions are in the hardpoint's frame (+x right,
/// +y up, +z forward), as the Centurion's own racks are (CenturionAuthor.AuthorBombMount). Every layer is centred across the
/// bay, so a layer with one store fewer than the one above it sits half a pitch over; layers are a cell high plus
/// <see cref="PackBayRecipes.Gap"/>, stacked down from <see cref="PackBayRecipes.RoofY"/>; rows stand along the bay a cell
/// long plus the gap apart, centred and then slid by <see cref="Slide"/>. A row may hold fewer stores than another where the
/// bay narrows around it.
/// </summary>
internal sealed class PackBayRecipe
{
    public readonly string Key, Pack, DonorKey, ProjectileKey;
    /// <summary>Hardpoint set: 0 the forward bay, 1 the aft bay.</summary>
    public readonly int Bay;
    /// <summary>Per row, nose row first: stores across the bay in each layer, bottom layer first. Every row has the same layers.</summary>
    public readonly int[][] RowLayers;
    /// <summary>
    /// The space each store is given, metres across, high and long, before the gap: the store's carried mesh box, or the
    /// larger box the rack was designed and cleared with where the store turned out smaller (PAB-125HD).
    /// </summary>
    public readonly float[] Cell;
    /// <summary>The store's carried mesh box about its own origin, min x, y, z then max x, y, z, measured from the pack's bundle.</summary>
    public readonly float[] StoreBox;
    /// <summary>Downward rail travel per layer, bottom layer first, metres.</summary>
    public readonly float[] LayerRail;
    /// <summary>Metres the rows are slid toward the nose from centred.</summary>
    public readonly float Slide;
    /// <summary>Offered only where the mission allows event content, named "EVENT: ...", as the LEGACY racks.</summary>
    public readonly bool Event;

    /// <summary>A rack whose rows are alike: <paramref name="rows"/> copies of <paramref name="layerColumns"/>.</summary>
    public PackBayRecipe(string key, string pack, string donorKey, string projectileKey, int bay, int rows, int[] layerColumns,
        float[] cell, float[] storeBox, float[] layerRail, float slide = 0f, bool @event = false)
        : this(key, pack, donorKey, projectileKey, bay, Enumerable.Repeat(layerColumns, rows).ToArray(), cell, storeBox, layerRail, slide, @event)
    {
    }

    public PackBayRecipe(string key, string pack, string donorKey, string projectileKey, int bay, int[][] rowLayers,
        float[] cell, float[] storeBox, float[] layerRail, float slide = 0f, bool @event = false)
    {
        Key = key;
        Pack = pack;
        DonorKey = donorKey;
        ProjectileKey = projectileKey;
        Bay = bay;
        RowLayers = rowLayers;
        Cell = cell;
        StoreBox = storeBox;
        LayerRail = layerRail;
        Slide = slide;
        Event = @event;
    }

    public int Rows => RowLayers.Length;
    public int Layers => RowLayers[0].Length;
    public int Rounds => RowLayers.Sum(row => row.Sum());
}

/// <summary>A store's place in a rack: its cell centre in the hardpoint frame, its release priority and rail.</summary>
internal readonly struct PackBaySlot
{
    public readonly int Layer, Row, Column, Priority;
    public readonly float X, Y, Z, Rail;

    public PackBaySlot(int layer, int row, int column, int priority, float x, float y, float z, float rail)
    {
        Layer = layer;
        Row = row;
        Column = column;
        Priority = priority;
        X = x;
        Y = y;
        Z = z;
        Rail = rail;
    }
}

internal static class PackBayRecipes
{
    /// <summary>The Centurion's store gap on every axis (CenturionAuthor.BombStoreGap).</summary>
    public const float Gap = 0.0801f;
    /// <summary>The bay roof in the hardpoint frame: CenturionAuthor.BombGridTop less BombHardpointHeight.</summary>
    public const float RoofY = 0.5799f;
    /// <summary>
    /// Every pack store rides its rail down at 4 m/s after 0.4 s, when the bay doors (3/s, BayDoor.openSpeed) are fully open;
    /// the longest rail, 3.08 m, ends 1.17 s after release, inside the Centurion's 4 s door hold.
    /// </summary>
    public const float RailSpeed = 4f, RailDelay = 0.4f;
    public const string Aryx = "Aryx Weaponry Pack", Meridian = "Meridian Works";

    // The racks offered, by bay, from the owner's counts (docs/DECISIONS.md 2026-11-23, weapon packs; AGM-57L and AGM-84 at
    // the most that clears each bay, his later ruling, with Tusko-N added at 12 a bay, and the forward-only ARAD-120 cut
    // from 16 to 12 after its loaded take-off needed full back stick to rotate): each grid checked
    // offline against the Centurion prefab's closed bay with 0.10 m clearance and released straight down through the open
    // doors. Cells and store boxes are measured from Aryx Weaponry Pack 1.1.2's and Meridian Works 1.3.0's bundles (the
    // PAB-125HD from the game's own mount, which Meridian Works switches on). Rails take each layer's top 0.10 m below the
    // closed doors' lowest vertex, rounded up to 1 cm. Written by a generator from the rack design; edit the design, not
    // these lines.
    // begin recipes
    public static readonly PackBayRecipe[] All =
    {
        new("baanish_centurion_pack_aryx_atlatl_aft", Aryx, "Aryx_SmallCruiseMissile1_Octo_Internal", "Aryx_Wep_SmallCruiseMissile1", 1, 3, new int[] { 5, 5, 5, 5 },
            new float[] { 0.26228f, 0.30173f, 2.01562f }, new float[] { -0.13114f, -0.13114f, -0.91871f, 0.13114f, 0.17059f, 1.09691f },
            new float[] { 1.93f, 2.31f, 2.7f, 3.08f }),
        new("baanish_centurion_pack_aryx_atlatl_fwd", Aryx, "Aryx_SmallCruiseMissile1_Octo_Internal", "Aryx_Wep_SmallCruiseMissile1", 0, 3, new int[] { 5, 5, 5, 5 },
            new float[] { 0.26228f, 0.30173f, 2.01562f }, new float[] { -0.13114f, -0.13114f, -0.91871f, 0.13114f, 0.17059f, 1.09691f },
            new float[] { 1.93f, 2.31f, 2.69f, 3.07f }),
        new("baanish_centurion_pack_aryx_cbo400_aft", Aryx, "Aryx_ClusterBomb1_Single_Internal", "aryx_clusterbomb1", 1, 2, new int[] { 4, 4, 4, 4 },
            new float[] { 0.44049f, 0.48403f, 2.43495f }, new float[] { -0.22028f, -0.22028f, -1.29053f, 0.22021f, 0.26375f, 1.14442f },
            new float[] { 1.39f, 1.95f, 2.51f, 3.08f }),
        new("baanish_centurion_pack_aryx_cbo400_fwd", Aryx, "Aryx_ClusterBomb1_Single_Internal", "aryx_clusterbomb1", 0, 2, new int[] { 4, 4, 4, 4 },
            new float[] { 0.44049f, 0.48403f, 2.43495f }, new float[] { -0.22028f, -0.22028f, -1.29053f, 0.22021f, 0.26375f, 1.14442f },
            new float[] { 1.38f, 1.95f, 2.51f, 3.07f }),
        new("baanish_centurion_pack_aryx_nemesis_aft", Aryx, "Aryx_FastAShM1_double_internal", "Aryx_FastAShM1", 1, 1, new int[] { 2, 2, 2, 2 },
            new float[] { 0.8265f, 0.54803f, 6.02609f }, new float[] { -0.41325f, -0.27495f, -2.6806f, 0.41325f, 0.27308f, 3.34549f },
            new float[] { 1.19f, 1.82f, 2.45f, 3.08f }),
        new("baanish_centurion_pack_aryx_nemesis_fwd", Aryx, "Aryx_FastAShM1_double_internal", "Aryx_FastAShM1", 0, 1, new int[] { 2, 2, 2, 2 },
            new float[] { 0.8265f, 0.54803f, 6.02609f }, new float[] { -0.41325f, -0.27495f, -2.6806f, 0.41325f, 0.27308f, 3.34549f },
            new float[] { 1.19f, 1.82f, 2.45f, 3.07f }),
        new("baanish_centurion_pack_aryx_pab3000lr_aft", Aryx, "aryx_wep_glidebomb_3000_single_internal", "aryx_wep_glidebomb_3000_m", 1, 2, new int[] { 2 },
            new float[] { 0.96101f, 0.99404f, 4.0644f }, new float[] { -0.48051f, -0.45343f, -2.14962f, 0.48051f, 0.54061f, 1.91478f },
            new float[] { 3.08f }),
        new("baanish_centurion_pack_aryx_pab3000lr_fwd", Aryx, "aryx_wep_glidebomb_3000_single_internal", "aryx_wep_glidebomb_3000_m", 0, 2, new int[] { 2 },
            new float[] { 0.96101f, 0.99404f, 4.0644f }, new float[] { -0.48051f, -0.45343f, -2.14962f, 0.48051f, 0.54061f, 1.91478f },
            new float[] { 3.07f }),
        new("baanish_centurion_pack_aryx_pgm400lr_aft", Aryx, "aryx_glidebomb400_internal_8x", "aryx_glidebomb400", 1, 2, new int[] { 4, 4, 4, 4 },
            new float[] { 0.53298f, 0.42449f, 2.98128f }, new float[] { -0.26649f, -0.21224f, -1.50118f, 0.26649f, 0.21224f, 1.4801f },
            new float[] { 1.56f, 2.07f, 2.57f, 3.08f }),
        new("baanish_centurion_pack_aryx_pgm400lr_fwd", Aryx, "aryx_glidebomb400_internal_8x", "aryx_glidebomb400", 0, 2, new int[] { 4, 4, 4, 4 },
            new float[] { 0.53298f, 0.42449f, 2.98128f }, new float[] { -0.26649f, -0.21224f, -1.50118f, 0.26649f, 0.21224f, 1.4801f },
            new float[] { 1.56f, 2.07f, 2.57f, 3.07f }),
        new("baanish_centurion_pack_aryx_tuskon_aft", Aryx, "Aryx_Wep_TuskoN_Tactical_Internal", "Aryx_Wep_TuskoN", 1, 2, new int[] { 3, 3 },
            new float[] { 0.57667f, 0.57667f, 3.86577f }, new float[] { -0.28833f, -0.28833f, -1.93161f, 0.28833f, 0.28833f, 1.93416f },
            new float[] { 2.42f, 3.08f }),
        new("baanish_centurion_pack_aryx_tuskon_fwd", Aryx, "Aryx_Wep_TuskoN_Tactical_Internal", "Aryx_Wep_TuskoN", 0, 2, new int[] { 3, 3 },
            new float[] { 0.57667f, 0.57667f, 3.86577f }, new float[] { -0.28833f, -0.28833f, -1.93161f, 0.28833f, 0.28833f, 1.93416f },
            new float[] { 2.42f, 3.07f }),
        new("baanish_centurion_pack_meridian_agm33l_aft", Meridian, "MeridianAGM33L_internal", "MeridianAGM33L_Missile", 1, 2, new int[] { 4, 4, 4 },
            new float[] { 0.54316f, 0.54315f, 3.70236f }, new float[] { -0.27158f, -0.27158f, -1.85118f, 0.27158f, 0.27158f, 1.85118f },
            new float[] { 1.83f, 2.45f, 3.08f }),
        new("baanish_centurion_pack_meridian_agm33l_fwd", Meridian, "MeridianAGM33L_internal", "MeridianAGM33L_Missile", 0, 2, new int[] { 4, 4, 4 },
            new float[] { 0.54316f, 0.54315f, 3.70236f }, new float[] { -0.27158f, -0.27158f, -1.85118f, 0.27158f, 0.27158f, 1.85118f },
            new float[] { 1.83f, 2.45f, 3.07f }),
        new("baanish_centurion_pack_meridian_agm57l_aft", Meridian, "MeridianAGM57L_internal", "MeridianAGM57L_Missile", 1, 2, new int[] { 3, 4, 4 },
            new float[] { 0.70918f, 0.70918f, 3.67559f }, new float[] { -0.35459f, -0.35459f, -1.83779f, 0.35459f, 0.35459f, 1.83779f },
            new float[] { 1.5f, 2.29f, 3.08f }, slide: -0.1f),
        new("baanish_centurion_pack_meridian_agm57l_fwd", Meridian, "MeridianAGM57L_internal", "MeridianAGM57L_Missile", 0, new[] { new int[] { 3, 3, 3 }, new int[] { 3, 4, 4 } },
            new float[] { 0.70918f, 0.70918f, 3.67559f }, new float[] { -0.35459f, -0.35459f, -1.83779f, 0.35459f, 0.35459f, 1.83779f },
            new float[] { 1.5f, 2.29f, 3.07f }),
        new("baanish_centurion_pack_meridian_agm84_aft", Meridian, "MeridianAGM84_internal", "MeridianAGM84_Missile", 1, new[] { new int[] { 1, 3, 3 }, new int[] { 2, 3, 3 } },
            new float[] { 0.78736f, 0.78736f, 3.95224f }, new float[] { -0.39368f, -0.39368f, -1.97612f, 0.39368f, 0.39368f, 1.97612f },
            new float[] { 1.34f, 2.21f, 3.08f }),
        new("baanish_centurion_pack_meridian_agm84_fwd", Meridian, "MeridianAGM84_internal", "MeridianAGM84_Missile", 0, 2, new int[] { 1, 3, 3 },
            new float[] { 0.78736f, 0.78736f, 3.95224f }, new float[] { -0.39368f, -0.39368f, -1.97612f, 0.39368f, 0.39368f, 1.97612f },
            new float[] { 1.34f, 2.21f, 3.07f }),
        new("baanish_centurion_pack_meridian_agm92_aft", Meridian, "MeridianAGM92_internal", "MeridianAGM92_Missile", 1, 2, new int[] { 2, 2 },
            new float[] { 1.06994f, 1.08264f, 4.02704f }, new float[] { -0.53497f, -0.54132f, -2.01352f, 0.53497f, 0.54132f, 2.01352f },
            new float[] { 1.91f, 3.08f }),
        new("baanish_centurion_pack_meridian_agm92_fwd", Meridian, "MeridianAGM92_internal", "MeridianAGM92_Missile", 0, 2, new int[] { 2, 2 },
            new float[] { 1.06994f, 1.08264f, 4.02704f }, new float[] { -0.53497f, -0.54132f, -2.01352f, 0.53497f, 0.54132f, 2.01352f },
            new float[] { 1.91f, 3.07f }),
        new("baanish_centurion_pack_meridian_arad120_fwd", Meridian, "MeridianARAD200_internal", "MeridianARAD200_Missile", 0, 1, new int[] { 4, 4, 4 },
            new float[] { 0.53365f, 0.49059f, 4.5441f }, new float[] { -0.26683f, -0.2453f, -2.27205f, 0.26683f, 0.2453f, 2.27205f },
            new float[] { 1.93f, 2.5f, 3.07f }),
        new("baanish_centurion_pack_meridian_blackarrow_aft", Meridian, "MeridianBlackArrow_internal", "MeridianBlackArrow_Missile", 1, 3, new int[] { 5, 5, 5, 5 },
            new float[] { 0.27939f, 0.29227f, 2.09706f }, new float[] { -0.13664f, -0.15353f, -1.04853f, 0.14274f, 0.13874f, 1.04853f },
            new float[] { 1.96f, 2.33f, 2.71f, 3.08f }),
        new("baanish_centurion_pack_meridian_blackarrow_fwd", Meridian, "MeridianBlackArrow_internal", "MeridianBlackArrow_Missile", 0, 3, new int[] { 5, 5, 5, 5 },
            new float[] { 0.27939f, 0.29227f, 2.09706f }, new float[] { -0.13664f, -0.15353f, -1.04853f, 0.14274f, 0.13874f, 1.04853f },
            new float[] { 1.96f, 2.33f, 2.7f, 3.07f }),
        new("baanish_centurion_pack_meridian_bodkin_aft", Meridian, "MeridianGBP500_internal", "MeridianGBP500_Missile", 1, 2, new int[] { 4 },
            new float[] { 0.55024f, 0.55024f, 3.05531f }, new float[] { -0.27512f, -0.27512f, -1.52766f, 0.27512f, 0.27512f, 1.52766f },
            new float[] { 3.08f }),
        new("baanish_centurion_pack_meridian_bodkin_fwd", Meridian, "MeridianGBP500_internal", "MeridianGBP500_Missile", 0, 2, new int[] { 4 },
            new float[] { 0.55024f, 0.55024f, 3.05531f }, new float[] { -0.27512f, -0.27512f, -1.52766f, 0.27512f, 0.27512f, 1.52766f },
            new float[] { 3.07f }),
        new("baanish_centurion_pack_meridian_exocet_aft", Meridian, "MeridianExocetAir_internal", "MeridianExocetAir_Missile", 1, 1, new int[] { 3, 3 },
            new float[] { 0.79795f, 0.79795f, 4.8415f }, new float[] { -0.39897f, -0.39897f, -2.42075f, 0.39897f, 0.39897f, 2.42075f },
            new float[] { 2.2f, 3.08f }),
        new("baanish_centurion_pack_meridian_exocet_fwd", Meridian, "MeridianExocetAir_internal", "MeridianExocetAir_Missile", 0, 1, new int[] { 3, 3 },
            new float[] { 0.79795f, 0.79795f, 4.8415f }, new float[] { -0.39897f, -0.39897f, -2.42075f, 0.39897f, 0.39897f, 2.42075f },
            new float[] { 2.2f, 3.07f }),
        new("baanish_centurion_pack_meridian_gbo900_aft", Meridian, "MeridianGBO900_internal", "MeridianGBO900_Missile", 1, 2, new int[] { 2, 2 },
            new float[] { 1.04448f, 1.04448f, 3.96435f }, new float[] { -0.52224f, -0.52224f, -1.98218f, 0.52224f, 0.52224f, 1.98218f },
            new float[] { 1.95f, 3.08f }),
        new("baanish_centurion_pack_meridian_gbo900_fwd", Meridian, "MeridianGBO900_internal", "MeridianGBO900_Missile", 0, 2, new int[] { 2, 2 },
            new float[] { 1.04448f, 1.04448f, 3.96435f }, new float[] { -0.52224f, -0.52224f, -1.98218f, 0.52224f, 0.52224f, 1.98218f },
            new float[] { 1.95f, 3.07f }),
        new("baanish_centurion_pack_meridian_hsm160_aft", Meridian, "MeridianHSM160_internal", "MeridianHSM160_Missile", 1, 1, new int[] { 3, 3 },
            new float[] { 0.79172f, 0.69795f, 4.78365f }, new float[] { -0.39586f, -0.23462f, -2.38814f, 0.39586f, 0.46333f, 2.39551f },
            new float[] { 2.3f, 3.08f }),
        new("baanish_centurion_pack_meridian_hsm160_fwd", Meridian, "MeridianHSM160_internal", "MeridianHSM160_Missile", 0, 1, new int[] { 3, 3 },
            new float[] { 0.79172f, 0.69795f, 4.78365f }, new float[] { -0.39586f, -0.23462f, -2.38814f, 0.39586f, 0.46333f, 2.39551f },
            new float[] { 2.3f, 3.07f }),
        new("baanish_centurion_pack_meridian_hsm160c_aft", Meridian, "MeridianHSM160C_internal", "MeridianHSM160C_Missile", 1, 1, new int[] { 3, 3 },
            new float[] { 0.79172f, 0.69795f, 4.78365f }, new float[] { -0.39586f, -0.23462f, -2.38814f, 0.39586f, 0.46333f, 2.39551f },
            new float[] { 2.3f, 3.08f }),
        new("baanish_centurion_pack_meridian_hsm160c_fwd", Meridian, "MeridianHSM160C_internal", "MeridianHSM160C_Missile", 0, 1, new int[] { 3, 3 },
            new float[] { 0.79172f, 0.69795f, 4.78365f }, new float[] { -0.39586f, -0.23462f, -2.38814f, 0.39586f, 0.46333f, 2.39551f },
            new float[] { 2.3f, 3.07f }),
        new("baanish_centurion_pack_meridian_hsm160m_aft", Meridian, "MeridianHSM160M_internal", "MeridianHSM160M_Missile", 1, 1, new int[] { 3, 3, 3 },
            new float[] { 0.79172f, 0.69795f, 4.78365f }, new float[] { -0.39586f, -0.23462f, -2.38814f, 0.39586f, 0.46333f, 2.39551f },
            new float[] { 1.52f, 2.3f, 3.08f }, @event: true),
        new("baanish_centurion_pack_meridian_hsm160m_fwd", Meridian, "MeridianHSM160M_internal", "MeridianHSM160M_Missile", 0, 1, new int[] { 3, 3, 3 },
            new float[] { 0.79172f, 0.69795f, 4.78365f }, new float[] { -0.39586f, -0.23462f, -2.38814f, 0.39586f, 0.46333f, 2.39551f },
            new float[] { 1.52f, 2.3f, 3.07f }, @event: true),
        new("baanish_centurion_pack_meridian_hsm160n_aft", Meridian, "MeridianHSM160N_internal", "MeridianHSM160N_Missile", 1, 1, new int[] { 3, 3 },
            new float[] { 0.79172f, 0.69795f, 4.78365f }, new float[] { -0.39586f, -0.23462f, -2.38814f, 0.39586f, 0.46333f, 2.39551f },
            new float[] { 2.3f, 3.08f }),
        new("baanish_centurion_pack_meridian_hsm160n_fwd", Meridian, "MeridianHSM160N_internal", "MeridianHSM160N_Missile", 0, 1, new int[] { 3, 3 },
            new float[] { 0.79172f, 0.69795f, 4.78365f }, new float[] { -0.39586f, -0.23462f, -2.38814f, 0.39586f, 0.46333f, 2.39551f },
            new float[] { 2.3f, 3.07f }),
        new("baanish_centurion_pack_meridian_kalibr_aft", Meridian, "MeridianKalibr_internal", "MeridianKalibr_Missile", 1, 1, new int[] { 4, 4, 4, 4 },
            new float[] { 0.51518f, 0.52438f, 5.27681f }, new float[] { -0.25758f, -0.26877f, -2.63841f, 0.2576f, 0.25561f, 2.63841f },
            new float[] { 1.26f, 1.87f, 2.47f, 3.08f }),
        new("baanish_centurion_pack_meridian_kalibr_fwd", Meridian, "MeridianKalibr_internal", "MeridianKalibr_Missile", 0, 1, new int[] { 4, 4, 4, 4 },
            new float[] { 0.51518f, 0.52438f, 5.27681f }, new float[] { -0.25758f, -0.26877f, -2.63841f, 0.2576f, 0.25561f, 2.63841f },
            new float[] { 1.26f, 1.87f, 2.47f, 3.07f }),
        new("baanish_centurion_pack_meridian_kalibrew_aft", Meridian, "MeridianKalibrEW_internal", "MeridianKalibrEW_Missile", 1, 1, new int[] { 4, 4, 4, 4 },
            new float[] { 0.51518f, 0.52438f, 5.27681f }, new float[] { -0.25758f, -0.26877f, -2.63841f, 0.2576f, 0.25561f, 2.63841f },
            new float[] { 1.26f, 1.87f, 2.47f, 3.08f }),
        new("baanish_centurion_pack_meridian_kalibrew_fwd", Meridian, "MeridianKalibrEW_internal", "MeridianKalibrEW_Missile", 0, 1, new int[] { 4, 4, 4, 4 },
            new float[] { 0.51518f, 0.52438f, 5.27681f }, new float[] { -0.25758f, -0.26877f, -2.63841f, 0.2576f, 0.25561f, 2.63841f },
            new float[] { 1.26f, 1.87f, 2.47f, 3.07f }),
        new("baanish_centurion_pack_meridian_pab125hd_aft", Meridian, "bomb_125HD_triple", "bomb_125_HD", 1, 4, new int[] { 5, 5, 5 },
            new float[] { 0.39949f, 0.33893f, 1.92131f }, new float[] { -0.10457f, -0.10257f, -0.83909f, 0.10457f, 0.11974f, 0.83306f },
            new float[] { 2.24f, 2.66f, 3.08f }),
        new("baanish_centurion_pack_meridian_pab125hd_fwd", Meridian, "bomb_125HD_triple", "bomb_125_HD", 0, 4, new int[] { 5, 5, 5 },
            new float[] { 0.39949f, 0.33893f, 1.92131f }, new float[] { -0.10457f, -0.10257f, -0.83909f, 0.10457f, 0.11974f, 0.83306f },
            new float[] { 2.24f, 2.66f, 3.07f }),
        new("baanish_centurion_pack_meridian_yashma_aft", Meridian, "MeridianYashma_internalx2", "MeridianYashma_Missile", 1, 1, new int[] { 4, 4, 4 },
            new float[] { 0.67242f, 0.67242f, 6.03868f }, new float[] { -0.33621f, -0.33621f, -3.03868f, 0.33621f, 0.33621f, 3f },
            new float[] { 1.57f, 2.32f, 3.08f }),
        new("baanish_centurion_pack_meridian_yashma_fwd", Meridian, "MeridianYashma_internalx2", "MeridianYashma_Missile", 0, 1, new int[] { 4, 4, 4 },
            new float[] { 0.67242f, 0.67242f, 6.03868f }, new float[] { -0.33621f, -0.33621f, -3.03868f, 0.33621f, 0.33621f, 3f },
            new float[] { 1.57f, 2.32f, 3.07f }, slide: -1f),
    };
    // end recipes

    /// <summary>
    /// The rack's slots in release order: bottom layer first, then nose to tail, then left to right, each a priority one
    /// higher than the last, so the stock sort (lowest priority first, WeaponStation.SortWeapons) releases them in that order.
    /// </summary>
    public static List<PackBaySlot> Slots(PackBayRecipe recipe)
    {
        var slots = new List<PackBaySlot>(recipe.Rounds);
        float w = recipe.Cell[0] + Gap, h = recipe.Cell[1] + Gap, l = recipe.Cell[2] + Gap;
        for (int layer = 0; layer < recipe.Layers; layer++)
            for (int row = 0; row < recipe.Rows; row++)
            {
                int columns = recipe.RowLayers[row][layer];
                for (int column = 0; column < columns; column++)
                    slots.Add(new PackBaySlot(layer, row, column, slots.Count,
                        (column - (columns - 1) * 0.5f) * w,
                        RoofY - recipe.Cell[1] * 0.5f - (recipe.Layers - 1 - layer) * h,
                        ((recipe.Rows - 1) * 0.5f - row) * l + recipe.Slide,
                        recipe.LayerRail[layer]));
            }

        return slots;
    }

    /// <summary>The top of a layer's cells in the hardpoint frame, layer 0 the bottom.</summary>
    public static float LayerTop(PackBayRecipe recipe, int layer) => RoofY - (recipe.Layers - 1 - layer) * (recipe.Cell[1] + Gap);

    /// <summary>The rack's release time from trigger to its top layer's rail end, seconds.</summary>
    public static float LongestRelease(PackBayRecipe recipe) => RailDelay + recipe.LayerRail[recipe.Layers - 1] / RailSpeed;
}
