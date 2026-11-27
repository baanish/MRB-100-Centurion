using System.Reflection;

namespace Centurion;

static class LiveryWorkshopTag
{
    internal const string Tag = "MRB-100 Centurion";

    // The authoring assemblies and the 0.34.2 runtime predate this field.
    static readonly FieldInfo? TagField = typeof(UnitDefinition).GetField("WorkshopTag");
    static bool applied;

    internal static void Update(CenturionLog log)
    {
        if (applied || TagField == null || Encyclopedia.Lookup == null ||
            !Encyclopedia.Lookup.TryGetValue(CenturionPlugin.JsonKey, out var definition) ||
            definition is not AircraftDefinition aircraft)
            return;

        string tag = SetDefaultTag(TagField, aircraft);
        applied = true;
        log.Info($"workshop tag: {CenturionPlugin.JsonKey} = '{tag}'");
    }

    internal static string SetDefaultTag(FieldInfo field, AircraftDefinition aircraft)
    {
        if (field.GetValue(aircraft) is string { Length: > 0 } existingTag)
            return existingTag;

        field.SetValue(aircraft, Tag);
        return Tag;
    }
}
