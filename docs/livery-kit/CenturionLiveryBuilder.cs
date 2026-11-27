// Copy this file into Assets/Scripts/Editor in Shockfront's Nuclear-Option-Mods project.
// In Unity, use Nuclear Option > Create Centurion Livery Builder, then Build in its Inspector.
// For a command-line build, pass -batchmode -quit -buildTarget Win64 -projectPath <project>
//   -executeMethod CenturionLiveryBuilder.BuildFromCommandLine
//   -centurionTexture <png> -centurionBundle <folder name> -centurionName <display name>
//   [-centurionFaction Primeva|Boscali] [-centurionGloss 0] [-centurionNoCopy]
using System;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEngine;

public sealed class CenturionLiveryBuilder : LiveryBuilder
{
    private const string CenturionKey = "baanish_centurion";
    private const int AtlasSize = 4096;

    public override LiveryMetaData CreateMeta() => new LiveryMetaData
    {
        DisplayName = DisplayName,
        Faction = Faction ?? "",
        Aircraft = "",
        AircraftKey = CenturionKey,
    };

    public override void AddToBuilder(BundleBuilder builder)
    {
        ValidateBundleName(BundleName);
        if (string.IsNullOrWhiteSpace(DisplayName))
            throw new ArgumentException("Enter the name to show in the game's livery list.");
        if (!string.IsNullOrEmpty(Faction) && Faction != "Boscali" && Faction != "Primeva")
            throw new ArgumentException("Choose Boscali or Primeva, or leave Faction empty for both sides.");

        // Addressables uses the target platform's separators. The Workshop loader expects backslashes.
        var target = EditorUserBuildSettings.activeBuildTarget;
        if (target != BuildTarget.StandaloneWindows64 && target != BuildTarget.StandaloneWindows)
            throw new InvalidOperationException("Switch the Unity build target to Windows before building a livery.");

        string path = AssetDatabase.GetAssetPath(Texture);
        if (!string.Equals(Path.GetExtension(path), ".png", StringComparison.OrdinalIgnoreCase) ||
            !(AssetImporter.GetAtPath(path) is TextureImporter importer))
            throw new ArgumentException("Choose a PNG texture from the project's Assets folder.");
        importer.GetSourceTextureWidthAndHeight(out int width, out int height);
        if (width != AtlasSize || height != AtlasSize)
            throw new ArgumentException($"The Centurion needs a {AtlasSize} x {AtlasSize} PNG. This PNG is {width} x {height}.");

        importer.textureType = TextureImporterType.Default;
        importer.sRGBTexture = true;
        importer.mipmapEnabled = true;
        importer.maxTextureSize = AtlasSize;
        // The same import as the aircraft's own skin: normal-quality compression blocks thin coloured lines into a sawtooth.
        importer.textureCompression = TextureImporterCompression.CompressedHQ;
        importer.anisoLevel = 16;
        importer.filterMode = FilterMode.Trilinear;
        importer.ClearPlatformTextureSettings("Standalone");
        importer.SaveAndReimport();
        Texture = AssetDatabase.LoadAssetAtPath<Texture2D>(path);

        base.AddToBuilder(builder);
        // A fresh Addressables project can have unset catalog paths even after BundleBuilder sets the bundle paths.
        var settings = AddressableAssetSettingsDefaultObject.Settings;
        settings.RemoteCatalogBuildPath.SetVariableByName(settings, "Remote.BuildPath");
        settings.RemoteCatalogLoadPath.SetVariableByName(settings, "Remote.LoadPath");
    }

    [MenuItem("Nuclear Option/Create Centurion Livery Builder")]
    private static void CreateBuilder()
    {
        var builder = ScriptableObjectUtility.CreateAsset<CenturionLiveryBuilder>("Centurion Livery Builder", "Assets", true, true);
        Selection.activeObject = builder;
    }

    public static void BuildFromCommandLine()
    {
        var args = Environment.GetCommandLineArgs();
        string texture = Argument(args, "-centurionTexture");
        string bundle = Argument(args, "-centurionBundle");
        string name = Argument(args, "-centurionName");
        if (texture == null || bundle == null || name == null)
            throw new ArgumentException("Pass -centurionTexture <png> -centurionBundle <folder name> -centurionName <display name>.");
        ValidateBundleName(bundle);
        if (!string.Equals(Path.GetExtension(texture), ".png", StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("-centurionTexture must name a PNG file.");

        float gloss = float.Parse(Argument(args, "-centurionGloss") ?? "0", CultureInfo.InvariantCulture);
        if (!(gloss >= 0f && gloss <= 1f))
            throw new ArgumentException("-centurionGloss must be between 0 and 1.");

        const string folder = "Assets/CenturionLivery";
        Directory.CreateDirectory(folder);
        string assetPath = folder + "/" + bundle + ".png";
        if (!string.Equals(Path.GetFullPath(texture), Path.GetFullPath(assetPath), StringComparison.OrdinalIgnoreCase))
            File.Copy(texture, assetPath, true);
        AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);

        var builder = CreateInstance<CenturionLiveryBuilder>();
        builder.BundleName = bundle;
        builder.CopyToAppData = Array.IndexOf(args, "-centurionNoCopy") < 0;
        builder.Texture = AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);
        builder.Glossiness = gloss;
        builder.DisplayName = name;
        builder.Faction = Argument(args, "-centurionFaction") ?? "";
        var bundleBuilder = new BundleBuilder(bundle);
        builder.AddToBuilder(bundleBuilder);
        bundleBuilder.Build(builder.CopyToAppData);
    }

    private static void ValidateBundleName(string name)
    {
        // The stock builder uses this name in output paths and removes an existing build at that path.
        if (name == null || !Regex.IsMatch(name, @"\A[a-z0-9_]+\z"))
            throw new ArgumentException("Bundle Name must contain only lowercase letters, digits, and underscores.");
    }

    private static string Argument(string[] args, string flag)
    {
        int i = Array.IndexOf(args, flag);
        if (i < 0) return null;
        if (i + 1 == args.Length || args[i + 1].StartsWith("-", StringComparison.Ordinal))
            throw new ArgumentException($"{flag} requires a value.");
        return args[i + 1];
    }
}
