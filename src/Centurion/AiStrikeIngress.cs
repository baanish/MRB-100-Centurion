using System;

namespace Centurion;

static class AiStrikeIngress
{
    // The owner's 2026-11-24 ruling: "Make it scale to distance also do 10mi = 15k and 30mi = 50k".
    const float LowRangeM = 18520f, HighRangeM = 55560f;
    const float LowIngressM = 4572f, HighIngressM = 15240f;

    internal static float Height(float? homeRangeM, float cruiseEntryM)
    {
        float fraction = Math.Clamp(((homeRangeM ?? HighRangeM) - LowRangeM) / (HighRangeM - LowRangeM), 0f, 1f);
        return Math.Min(LowIngressM + (HighIngressM - LowIngressM) * fraction, cruiseEntryM);
    }
}
