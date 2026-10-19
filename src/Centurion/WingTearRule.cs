using static System.FormattableString;

namespace Centurion;

/// <summary>
/// When the extended span tears off (docs/SPEC.md "Telescoping and tear limits"): extension past 0.25 and gravity-corrected load
/// factor above +4.0 or below -1.0 held for 0.5 s. The limit is the wing's own, which a full pull at high speed can reach
/// through the fly-by-wire, so the panels tear when flown past the envelope. There is no speed trigger: the stage drag rise
/// slows the extended aircraft instead (owner, 2026-10-12). Runs where the aircraft is simulated; <see cref="TelescopeController"/>
/// does the tear itself.
/// </summary>
sealed class WingTearRule
{
    public const float MinExtension = 0.25f;
    public const float HoldS = 0.5f;
    public const float WarnFraction = 0.9f;
    const float MaxNz = 4.0f, MinNz = -1.0f;

    // Which limit a step is past or near; its line is formatted only when it is logged, since this runs every physics step.
    enum Limit { None, LoadHigh, LoadLow }

    readonly CenturionLog log;
    float heldS;
    Limit armedBy;
    string armedLine = "";

    public WingTearRule(CenturionLog log) => this.log = log;

    /// <summary>"intact", "armed" while a limit is held, or "torn".</summary>
    public string State => Fired ? "torn" : armedBy != Limit.None ? "armed" : "intact";

    public bool Fired { get; private set; }

    /// <summary>One physics step; true on the step the tear fires.</summary>
    public bool Step(float extension, float nz, float dt)
    {
        if (Fired)
        {
            return false;
        }

        Limit over = extension <= MinExtension ? Limit.None
            : nz > MaxNz ? Limit.LoadHigh
            : nz < MinNz ? Limit.LoadLow
            : Limit.None;
        if (over == Limit.None)
        {
            if (armedBy != Limit.None)
            {
                log.Stage("tear-disarmed", Invariant($"back inside the limits after {heldS:0.00} s (armed by {armedLine})"));
            }

            armedBy = Limit.None;
            heldS = 0f;
            if (extension > MinExtension)
            {
                Warn(nz);
            }

            return false;
        }

        if (armedBy == Limit.None)
        {
            armedLine = Describe(over, nz, near: false);
            log.Stage("tear-armed", Invariant($"{armedLine} at extension {extension:0.00}"));
        }

        armedBy = over;
        heldS += dt;
        if (heldS < HoldS)
        {
            return false;
        }

        Fired = true;
        log.Info(Invariant($"tear-fired: {Describe(over, nz, near: false)} for {heldS:0.00} s at extension {extension:0.00}"));
        return true;
    }

    void Warn(float nz)
    {
        Limit near = nz > WarnFraction * MaxNz ? Limit.LoadHigh
            : nz < WarnFraction * MinNz ? Limit.LoadLow
            : Limit.None;
        if (near != Limit.None && log.StageDue("tear-warn"))
        {
            log.StageLine("tear-warn", "past 90% of a tear limit: " + Describe(near, nz, near: true));
        }
    }

    static string Describe(Limit limit, float nz, bool near) => limit == Limit.LoadHigh
        ? Invariant($"load factor {nz:0.00}{(near ? ", limit " : " above ")}+{MaxNz}")
        : Invariant($"load factor {nz:0.00}{(near ? ", limit " : " below ")}{MinNz}");
}
